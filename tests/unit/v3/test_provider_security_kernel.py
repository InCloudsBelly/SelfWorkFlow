import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.fixtures.providers.fake_provider import FakeEffectPort
from selfworkflow.v3.approvals import (
    build_machine_authorization,
    build_operation_plan_subject,
    issue_approval,
)
from selfworkflow.v3.contracts import (
    ContractError,
    validate_provider_operation_plan,
)
from selfworkflow.v3.effects import EffectMutation
from selfworkflow.v3.hashing import content_hash
from selfworkflow.v3.plans import PlanError, build_operation_plan, build_query_plan
from selfworkflow.v3.project_lease import (
    LeaseError,
    ProviderLeaseManager,
    build_stale_unlock_authorization,
)
from selfworkflow.v3.runner import RunnerError, run_operation


H = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = NOW

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class Process:
    def current(self):
        return 101, "process-start-a"

    def is_live(self, pid, start):
        return pid == 101 and start == "process-start-a"


class Boot:
    def current(self):
        return "boot-a"


class FakeLeaseStore:
    def __init__(self):
        self.values = {}

    def read(self, key):
        value = self.values.get(key)
        return None if value is None else dict(value)

    def create(self, key, document):
        if key in self.values:
            return False
        self.values[key] = dict(document)
        return True

    def replace(self, key, expected_hash, document):
        current = self.values.get(key)
        if current is None or current["leaseHash"] != expected_hash:
            return False
        self.values[key] = dict(document)
        return True

    def delete(self, key, expected_hash):
        current = self.values.get(key)
        if current is None or current["leaseHash"] != expected_hash:
            return False
        del self.values[key]
        return True


class FakeReplayStore:
    def __init__(self):
        self.values = set()

    def consume(self, key):
        if key in self.values:
            return False
        self.values.add(key)
        return True


class ProviderSecurityKernelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = {
            "targetKind": "managed-state-root",
            "targetId": "provider-index",
            "recursion": "bounded",
            "reparsePolicy": "reject",
            "allowedActions": ["sync"],
            "evidenceRequired": True,
        }
        self.store = FakeLeaseStore()
        self.clock = Clock()
        self.manager = ProviderLeaseManager(
            store=self.store,
            clock=self.clock,
            process=Process(),
            boot=Boot(),
            host_identity="host-a",
            user_session="session-a",
            heartbeat_seconds=2,
            ttl_seconds=10,
        )

    def tearDown(self):
        self.temp.cleanup()

    def operation(self):
        kwargs = dict(
            provider_id="fake.provider",
            operation_id="sync-incremental",
            binding_snapshot_hash=H,
            plan_hash=H,
            project_root=str(self.root),
            executable=str(self.root / "provider.exe"),
            env={"LANG": "C"},
            env_allowlist=("LANG",),
            mutation_targets=(self.target,),
            execution_nonce="nonce-a",
            attempt_ref="attempt-a",
            adapter_render_hash=H,
            ownership_domain="selfworkflow-managed",
        )
        draft = build_operation_plan(**kwargs)
        approval = issue_approval(
            build_operation_plan_subject(draft.document),
            confirmation_source="user-confirmation",
            scope="one operation",
            target_hashes=tuple(item["canonicalTargetHash"] for item in draft.document["mutationTargets"]),
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
            nonce="nonce-a",
        )
        return build_operation_plan(**kwargs, approval=approval), approval

    def test_plan_contains_exact_command_and_public_validator_rejects_bad_hash(self):
        plan, _ = self.operation()
        self.assertEqual(plan.document["commandSpec"]["argv"][0], str(self.root / "provider.exe"))
        tampered = dict(plan.document)
        tampered["operationPlanHash"] = H
        with self.assertRaises(ContractError):
            validate_provider_operation_plan(tampered)

    def test_runner_rejects_undeclared_side_effect_and_replay(self):
        plan, approval = self.operation()
        lease = self.manager.acquire(
            project_root=str(self.root), provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        replay = FakeReplayStore()
        port = FakeEffectPort(
            touched_paths=("outside/secret",),
            mutations=(EffectMutation("filesystem", "outside/secret", "modify"),),
        )
        with self.assertRaisesRegex(RunnerError, "undeclared-effect"):
            run_operation(
                plan, approval=approval, effect_port=port, now=NOW,
                lease=lease, lease_manager=self.manager,
                replay_store=replay, test_mode=True,
            )
        with self.assertRaisesRegex(RunnerError, "approval-replay"):
            run_operation(
                plan, approval=approval, effect_port=FakeEffectPort(), now=NOW,
                lease=lease, lease_manager=self.manager,
                replay_store=replay, test_mode=True,
            )

    def test_cross_manager_store_is_mutually_exclusive(self):
        self.manager.acquire(
            project_root=str(self.root), provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        other = ProviderLeaseManager(
            store=self.store, clock=self.clock, process=Process(), boot=Boot(),
            host_identity="host-a", user_session="session-a",
            heartbeat_seconds=2, ttl_seconds=10,
        )
        with self.assertRaisesRegex(LeaseError, "lease-concurrent-owner"):
            other.acquire(
                project_root=str(self.root), provider_id="fake.provider",
                operation_id="sync-incremental", nonce="nonce-b",
            )

    def test_default_identity_fails_closed(self):
        manager = ProviderLeaseManager(store=self.store)
        with self.assertRaisesRegex(LeaseError, "lease-identity-unavailable"):
            manager.acquire(
                project_root=str(self.root), provider_id="fake.provider",
                operation_id="inspect", nonce="nonce-x",
            )

    def test_stale_unlock_requires_typed_authorization(self):
        lease = self.manager.acquire(
            project_root=str(self.root), provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        self.clock.advance(3)
        with self.assertRaisesRegex(LeaseError, "stale-unlock-requires-authorization"):
            self.manager.release(lease)
        authorization = build_stale_unlock_authorization(
            lease, issued_at=self.clock.now(), expires_at=self.clock.now() + timedelta(minutes=1),
            nonce="unlock-a",
        )
        self.manager.release(lease, stale_authorization=authorization)

    def test_bool_machine_authorization_and_user_owned_maintenance_are_rejected(self):
        query_kwargs = dict(
            provider_id="fake.provider", operation_id="inspect",
            binding_snapshot_hash=H, plan_hash=H, adapter_hash=H,
            typed_input_schema_ref="query.input", typed_input={"q": "x"},
            adapter_render_hash=H, project_root=str(self.root),
            project_state_receipt_hash=H, workspace_fingerprint_hash=H,
            query_byte_budget=1000, call_limit=1, timeout_seconds=1,
            side_effects="local-write", mutation_targets=(self.target,),
            execution_nonce="nonce-q", attempt_ref="attempt-q",
            executable=str(self.root / "provider.exe"), arguments=("query",),
        )
        with self.assertRaises((TypeError, PlanError)):
            build_query_plan(**query_kwargs, machine_authorized=True)
        authorization = build_machine_authorization(
            provider_id="fake.provider", project_root=str(self.root),
            subject_kind="query-plan", operation_id="inspect",
            side_effect_class="local-write", execution_nonce="nonce-q",
            attempt_ref="attempt-q", issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5), nonce="machine-a",
        )
        build_query_plan(**query_kwargs, machine_authorization=authorization, now=NOW)
        with self.assertRaisesRegex(PlanError, "user-owned-source-protected"):
            build_operation_plan(
                provider_id="fake.provider", operation_id="upgrade-managed-adapter",
                binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root),
                executable=str(self.root / "provider.exe"), mutation_targets=(self.target,),
                execution_nonce="nonce-u", attempt_ref="attempt-u",
                adapter_render_hash=H, ownership_domain="user-owned",
            )


if __name__ == "__main__":
    unittest.main()
