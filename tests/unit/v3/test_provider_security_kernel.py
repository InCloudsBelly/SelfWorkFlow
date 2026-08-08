from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import tempfile
import unittest

from selfworkflow.v3.approvals import build_machine_authorization
from selfworkflow.v3.command_registry import (
    CommandRegistryError,
    validate_rendered_command,
)
from selfworkflow.v3.contracts import ContractError, load_contract, validate_provider_operation_plan
from selfworkflow.v3.effects import EffectMutation
from selfworkflow.v3.hashing import content_hash
from selfworkflow.v3.plans import PlanError, build_query_plan
from selfworkflow.v3.runner import RunnerError, run_operation
from tests.fixtures.providers.fake_provider import FakeEffectPort
from tests.fixtures.providers.security_fakes import (
    FakeReplayStore,
    H,
    NOW,
    command_registry,
    evidence_for,
    lease_manager,
    operation_bundle,
)


class ProviderSecurityKernelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_command_spec_cannot_substitute_executable_cwd_env_or_registry(self):
        plan, _approval, registry, *_ = operation_bundle(self.temp.name)
        validate_rendered_command(plan.document["commandSpec"], registry, production=False)
        mutations = (
            ("argv", ["C:\\evil.exe", *plan.document["commandSpec"]["argv"][1:]]),
            ("cwd", "C:\\"),
            ("env", {"PATH": "C:\\evil"}),
            ("registryHash", H),
        )
        for key, value in mutations:
            command = dict(plan.document["commandSpec"])
            command[key] = value
            command["commandSpecHash"] = content_hash({
                name: item for name, item in command.items() if name != "commandSpecHash"
            })
            with self.subTest(key=key):
                with self.assertRaises(CommandRegistryError):
                    validate_rendered_command(command, registry, production=False)

    def test_public_plan_rejects_cross_field_rehash(self):
        plan, *_ = operation_bundle(self.temp.name)
        document = json.loads(json.dumps(plan.document))
        document["commandSpec"]["operationId"] = "rebuild-index"
        document["commandSpec"]["commandSpecHash"] = content_hash({
            key: value for key, value in document["commandSpec"].items()
            if key != "commandSpecHash"
        })
        document["operationPlanHash"] = content_hash({
            key: value for key, value in document.items() if key != "operationPlanHash"
        })
        with self.assertRaisesRegex(ContractError, "command-plan-mismatch"):
            validate_provider_operation_plan(document)

    def test_replay_reserve_is_concurrently_exclusive(self):
        store = FakeReplayStore()
        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(lambda _i: store.reserve("same-key"), range(32)))
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(outcomes.count(False), 31)

    def test_effect_returned_failure_is_terminal_not_retryable(self):
        plan, approval, registry, _machine, resolver = operation_bundle(self.temp.name)
        manager = lease_manager()
        lease = manager.acquire(
            project_root=self.temp.name, provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        replay = FakeReplayStore()
        receipt, _ = run_operation(
            plan, approval=approval,
            effect_port=FakeEffectPort(
                exit_code=7,
                mutations=(EffectMutation("managed-state", "index", "sync"),),
                mutation_evidence=(evidence_for(plan),),
            ),
            now=NOW, trusted_command_registry=registry,
            authorization_resolver=resolver, lease=lease,
            lease_manager=manager, replay_store=replay, test_mode=True,
        )
        self.assertEqual(receipt["outcome"], "failed")
        self.assertEqual(receipt["replayState"], "terminal-failed")
        with self.assertRaisesRegex(RunnerError, "lease-not-current|approval-replay"):
            run_operation(
                plan, approval=approval, effect_port=FakeEffectPort(), now=NOW,
                trusted_command_registry=registry, authorization_resolver=resolver,
                lease=lease, lease_manager=manager, replay_store=replay,
                test_mode=True,
            )

    def test_effect_port_that_skips_live_guard_is_terminal_failed(self):
        plan, approval, registry, _machine, resolver = operation_bundle(self.temp.name)
        manager = lease_manager()
        lease = manager.acquire(
            project_root=self.temp.name, provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        replay = FakeReplayStore()
        with self.assertRaises(RunnerError) as raised:
            run_operation(
                plan, approval=approval,
                effect_port=FakeEffectPort(
                    mutation_evidence=(evidence_for(plan),), invoke_live_guard=False,
                ),
                now=NOW, trusted_command_registry=registry,
                authorization_resolver=resolver, lease=lease,
                lease_manager=manager, replay_store=replay, test_mode=True,
            )
        self.assertEqual(raised.exception.reason, "effect-live-lease-guard-not-used")
        self.assertEqual(raised.exception.replay_state, "terminal-failed")

    def test_boolean_authorization_user_owned_mutation_delete_and_network_cannot_bypass(self):
        registry = command_registry(operation_id="sync-incremental", side_effect_class="local-write")
        common = dict(
            provider_id="fake.provider", operation_id="sync-incremental",
            binding_snapshot_hash=H, plan_hash=H, adapter_hash=H,
            typed_input_schema_ref="query.input", typed_input={},
            project_root=self.temp.name, project_state_receipt_hash=H,
            workspace_fingerprint_hash=H, query_byte_budget=1, call_limit=1,
            timeout_seconds=1, mutation_targets=({
                "targetKind": "managed-state-root", "targetId": "index",
                "allowedActions": ["sync"], "evidenceRequired": True,
            },), execution_nonce="nonce-a", attempt_ref="attempt-a",
            command_registry=registry,
            command_template_id="sync-incremental.template", now=NOW,
        )
        with self.assertRaisesRegex(PlanError, "user-owned-source-protected"):
            build_query_plan(
                **common, side_effects="local-write",
                ownership_domain="user-owned", machine_authorization=True,
            )
        with self.assertRaisesRegex(PlanError, "network-unsupported"):
            build_query_plan(
                **common, side_effects="network",
                ownership_domain="selfworkflow-managed", machine_authorization=True,
            )

    def test_test_fixture_registry_cannot_be_loaded_as_production_contract(self):
        registry = command_registry(operation_id="inspect", side_effect_class="none")
        with self.assertRaisesRegex(ContractError, "test-command-registry-rejected"):
            load_contract("trusted-command-registry.schema.json", json.dumps(registry.document))

    def test_public_registry_validator_recomputes_registry_and_template_hashes(self):
        registry = command_registry(
            operation_id="inspect", side_effect_class="none",
            trust_source="host-attested",
        )
        load_contract("trusted-command-registry.schema.json", json.dumps(registry.document))
        document = registry.document
        document["templates"][0]["operationId"] = "other"
        document["registryHash"] = content_hash({
            key: value for key, value in document.items() if key != "registryHash"
        })
        with self.assertRaisesRegex(ContractError, "template-hash-invalid"):
            load_contract("trusted-command-registry.schema.json", json.dumps(document))


if __name__ == "__main__":
    unittest.main()
