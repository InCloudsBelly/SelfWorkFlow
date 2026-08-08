import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.fixtures.providers.fake_provider import FakeEffectPort
from selfworkflow.v3.approvals import build_operation_plan_subject, build_query_plan_subject, issue_approval
from selfworkflow.v3.hashing import content_hash, project_root_hash
from selfworkflow.v3.plans import PlanError, build_operation_plan, build_query_plan
from selfworkflow.v3.project_state import WorkspaceObservation
from selfworkflow.v3.runner import RunnerError, run_operation, run_query

H = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


class Observer:
    def __init__(self, observations): self.observations = iter(observations)
    def capture(self): return next(self.observations)


class ProviderRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = {"targetKind": "managed-state-root", "canonicalTargetHash": H, "containmentRootHash": H, "recursion": "bounded", "reparsePolicy": "reject"}

    def tearDown(self): self.temp.cleanup()

    def operation(self, *, approval=True):
        draft = build_operation_plan(provider_id="fake.provider", operation_id="sync-incremental", binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root), executable=str(self.root / "provider.exe"), env={"LANG": "C"}, env_allowlist=("LANG",), mutation_targets=(self.target,), execution_nonce="nonce-a", attempt_ref="attempt-a", adapter_render_hash=H)
        receipt = None
        if approval:
            receipt = issue_approval(build_operation_plan_subject(draft.document), confirmation_source="user-confirmation", scope="one", target_hashes=(H,), issued_at=NOW, expires_at=NOW.replace(hour=23), nonce="nonce-a", attempt_ref="attempt-a")
            draft = build_operation_plan(provider_id="fake.provider", operation_id="sync-incremental", binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root), executable=str(self.root / "provider.exe"), env={"LANG": "C"}, env_allowlist=("LANG",), mutation_targets=(self.target,), execution_nonce="nonce-a", attempt_ref="attempt-a", adapter_render_hash=H, approval=receipt)
        return draft, receipt

    def test_effect_port_records_fixed_argv_and_receipt(self):
        plan, approval = self.operation()
        port = FakeEffectPort()
        receipt, result = run_operation(plan, approval=approval, effect_port=port, now=NOW, test_mode=True)
        self.assertEqual(len(port.calls), 1)
        self.assertEqual(port.calls[0].argv, (str(self.root / "provider.exe"), "--operation", "sync-incremental", "--project-root", plan.cwd))
        self.assertEqual(receipt["outcome"], "succeeded")
        self.assertEqual(result.exit_code, 0)

    def test_production_rejects_test_port_and_test_receipt(self):
        plan, approval = self.operation()
        with self.assertRaisesRegex(RunnerError, "test-effect-port-rejected"):
            run_operation(plan, approval=approval, effect_port=FakeEffectPort(), now=NOW)
        draft = build_operation_plan(provider_id="fake.provider", operation_id="sync-incremental", binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root), executable=str(self.root / "provider.exe"), mutation_targets=(self.target,), execution_nonce="nonce-b", attempt_ref="attempt-b", adapter_render_hash=H)
        test_approval = issue_approval(build_operation_plan_subject(draft.document), confirmation_source="test-fixture", scope="test", target_hashes=(H,), issued_at=NOW, expires_at=NOW.replace(hour=23), nonce="nonce-b")
        final = build_operation_plan(provider_id="fake.provider", operation_id="sync-incremental", binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root), executable=str(self.root / "provider.exe"), mutation_targets=(self.target,), execution_nonce="nonce-b", attempt_ref="attempt-b", adapter_render_hash=H, approval=test_approval)
        class ProductionPort(FakeEffectPort): is_test_port = False
        with self.assertRaisesRegex(RunnerError, "test-approval-rejected"):
            run_operation(final, approval=test_approval, effect_port=ProductionPort(), now=NOW)

    def test_env_and_cwd_injection_are_rejected_before_effect(self):
        with self.assertRaisesRegex(PlanError, "env-injection"):
            build_operation_plan(provider_id="fake.provider", operation_id="inspect", binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root), executable=str(self.root / "provider.exe"), env={"BAD": "x;evil"}, env_allowlist=("BAD",), mutation_targets=(self.target,), execution_nonce="nonce-a", attempt_ref="attempt-a", adapter_render_hash=H)

    def test_local_write_query_requires_machine_authorization_and_drift_fails(self):
        kwargs = dict(provider_id="fake.provider", operation_id="inspect", binding_snapshot_hash=H, plan_hash=H, adapter_hash=H, typed_input_schema_ref="query.input", typed_input={"q": "x"}, adapter_render_hash=H, project_root=str(self.root), project_state_receipt_hash=H, workspace_fingerprint_hash=H, query_byte_budget=1000, call_limit=1, timeout_seconds=1, mutation_targets=(H,), execution_nonce="nonce-q", attempt_ref="attempt-q")
        with self.assertRaisesRegex(PlanError, "machine-project-authorization-required"):
            build_query_plan(**kwargs, side_effects="local-write")
        plan = build_query_plan(**kwargs, side_effects="none")
        approval = issue_approval(build_query_plan_subject(plan.document), confirmation_source="user-confirmation", scope="query", target_hashes=(H,), issued_at=NOW, expires_at=NOW.replace(hour=23), nonce="nonce-q", attempt_ref="attempt-q")
        plan = build_query_plan(**kwargs, side_effects="none", approval=approval)
        obs = WorkspaceObservation(H, {"fingerprintHash": H}, ("Source/a.cpp",))
        with self.assertRaisesRegex(RunnerError, "workspace-drift-during-query"):
            run_query(plan, approval=approval, effect_port=FakeEffectPort(), observer=Observer([obs, WorkspaceObservation(content_hash("other"), {"fingerprintHash": content_hash("other")}, ("Source/a.cpp",))]), argv=("provider",), env={}, cwd=str(self.root), now=NOW, returned_files=[], index_revision="1", index_completeness="complete", actual_side_effects="none", test_mode=True)


if __name__ == "__main__": unittest.main()
