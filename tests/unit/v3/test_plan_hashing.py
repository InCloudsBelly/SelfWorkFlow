from __future__ import annotations

from datetime import timedelta
import json
import tempfile
import unittest

from selfworkflow.v3.approvals import (
    build_operation_plan_subject,
    build_selection_exception_subject,
    issue_approval,
    validate_approval,
)
from selfworkflow.v3.command_registry import (
    CommandRegistryError,
    build_adapter_command_template,
)
from selfworkflow.v3.contracts import ContractError, load_contract, validate_provider_operation_plan
from selfworkflow.v3.plans import (
    OPERATION_IDS,
    PlanError,
    assert_maintenance_operation,
    build_operation_plan,
    build_query_plan,
)
from tests.fixtures.providers.security_fakes import H, NOW, command_registry, operation_bundle, query_bundle


class PlanHashingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_subject_approval_final_hash_has_no_cycle(self):
        plan, approval, _registry, _machine, _resolver = operation_bundle(self.temp.name)
        self.assertEqual(
            plan.document["operationAuthorizationSubjectHash"],
            build_operation_plan_subject(plan.document).subject_hash,
        )
        self.assertEqual(plan.document["approvalReceiptHash"], approval.receipt_hash)
        validate_approval(
            plan.subject, approval, now=NOW,
            expected_target_hashes=[plan.document["mutationTargets"][0]["mutationTargetHash"]],
            expected_provider_id="fake.provider",
            expected_project_root_hash=plan.document["canonicalProjectRootHash"],
            expected_operation_id="sync-incremental",
            expected_attempt_ref="attempt-a", expected_execution_nonce="nonce-a",
        )

    def test_approval_provider_attempt_nonce_expiry_and_target_are_rederived(self):
        plan, _approval, *_ = operation_bundle(self.temp.name)
        target = plan.document["mutationTargets"][0]["mutationTargetHash"]
        wrong_provider = issue_approval(
            plan.subject, confirmation_source="user-confirmation", scope="exact-plan",
            target_hashes=(target,), issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=1), nonce="nonce-a",
            provider_id="other.provider",
        )
        with self.assertRaisesRegex(Exception, "approval-provider-mismatch"):
            validate_approval(
                plan.subject, wrong_provider, now=NOW,
                expected_target_hashes=(target,), expected_provider_id="fake.provider",
                expected_project_root_hash=plan.document["canonicalProjectRootHash"],
                expected_attempt_ref="attempt-a", expected_operation_id="sync-incremental",
                expected_execution_nonce="nonce-a",
            )
        expired = issue_approval(
            plan.subject, confirmation_source="user-confirmation", scope="exact-plan",
            target_hashes=(target,), issued_at=NOW - timedelta(minutes=2),
            expires_at=NOW - timedelta(minutes=1), nonce="nonce-a",
        )
        with self.assertRaisesRegex(Exception, "approval-expired"):
            validate_approval(
                plan.subject, expired, now=NOW,
                expected_target_hashes=(target,), expected_provider_id="fake.provider",
                expected_project_root_hash=plan.document["canonicalProjectRootHash"],
                expected_attempt_ref="attempt-a", expected_operation_id="sync-incremental",
                expected_execution_nonce="nonce-a",
            )

    def test_query_approval_cannot_authorize_operation_and_selection_is_distinct(self):
        query, query_approval, *_ = query_bundle(self.temp.name)
        operation, *_ = operation_bundle(self.temp.name)
        with self.assertRaisesRegex(Exception, "approval-subject"):
            validate_approval(operation.subject, query_approval, now=NOW)
        selection = build_selection_exception_subject(
            base_request_hash=H, support_matrix_hash=H,
            support_matrix_entry_hash=H, capability_id="code.navigation",
            operation_id="inspect", platform="windows-x64", adapter_hash=H,
            task_scope_hash=H, provider_id="fake.provider",
            execution_nonce="nonce-a", attempt_ref="attempt-a",
        )
        receipt = issue_approval(
            selection, confirmation_source="user-confirmation", scope="exact-plan",
            target_hashes=(), issued_at=NOW, expires_at=NOW + timedelta(minutes=1),
            nonce="nonce-a",
        )
        with self.assertRaisesRegex(Exception, "approval-subject"):
            validate_approval(operation.subject, receipt, now=NOW)

    def test_builder_has_no_raw_command_cwd_or_env_allowlist_escape_hatch(self):
        registry = command_registry(operation_id="inspect", side_effect_class="none")
        common = dict(
            provider_id="fake.provider", operation_id="inspect",
            binding_snapshot_hash=H, adapter_hash=H, plan_hash=H,
            project_root=self.temp.name, command_registry=registry,
            command_template_id="inspect.template", mutation_targets=(),
            execution_nonce="nonce-a", attempt_ref="attempt-a",
            ownership_domain="user-owned",
        )
        for forbidden in (
            {"executable": "C:/evil.exe"}, {"cwd": "C:/"},
            {"env_allowlist": ("PATH",)}, {"arguments": ("--evil",)},
        ):
            with self.subTest(forbidden=next(iter(forbidden))):
                with self.assertRaises(TypeError):
                    build_operation_plan(**common, **forbidden)

    def test_shell_templates_and_dangerous_environment_are_rejected(self):
        with self.assertRaisesRegex(CommandRegistryError, "shell-unsupported"):
            build_adapter_command_template(
                template_id="bad", provider_id="fake.provider",
                binding_snapshot_hash=H, adapter_hash=H, operation_id="inspect",
                side_effect_class="none", executable="C:\\Windows\\System32\\cmd.exe",
                argv_template=("C:\\Windows\\System32\\cmd.exe", "/c", "echo"),
            )
        with self.assertRaisesRegex(CommandRegistryError, "env-unsafe"):
            command_registry(
                operation_id="inspect", side_effect_class="none",
                env_allowlist=("PATH",),
            )

    def test_network_delete_and_user_owned_write_are_unsupported(self):
        self.assertNotIn("remove", OPERATION_IDS)
        with self.assertRaisesRegex(PlanError, "operation-not-allowed"):
            assert_maintenance_operation("remove", ownership_domain="selfworkflow-managed")
        with self.assertRaisesRegex(PlanError, "network-unsupported"):
            build_query_plan(
                provider_id="fake.provider", operation_id="inspect",
                binding_snapshot_hash=H, plan_hash=H, adapter_hash=H,
                typed_input_schema_ref="query.input", typed_input={},
                project_root=self.temp.name, project_state_receipt_hash=H,
                workspace_fingerprint_hash=H, query_byte_budget=1, call_limit=1,
                timeout_seconds=1, side_effects="network", mutation_targets=(),
                execution_nonce="nonce-a", attempt_ref="attempt-a",
                command_registry=command_registry(operation_id="inspect", side_effect_class="none"),
                command_template_id="inspect.template",
            )
        with self.assertRaisesRegex(PlanError, "action-invalid"):
            operation_bundle(self.temp.name, action="delete")
        with self.assertRaisesRegex(PlanError, "user-owned-source-protected"):
            operation_bundle(self.temp.name, ownership_domain="user-owned")

    def test_serialized_plan_recomputes_all_hashes_and_cross_fields(self):
        plan, *_ = operation_bundle(self.temp.name)
        load_contract("provider-operation-plan.schema.json", json.dumps(plan.document))
        for mutation in (
            lambda d: d.update(operationPlanHash=H),
            lambda d: d["commandSpec"].update(cwd=self.temp.name + "-other"),
            lambda d: d["mutationTargets"][0].update(mutationTargetHash=H),
            lambda d: d["commandSpec"].update(adapterHash=H.replace("a", "b", 1)),
        ):
            tampered = json.loads(json.dumps(plan.document))
            mutation(tampered)
            with self.subTest(tampered=tampered):
                with self.assertRaises(ContractError):
                    validate_provider_operation_plan(tampered)


if __name__ == "__main__":
    unittest.main()
