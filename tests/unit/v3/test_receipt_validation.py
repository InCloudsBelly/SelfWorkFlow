from __future__ import annotations

from datetime import timedelta
import tempfile
import unittest

from selfworkflow.v3.approvals import build_machine_authorization
from selfworkflow.v3.contracts import (
    ContractError,
    validate_provider_machine_authorization,
    validate_provider_operation_receipt,
)
from selfworkflow.v3.hashing import content_hash
from selfworkflow.v3.project_state import build_project_state_receipt, build_workspace_fingerprint
from selfworkflow.v3.receipts import build_operation_receipt
from tests.fixtures.providers.security_fakes import H, NOW, evidence_for, operation_bundle


class ReceiptValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_dirty_untracked_hashes_and_unknown_relationship_are_explicit(self):
        fingerprint = build_workspace_fingerprint(
            self.temp.name, git_head_tree_hash=H, git_index_hash=H,
            files=(
                {"path": "src/a.cpp", "status": "modified", "content": b"a"},
                {"path": "src/new.cpp", "status": "untracked", "content": b"b"},
            ),
            indexing_config_hash=H, ignored_generated_boundary_hash=H,
            dependency_closure_hash=None, dependency_closure_proven=False,
        )
        receipt = build_project_state_receipt(
            provider_id="fake.provider", source_identity_hash=H,
            project_root=self.temp.name, workspace_fingerprint=fingerprint,
            health="ready", source_content_fresh="fresh",
            relationship_fresh="unknown", captured_at=NOW,
            valid_until=NOW + timedelta(minutes=1), index_revision="r1",
        )
        self.assertEqual(receipt["relationshipFresh"], "unknown")
        self.assertEqual(len(fingerprint["files"]), 2)

    def test_public_receipt_requires_resolver_and_exact_evidence_set(self):
        plan, approval, *_ = operation_bundle(self.temp.name)
        evidence = evidence_for(plan)
        reference = "evidence-" + evidence["evidenceHash"][7:]
        receipt = build_operation_receipt(
            operation_plan_hash=plan.operation_plan_hash,
            execution_nonce="nonce-a", attempt_ref="attempt-a",
            provider_id="fake.provider", binding_snapshot_hash=H,
            canonical_project_root_hash=plan.document["canonicalProjectRootHash"],
            started_at=NOW, completed_at=NOW, outcome="succeeded",
            replay_state="terminal-succeeded",
            approval_receipt_ref=approval.receipt_hash,
            mutation_evidence_refs=(reference,),
        )
        with self.assertRaisesRegex(ContractError, "evidence-resolver-required"):
            validate_provider_operation_receipt(receipt, plan.document)
        validate_provider_operation_receipt(
            receipt, plan.document,
            lambda ref: evidence if ref == reference else None,
        )
        missing = dict(receipt)
        missing["mutationEvidenceRefs"] = []
        missing["receiptHash"] = content_hash({
            key: value for key, value in missing.items() if key != "receiptHash"
        })
        with self.assertRaisesRegex(ContractError, "cardinality"):
            validate_provider_operation_receipt(missing, plan.document, lambda _ref: None)

    def test_cross_target_rehash_cannot_satisfy_required_evidence(self):
        plan, approval, *_ = operation_bundle(self.temp.name)
        evidence = evidence_for(plan)
        evidence["mutationTargetHash"] = H
        evidence["evidenceHash"] = content_hash({
            key: value for key, value in evidence.items() if key != "evidenceHash"
        })
        reference = "evidence-" + evidence["evidenceHash"][7:]
        receipt = build_operation_receipt(
            operation_plan_hash=plan.operation_plan_hash,
            execution_nonce="nonce-a", attempt_ref="attempt-a",
            provider_id="fake.provider", binding_snapshot_hash=H,
            canonical_project_root_hash=plan.document["canonicalProjectRootHash"],
            started_at=NOW, completed_at=NOW, outcome="succeeded",
            replay_state="terminal-succeeded",
            approval_receipt_ref=approval.receipt_hash,
            mutation_evidence_refs=(reference,),
        )
        with self.assertRaisesRegex(ContractError, "evidence-target-mismatch"):
            validate_provider_operation_receipt(
                receipt, plan.document, lambda _ref: evidence,
            )

    def test_bad_receipt_hash_replay_state_and_test_issuer_are_rejected(self):
        plan, approval, *_ = operation_bundle(self.temp.name)
        evidence = evidence_for(plan)
        reference = "evidence-" + evidence["evidenceHash"][7:]
        receipt = build_operation_receipt(
            operation_plan_hash=plan.operation_plan_hash,
            execution_nonce="nonce-a", attempt_ref="attempt-a",
            provider_id="fake.provider", binding_snapshot_hash=H,
            canonical_project_root_hash=plan.document["canonicalProjectRootHash"],
            started_at=NOW, completed_at=NOW, outcome="succeeded",
            replay_state="terminal-succeeded", approval_receipt_ref=approval.receipt_hash,
            mutation_evidence_refs=(reference,),
        )
        receipt["receiptHash"] = H
        with self.assertRaises(ContractError):
            validate_provider_operation_receipt(receipt)
        machine = build_machine_authorization(
            provider_id="fake.provider", project_root=self.temp.name,
            subject_kind="operation-plan", operation_id="sync-incremental",
            side_effect_class="local-write", execution_nonce="nonce-a",
            attempt_ref="attempt-a", issued_at=NOW,
            expires_at=NOW + timedelta(minutes=1), nonce="machine-a",
            confirmation_source="test-fixture", issuer_id="test-fixture",
            test_mode=True,
        )
        with self.assertRaisesRegex(ContractError, "test-authorization-rejected"):
            validate_provider_machine_authorization(machine.document)
        revoked = dict(machine.document)
        revoked["issuerId"] = "host-authority"
        revoked["confirmationSource"] = "machine-policy"
        revoked["revocationState"] = "revoked"
        revoked["authorizationHash"] = content_hash({
            key: value for key, value in revoked.items() if key != "authorizationHash"
        })
        with self.assertRaisesRegex(ContractError, "not-active"):
            validate_provider_machine_authorization(revoked)


if __name__ == "__main__":
    unittest.main()
