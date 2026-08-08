import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from selfworkflow.v3.hashing import content_hash, project_root_hash
from selfworkflow.v3.project_state import ProjectStateError, build_project_state_receipt, build_workspace_fingerprint
from selfworkflow.v3.receipts import ReceiptError, build_mutation_evidence, build_operation_receipt, build_query_receipt, validate_mutation_evidence

H = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


class ReceiptValidationTests(unittest.TestCase):
    def setUp(self): self.temp = tempfile.TemporaryDirectory()
    def tearDown(self): self.temp.cleanup()

    def fingerprint(self, *, proven=True):
        return build_workspace_fingerprint(self.temp.name, git_head_tree_hash=H, git_index_hash=H, files=[{"path": "Source/a.cpp", "status": "modified", "content": b"int x;"}, {"path": "README.md", "status": "untracked", "content": b"readme"}], indexing_config_hash=H, ignored_generated_boundary_hash=H, dependency_closure_hash=H if proven else None, dependency_closure_proven=proven)

    def test_dirty_untracked_hashes_and_unknown_relationship_are_explicit(self):
        fingerprint = self.fingerprint(proven=False)
        self.assertNotEqual(fingerprint["files"][0]["contentHash"], H)
        receipt = build_project_state_receipt(provider_id="fake.provider", source_identity_hash=H, project_root=self.temp.name, workspace_fingerprint=fingerprint, index_revision="1", health="ready", source_content_fresh="fresh", relationship_fresh="unknown", captured_at=NOW, valid_until=NOW + timedelta(minutes=1))
        self.assertEqual(receipt["relationshipFresh"], "unknown")
        with self.assertRaisesRegex(ProjectStateError, "relationship-freshness-unproven"):
            build_project_state_receipt(provider_id="fake.provider", source_identity_hash=H, project_root=self.temp.name, workspace_fingerprint=fingerprint, index_revision="1", health="ready", source_content_fresh="fresh", relationship_fresh="fresh", captured_at=NOW, valid_until=NOW + timedelta(minutes=1))

    def test_all_evidence_kinds_are_schema_validated_and_bound(self):
        states = {"identityHash": H, "revision": "1"}
        for kind in ("filesystem-manifest", "managed-state-manifest", "process-state-delta", "service-state-delta"):
            before = [] if kind == "filesystem-manifest" else states
            after = [{"path": "managed/index", "type": "file", "size": 1, "contentHash": H, "reparseIdentityHash": H}] if kind == "filesystem-manifest" else states
            with self.subTest(kind=kind):
                evidence = build_mutation_evidence(subject_kind="operation-plan", subject_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a", provider_binding_hash=H, project_root_hash=project_root_hash(self.temp.name), observed_at=NOW, pre_state_identity=H, post_state_identity=H, mutation_target_hash=H, provider_id="fake.provider", evidence_kind=kind, before=before, after=after, declared_paths=("managed/index",))
                validate_mutation_evidence(evidence, subject_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a", project_root_hash=project_root_hash(self.temp.name), declared_paths=("managed/index",))

    def test_replay_out_of_bounds_duplicate_and_unobservable_are_closed(self):
        with self.assertRaisesRegex(ReceiptError, "mutation-target-out-of-bounds"):
            build_mutation_evidence(subject_kind="operation-plan", subject_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a", provider_binding_hash=H, project_root_hash=H, observed_at=NOW, pre_state_identity=H, post_state_identity=H, mutation_target_hash=H, provider_id="fake.provider", evidence_kind="filesystem-manifest", before=[], after=[{"path": "secret", "type": "file", "size": 1, "contentHash": H, "reparseIdentityHash": H}], declared_paths=("managed/index",))
        with self.assertRaisesRegex(ReceiptError, "required-mutation-unobservable"):
            build_mutation_evidence(subject_kind="operation-plan", subject_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a", provider_binding_hash=H, project_root_hash=H, observed_at=NOW, pre_state_identity=H, post_state_identity=H, mutation_target_hash=H, provider_id="fake.provider", evidence_kind="managed-state-manifest", before={"identityHash": H, "revision": "1"}, after={"identityHash": H, "revision": "2"}, observable=False, required=True)

    def test_receipt_hashes_are_self_consistent(self):
        operation = build_operation_receipt(operation_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a", provider_id="fake.provider", binding_snapshot_hash=H, started_at=NOW, completed_at=NOW, outcome="succeeded", approval_receipt_ref=None, mutation_evidence_refs=())
        self.assertEqual(operation["receiptHash"], content_hash({key: value for key, value in operation.items() if key != "receiptHash"}))
        query = build_query_receipt(query_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a", provider_id="fake.provider", adapter_hash=H, source_identity_hash=H, project_state_receipt_hash=H, workspace_fingerprint_hash=H, index_revision="1", index_completeness="complete", returned_files=[], truncated=False, pre_fingerprint_hash=H, post_fingerprint_hash=H, actual_side_effects="none", mutation_evidence_refs=[])
        self.assertEqual(query["receiptHash"], content_hash({key: value for key, value in query.items() if key != "receiptHash"}))


if __name__ == "__main__": unittest.main()
