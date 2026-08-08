import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from selfworkflow.v3.approvals import (
    ApprovalError, build_operation_plan_subject, build_query_plan_subject,
    build_selection_exception_subject, issue_approval, validate_approval,
)
from selfworkflow.v3.hashing import content_hash, project_root_hash
from selfworkflow.v3.contracts import (
    ContractError, validate_provider_approval_receipt, validate_provider_query_plan,
)
from selfworkflow.v3.plans import build_operation_plan, build_query_plan


H = "sha256:" + "a" * 64
ROOT_H = "sha256:" + "b" * 64
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


class PlanHashingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = {"targetKind": "managed-state-root", "targetId": "provider-index", "recursion": "bounded", "reparsePolicy": "reject", "allowedActions": ["sync"], "evidenceRequired": True}

    def tearDown(self):
        self.temp.cleanup()

    def _plan(self, approval=None):
        return build_operation_plan(
            provider_id="fake.provider", operation_id="sync-incremental", binding_snapshot_hash=H,
            plan_hash=H, project_root=str(self.root), executable=str(self.root / "fake-provider.exe"),
            env={"LANG": "C"}, env_allowlist=("LANG",), mutation_targets=(self.target,),
            execution_nonce="nonce-a", attempt_ref="attempt-a", adapter_render_hash=H,
            ownership_domain="selfworkflow-managed", approval=approval,
        )

    def test_subject_approval_final_hash_has_no_cycle(self):
        draft = self._plan()
        subject = build_operation_plan_subject(draft.document)
        approval = issue_approval(subject, confirmation_source="user-confirmation", scope="one operation", target_hashes=tuple(item["canonicalTargetHash"] for item in draft.document["mutationTargets"]), issued_at=NOW, expires_at=NOW + timedelta(minutes=5), nonce="nonce-a", provider_id="fake.provider", canonical_project_root_hash=project_root_hash(self.root), operation_id="sync-incremental", attempt_ref="attempt-a")
        final = self._plan(approval)
        self.assertEqual(final.document["operationAuthorizationSubjectHash"], subject.subject_hash)
        self.assertEqual(final.document["approvalReceiptHash"], approval.receipt_hash)
        self.assertEqual(final.document["operationPlanHash"], content_hash({key: value for key, value in final.document.items() if key != "operationPlanHash"}))

    def test_query_approval_cannot_authorize_operation(self):
        query_like = dict(self._plan().document)
        query_like["sideEffects"] = "none"
        subject = build_query_plan_subject({**query_like, "operationId": "inspect"})
        receipt = issue_approval(subject, confirmation_source="user-confirmation", scope="query", target_hashes=(), issued_at=NOW, expires_at=NOW + timedelta(minutes=5), nonce="nonce-a")
        with self.assertRaises(ApprovalError) as error:
            validate_approval(build_operation_plan_subject(self._plan().document), receipt, now=NOW)
        self.assertEqual(error.exception.reason, "approval-subject-kind-mismatch")

    def test_selection_exception_is_a_distinct_subject(self):
        subject = build_selection_exception_subject(base_request_hash=H, support_matrix_hash=H, support_matrix_entry_hash=H, capability_id="code.context", operation_id="inspect", platform="windows", adapter_hash=H, task_scope_hash=H, provider_id="fake.provider", execution_nonce="nonce-a", attempt_ref="attempt-a")
        receipt = issue_approval(subject, confirmation_source="user-confirmation", scope="exception", target_hashes=(), issued_at=NOW, expires_at=NOW + timedelta(minutes=5), nonce="nonce-a")
        with self.assertRaises(ApprovalError) as error:
            validate_approval(build_operation_plan_subject(self._plan().document), receipt, now=NOW)
        self.assertEqual(error.exception.reason, "approval-subject-kind-mismatch")

    def test_expiry_target_project_and_attempt_replay_are_rejected(self):
        plan = self._plan()
        subject = build_operation_plan_subject(plan.document)
        approval = issue_approval(subject, confirmation_source="user-confirmation", scope="one", target_hashes=tuple(item["canonicalTargetHash"] for item in plan.document["mutationTargets"]), issued_at=NOW, expires_at=NOW + timedelta(minutes=1), nonce="nonce-a", provider_id="fake.provider", canonical_project_root_hash=project_root_hash(self.root), operation_id="sync-incremental", attempt_ref="attempt-a")
        with self.assertRaisesRegex(ApprovalError, "approval-expired"):
            validate_approval(subject, approval, now=NOW + timedelta(minutes=2))
        with self.assertRaisesRegex(ApprovalError, "approval-target-drift"):
            validate_approval(subject, approval, now=NOW, expected_target_hashes=(ROOT_H,))
        with self.assertRaisesRegex(ApprovalError, "approval-attempt-mismatch"):
            validate_approval(subject, approval, now=NOW, expected_target_hashes=tuple(item["canonicalTargetHash"] for item in plan.document["mutationTargets"]), expected_attempt_ref="attempt-b")

    def test_invalid_command_and_operation_are_rejected(self):
        with self.assertRaisesRegex(Exception, "argv-template-injection"):
            build_operation_plan(provider_id="fake.provider", operation_id="inspect", binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root), executable="C:/fake;evil.exe", mutation_targets=(self.target,), execution_nonce="nonce-a", attempt_ref="attempt-a", adapter_render_hash=H, ownership_domain="selfworkflow-managed")
        with self.assertRaisesRegex(Exception, "operation-not-allowed"):
            build_operation_plan(provider_id="fake.provider", operation_id="remove", binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root), executable=str(self.root / "fake.exe"), mutation_targets=(self.target,), execution_nonce="nonce-a", attempt_ref="attempt-a", adapter_render_hash=H, ownership_domain="selfworkflow-managed")

    def test_wrong_provider_approval_and_outside_cwd_are_rejected(self):
        draft = self._plan()
        approval = issue_approval(
            build_operation_plan_subject(draft.document),
            confirmation_source="user-confirmation", scope="one",
            target_hashes=tuple(item["canonicalTargetHash"] for item in draft.document["mutationTargets"]),
            issued_at=NOW, expires_at=NOW + timedelta(minutes=1), nonce="nonce-a",
            provider_id="other.provider",
        )
        with self.assertRaises(Exception):
            self._plan(approval)
        outside = tempfile.TemporaryDirectory()
        try:
            with self.assertRaisesRegex(Exception, "command-cwd-outside-project"):
                build_operation_plan(
                    provider_id="fake.provider", operation_id="inspect",
                    binding_snapshot_hash=H, plan_hash=H, project_root=str(self.root),
                    cwd=outside.name, executable=str(self.root / "fake.exe"),
                    mutation_targets=(self.target,), execution_nonce="nonce-a",
                    attempt_ref="attempt-a", adapter_render_hash=H,
                    ownership_domain="selfworkflow-managed",
                )
        finally:
            outside.cleanup()

    def test_serialized_query_and_approval_hashes_are_recomputed(self):
        query = build_query_plan(
            provider_id="fake.provider", operation_id="inspect",
            binding_snapshot_hash=H, plan_hash=H, adapter_hash=H,
            typed_input_schema_ref="query.input", typed_input={"q": "x"},
            adapter_render_hash=H, project_root=str(self.root),
            project_state_receipt_hash=H, workspace_fingerprint_hash=H,
            query_byte_budget=100, call_limit=1, timeout_seconds=1,
            side_effects="none", mutation_targets=(), execution_nonce="nonce-q",
            attempt_ref="attempt-q", executable=str(self.root / "fake.exe"),
            arguments=("query",),
        )
        changed = dict(query.document)
        changed["queryPlanHash"] = H
        with self.assertRaises(ContractError):
            validate_provider_query_plan(changed)
        subject = build_query_plan_subject(query.document)
        approval = issue_approval(
            subject, confirmation_source="user-confirmation", scope="query",
            target_hashes=(), issued_at=NOW, expires_at=NOW + timedelta(minutes=1),
            nonce="nonce-q",
        )
        approval.document["receiptHash"] = H
        with self.assertRaises(ContractError):
            validate_provider_approval_receipt(approval.document)


if __name__ == "__main__":
    unittest.main()
