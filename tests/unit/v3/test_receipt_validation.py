import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from selfworkflow.v3.contracts import (
    ContractError,
    validate_provider_operation_receipt,
    validate_provider_project_state_receipt,
    validate_provider_query_receipt,
    validate_workspace_fingerprint,
)
from selfworkflow.v3.hashing import content_hash, project_root_hash
from selfworkflow.v3.project_state import ProjectStateError, build_project_state_receipt, build_workspace_fingerprint
from selfworkflow.v3.receipts import build_operation_receipt, build_query_receipt


H = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


class ReceiptValidationTests(unittest.TestCase):
    def setUp(self): self.temp = tempfile.TemporaryDirectory()
    def tearDown(self): self.temp.cleanup()

    def fingerprint(self, *, proven=True):
        return build_workspace_fingerprint(
            self.temp.name, git_head_tree_hash=H, git_index_hash=H,
            files=[
                {"path": "Source/a.cpp", "status": "modified", "content": b"int x;"},
                {"path": "README.md", "status": "untracked", "content": b"readme"},
            ],
            indexing_config_hash=H, ignored_generated_boundary_hash=H,
            dependency_closure_hash=H if proven else None,
            dependency_closure_proven=proven,
        )

    def test_dirty_untracked_hashes_and_unknown_relationship_are_explicit(self):
        fingerprint = self.fingerprint(proven=False)
        self.assertNotEqual(fingerprint["files"][0]["contentHash"], H)
        receipt = build_project_state_receipt(
            provider_id="fake.provider", source_identity_hash=H,
            project_root=self.temp.name, workspace_fingerprint=fingerprint,
            index_revision="1", health="ready", source_content_fresh="fresh",
            relationship_fresh="unknown", captured_at=NOW,
            valid_until=NOW + timedelta(minutes=1),
        )
        self.assertEqual(receipt["relationshipFresh"], "unknown")
        with self.assertRaisesRegex(ProjectStateError, "relationship-freshness-unproven"):
            build_project_state_receipt(
                provider_id="fake.provider", source_identity_hash=H,
                project_root=self.temp.name, workspace_fingerprint=fingerprint,
                index_revision="1", health="ready", source_content_fresh="fresh",
                relationship_fresh="fresh", captured_at=NOW,
                valid_until=NOW + timedelta(minutes=1),
            )

    def test_public_serialized_hash_validators_reject_tampering(self):
        fingerprint = self.fingerprint()
        state = build_project_state_receipt(
            provider_id="fake.provider", source_identity_hash=H,
            project_root=self.temp.name, workspace_fingerprint=fingerprint,
            index_revision="1", health="ready", source_content_fresh="fresh",
            relationship_fresh="fresh", captured_at=NOW,
            valid_until=NOW + timedelta(minutes=1),
        )
        operation = build_operation_receipt(
            operation_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a",
            provider_id="fake.provider", binding_snapshot_hash=H,
            canonical_project_root_hash=project_root_hash(self.temp.name),
            started_at=NOW, completed_at=NOW, outcome="succeeded",
            approval_receipt_ref=None, mutation_evidence_refs=(),
        )
        query = build_query_receipt(
            query_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a",
            provider_id="fake.provider", adapter_hash=H, source_identity_hash=H,
            project_state_receipt_hash=H, workspace_fingerprint_hash=H,
            canonical_project_root_hash=project_root_hash(self.temp.name),
            started_at=NOW, completed_at=NOW,
            index_revision="1", index_completeness="complete", returned_files=[],
            truncated=False, pre_fingerprint_hash=H, post_fingerprint_hash=H,
            actual_side_effects="none", mutation_evidence_refs=[],
        )
        cases = (
            (fingerprint, "fingerprintHash", validate_workspace_fingerprint),
            (state, "receiptHash", validate_provider_project_state_receipt),
            (operation, "receiptHash", validate_provider_operation_receipt),
            (query, "receiptHash", validate_provider_query_receipt),
        )
        for document, field, validator in cases:
            with self.subTest(field=field, validator=validator.__name__):
                tampered = dict(document)
                tampered[field] = H if document[field] != H else content_hash("bad")
                with self.assertRaises(ContractError):
                    validator(tampered)


if __name__ == "__main__": unittest.main()
