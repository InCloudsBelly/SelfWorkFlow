import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.fixtures.providers.fake_provider import FakeEffectPort
from selfworkflow.v3.approvals import (
    build_machine_authorization,
    build_operation_plan_subject,
    build_query_plan_subject,
    issue_approval,
)
from selfworkflow.v3.hashing import content_hash
from selfworkflow.v3.effects import EffectMutation
from selfworkflow.v3.plans import PlanError, build_operation_plan, build_query_plan
from selfworkflow.v3.project_lease import ProviderLeaseManager
from selfworkflow.v3.project_state import WorkspaceObservation
from selfworkflow.v3.runner import RunnerError, run_operation, run_query


H = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


class Observer:
    def __init__(self, observations): self.observations = iter(observations)
    def capture(self): return next(self.observations)


class Clock:
    def now(self): return NOW


class Process:
    def current(self): return 100, "start-a"
    def is_live(self, pid, start): return pid == 100 and start == "start-a"


class Boot:
    def current(self): return "boot-a"


class Store:
    def __init__(self): self.values = {}
    def read(self, key): return None if key not in self.values else dict(self.values[key])
    def create(self, key, document):
        if key in self.values: return False
        self.values[key] = dict(document); return True
    def replace(self, key, expected_hash, document):
        if key not in self.values or self.values[key]["leaseHash"] != expected_hash: return False
        self.values[key] = dict(document); return True
    def delete(self, key, expected_hash):
        if key not in self.values or self.values[key]["leaseHash"] != expected_hash: return False
        del self.values[key]; return True


class Replay:
    def __init__(self): self.values = set()
    def consume(self, key):
        if key in self.values: return False
        self.values.add(key); return True


class ProviderRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = {
            "targetKind": "managed-state-root", "targetId": "provider-index",
            "recursion": "bounded", "reparsePolicy": "reject",
            "allowedActions": ["sync"], "evidenceRequired": False,
        }
        self.manager = ProviderLeaseManager(
            store=Store(), clock=Clock(), process=Process(), boot=Boot(),
            host_identity="host-a", user_session="session-a",
        )

    def tearDown(self): self.temp.cleanup()

    def operation(self, *, confirmation_source="user-confirmation", nonce="nonce-a"):
        kwargs = dict(
            provider_id="fake.provider", operation_id="sync-incremental",
            binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root),
            executable=str(self.root / "provider.exe"), env={"LANG": "C"},
            env_allowlist=("LANG",), mutation_targets=(self.target,),
            execution_nonce=nonce, attempt_ref="attempt-a", adapter_render_hash=H,
            ownership_domain="selfworkflow-managed",
        )
        draft = build_operation_plan(**kwargs)
        approval = issue_approval(
            build_operation_plan_subject(draft.document),
            confirmation_source=confirmation_source, scope="one",
            target_hashes=tuple(item["canonicalTargetHash"] for item in draft.document["mutationTargets"]),
            issued_at=NOW, expires_at=NOW + timedelta(minutes=5),
            nonce=nonce,
        )
        return build_operation_plan(**kwargs, approval=approval), approval

    def lease(self, nonce="nonce-a"):
        return self.manager.acquire(
            project_root=str(self.root), provider_id="fake.provider",
            operation_id="sync-incremental", nonce=nonce,
        )

    def test_effect_port_uses_only_plan_command_and_receipt(self):
        plan, approval = self.operation()
        port = FakeEffectPort()
        receipt, result = run_operation(
            plan, approval=approval, effect_port=port, now=NOW,
            lease=self.lease(), lease_manager=self.manager,
            replay_store=Replay(), test_mode=True,
        )
        self.assertEqual(len(port.calls), 1)
        self.assertEqual(port.calls[0].argv, tuple(plan.document["commandSpec"]["argv"]))
        self.assertEqual(receipt["outcome"], "succeeded")
        self.assertEqual(result.exit_code, 0)

    def test_production_rejects_test_port_and_test_receipt(self):
        plan, approval = self.operation()
        with self.assertRaisesRegex(RunnerError, "test-effect-port-rejected"):
            run_operation(plan, approval=approval, effect_port=FakeEffectPort(), now=NOW)
        test_plan, test_approval = self.operation(confirmation_source="test-fixture", nonce="nonce-b")
        class ProductionPort(FakeEffectPort): is_test_port = False
        with self.assertRaisesRegex(RunnerError, "test-approval-rejected"):
            run_operation(
                test_plan, approval=test_approval, effect_port=ProductionPort(), now=NOW,
                lease=self.lease("nonce-b"), lease_manager=self.manager,
                replay_store=Replay(),
            )

    def test_env_cwd_and_post_plan_command_tamper_are_rejected(self):
        with self.assertRaisesRegex(PlanError, "env-injection"):
            build_operation_plan(
                provider_id="fake.provider", operation_id="inspect",
                binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root),
                executable=str(self.root / "provider.exe"), env={"BAD": "x;evil"},
                env_allowlist=("BAD",), mutation_targets=(self.target,),
                execution_nonce="nonce-a", attempt_ref="attempt-a",
                adapter_render_hash=H, ownership_domain="selfworkflow-managed",
            )
        generated_allowlist = (name for name in ("LANG",))
        generated = build_operation_plan(
            provider_id="fake.provider", operation_id="inspect",
            binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root),
            executable=str(self.root / "provider.exe"), env={"LANG": "C"},
            env_allowlist=generated_allowlist, mutation_targets=(self.target,),
            execution_nonce="nonce-env", attempt_ref="attempt-env",
            adapter_render_hash=H, ownership_domain="selfworkflow-managed",
        )
        self.assertEqual(generated.document["envAllowlist"], ["LANG"])
        plan, approval = self.operation()
        plan.document["commandSpec"]["argv"][0] = str(self.root / "other.exe")
        with self.assertRaisesRegex(RunnerError, "operation-plan-invalid"):
            run_operation(
                plan, approval=approval, effect_port=FakeEffectPort(), now=NOW,
                lease=self.lease(), lease_manager=self.manager,
                replay_store=Replay(), test_mode=True,
            )

    def test_local_write_query_requires_typed_machine_authorization(self):
        kwargs = dict(
            provider_id="fake.provider", operation_id="inspect",
            binding_snapshot_hash=H, plan_hash=H, adapter_hash=H,
            typed_input_schema_ref="query.input", typed_input={"q": "x"},
            adapter_render_hash=H, project_root=str(self.root),
            project_state_receipt_hash=H, workspace_fingerprint_hash=H,
            query_byte_budget=1000, call_limit=1, timeout_seconds=1,
            mutation_targets=(self.target,), execution_nonce="nonce-q",
            attempt_ref="attempt-q", executable=str(self.root / "provider.exe"),
            arguments=("query",),
        )
        with self.assertRaisesRegex(PlanError, "machine-project-authorization-required"):
            build_query_plan(**kwargs, side_effects="local-write")
        authorization = build_machine_authorization(
            provider_id="fake.provider", project_root=str(self.root),
            subject_kind="query-plan", operation_id="inspect",
            side_effect_class="local-write", execution_nonce="nonce-q",
            attempt_ref="attempt-q", issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5), nonce="machine-a",
        )
        draft = build_query_plan(
            **kwargs, side_effects="local-write",
            machine_authorization=authorization, now=NOW,
        )
        approval = issue_approval(
            build_query_plan_subject(draft.document),
            confirmation_source="user-confirmation", scope="query",
            target_hashes=tuple(item["canonicalTargetHash"] for item in draft.document["mutationTargets"]),
            issued_at=NOW, expires_at=NOW + timedelta(minutes=5), nonce="nonce-q",
        )
        build_query_plan(
            **kwargs, side_effects="local-write",
            machine_authorization=authorization, now=NOW, approval=approval,
        )

    def test_readonly_query_drift_fails_without_external_command_override(self):
        kwargs = dict(
            provider_id="fake.provider", operation_id="inspect",
            binding_snapshot_hash=H, plan_hash=H, adapter_hash=H,
            typed_input_schema_ref="query.input", typed_input={"q": "x"},
            adapter_render_hash=H, project_root=str(self.root),
            project_state_receipt_hash=H, workspace_fingerprint_hash=H,
            query_byte_budget=1000, call_limit=1, timeout_seconds=1,
            side_effects="none", mutation_targets=(), execution_nonce="nonce-q",
            attempt_ref="attempt-q", executable=str(self.root / "provider.exe"),
            arguments=("query",),
        )
        draft = build_query_plan(**kwargs)
        approval = issue_approval(
            build_query_plan_subject(draft.document),
            confirmation_source="user-confirmation", scope="query", target_hashes=(),
            issued_at=NOW, expires_at=NOW + timedelta(minutes=5), nonce="nonce-q",
        )
        plan = build_query_plan(**kwargs, approval=approval)
        pre = WorkspaceObservation(H, {"fingerprintHash": H}, ())
        post_hash = content_hash("other")
        post = WorkspaceObservation(post_hash, {"fingerprintHash": post_hash}, ("Source/a.cpp",))
        with self.assertRaisesRegex(RunnerError, "workspace-drift-during-query"):
            run_query(
                plan, approval=approval, effect_port=FakeEffectPort(),
                observer=Observer([pre, post]), now=NOW, returned_files=[],
                index_revision="1", index_completeness="complete",
                replay_store=Replay(), test_mode=True,
            )

    def test_required_effect_evidence_cannot_be_omitted(self):
        self.target["evidenceRequired"] = True
        plan, approval = self.operation()
        with self.assertRaisesRegex(RunnerError, "required-mutation-evidence-missing"):
            run_operation(
                plan, approval=approval,
                effect_port=FakeEffectPort(
                    mutations=(EffectMutation("managed-state", "provider-index", "sync"),),
                ),
                now=NOW, lease=self.lease(), lease_manager=self.manager,
                replay_store=Replay(), test_mode=True,
            )


if __name__ == "__main__": unittest.main()
