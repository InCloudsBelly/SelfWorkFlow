import tempfile
import unittest
from datetime import datetime, timezone

from selfworkflow.v3.hashing import project_root_hash
from selfworkflow.v3.receipts import ReceiptError, build_mutation_evidence, validate_mutation_evidence

H = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


class MutationEvidenceTests(unittest.TestCase):
    def setUp(self): self.temp = tempfile.TemporaryDirectory()
    def tearDown(self): self.temp.cleanup()

    def _filesystem(self, *, path="managed/index", nonce="nonce-a", attempt="attempt-a"):
        return build_mutation_evidence(subject_kind="operation-plan", subject_plan_hash=H, execution_nonce=nonce, attempt_ref=attempt, provider_binding_hash=H, project_root_hash=project_root_hash(self.temp.name), observed_at=NOW, pre_state_identity=H, post_state_identity=H, mutation_target_hash=H, provider_id="fake.provider", evidence_kind="filesystem-manifest", before=[], after=[{"path": path, "type": "file", "size": 1, "contentHash": H, "reparseIdentityHash": H}], declared_paths=("managed/index",))

    def test_actual_mutation_must_be_declared_subset(self):
        with self.assertRaisesRegex(ReceiptError, "mutation-target-out-of-bounds"):
            self._filesystem(path="outside/secret")

    def test_cross_nonce_attempt_and_project_replay_are_rejected(self):
        evidence = self._filesystem()
        with self.assertRaisesRegex(ReceiptError, "mutation-evidence-replay"):
            validate_mutation_evidence(evidence, subject_plan_hash=H, execution_nonce="nonce-b", attempt_ref="attempt-a", project_root_hash=project_root_hash(self.temp.name), declared_paths=("managed/index",))
        with self.assertRaisesRegex(ReceiptError, "mutation-evidence-replay"):
            validate_mutation_evidence(evidence, subject_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-b", project_root_hash=project_root_hash(self.temp.name), declared_paths=("managed/index",))
        other = tempfile.TemporaryDirectory()
        try:
            with self.assertRaisesRegex(ReceiptError, "mutation-evidence-project-mismatch"):
                validate_mutation_evidence(evidence, subject_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a", project_root_hash=project_root_hash(other.name), declared_paths=("managed/index",))
        finally: other.cleanup()

    def test_redundant_unobservable_is_unverified_and_required_is_blocked(self):
        kwargs = dict(subject_kind="query-plan", subject_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a", provider_binding_hash=H, project_root_hash=H, observed_at=NOW, pre_state_identity=H, post_state_identity=H, mutation_target_hash=H, provider_id="fake.provider", evidence_kind="managed-state-manifest", before={"identityHash": H, "revision": "1"}, after={"identityHash": H, "revision": "2"}, observable=False)
        with self.assertRaisesRegex(ReceiptError, "redundant-mutation-unverified"):
            build_mutation_evidence(**kwargs, required=False)
        with self.assertRaisesRegex(ReceiptError, "required-mutation-unobservable"):
            build_mutation_evidence(**kwargs, required=True)

    def test_duplicate_manifest_is_rejected(self):
        with self.assertRaisesRegex(ReceiptError, "mutation-evidence-duplicate"):
            build_mutation_evidence(subject_kind="operation-plan", subject_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a", provider_binding_hash=H, project_root_hash=H, observed_at=NOW, pre_state_identity=H, post_state_identity=H, mutation_target_hash=H, provider_id="fake.provider", evidence_kind="filesystem-manifest", before=[], after=[{"path": "managed/index", "type": "file", "size": 1, "contentHash": H, "reparseIdentityHash": H}, {"path": "managed/index", "type": "file", "size": 1, "contentHash": H, "reparseIdentityHash": H}], declared_paths=("managed/index",))


if __name__ == "__main__": unittest.main()
