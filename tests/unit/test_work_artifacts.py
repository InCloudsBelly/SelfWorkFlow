import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from jsonschema import Draft202012Validator

from selfworkflow.work_artifacts import (
    WorkArtifactError,
    WorkArtifactManager,
    canonical_document_package_hash,
    canonical_content_generation_hash,
    canonical_publication_receipt_hash,
    WDLC_LIMITS_V1,
)


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _git_repo(root):
    _git(root, "init", "-q")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "-c", "user.name=Tests", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "base")


def _doc(doc_id="design", content="# Design\n"):
    return {"id": doc_id, "kind": doc_id, "content": content}


class WorkArtifactUnitTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_hash_vectors_are_stable(self):
        artifact = [{"id": "design", "kind": "design", "contentHash": "sha256:bbb"}]
        self.assertEqual(
            canonical_document_package_hash(artifact),
            "sha256:644777b6c103be30c4291378343562373bde82452675fd4e9e0c8a2e244e7a3a",
        )
        self.assertEqual(
            canonical_content_generation_hash(artifact, 1),
            "sha256:4cbbe1bdef78683d4ca322f2827f6d9be148d02427137608b35a273efb64cc95",
        )
        self.assertEqual(
            canonical_publication_receipt_hash({
                "schemaVersion": 1,
                "backend": "selfopenwiki",
                "receiptId": "r1",
                "decision": "published",
                "subjectManifestHash": "sha256:mmm",
                "subjectPackageHash": "sha256:ppp",
                "subjectContentGenerationHash": "sha256:ggg",
                "publishedContentHash": "sha256:ccc",
                "publishedAt": "2026-01-01T00:00:00Z",
            }),
            "sha256:9b643df609f8f0c711c58c764e19fc8e6d14628a052b51a85cf16a41556e5555",
        )

    def test_capture_review_post_review_verify_and_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git_repo(root)
            manager = WorkArtifactManager(root, "task/design")
            captured = manager.transition(
                expected_content_generation=0,
                expected_state_revision=0,
                expected_manifest_hash=None,
                event="documents-captured",
                artifacts=[_doc(), {"id": "plan", "kind": "implementation-plan", "content": "# Plan\n"}],
                operation_nonce="capture-1",
            )
            reviewed = manager.transition(
                expected_content_generation=1,
                expected_state_revision=1,
                expected_manifest_hash=captured["manifestHash"],
                event="review-recorded",
                review={"receiptId": "review-1", "packageHash": captured["packageHash"], "findings": [], "independent": True},
                operation_nonce="review-1",
            )
            post = manager.transition(
                expected_content_generation=1,
                expected_state_revision=2,
                expected_manifest_hash=reviewed["manifestHash"],
                event="post-review-recorded",
                review={"receiptId": "post-1", "packageHash": reviewed["packageHash"], "findings": [], "independent": True},
                operation_nonce="post-1",
            )
            verified = manager.transition(
                expected_content_generation=1,
                expected_state_revision=3,
                expected_manifest_hash=post["manifestHash"],
                event="verification-recorded",
                verification={"receiptId": "verify-1", "packageHash": post["packageHash"], "fresh": True, "passed": True},
                operation_nonce="verify-1",
            )
            completed = manager.transition(
                expected_content_generation=1,
                expected_state_revision=4,
                expected_manifest_hash=verified["manifestHash"],
                event="task-completed",
                operation_nonce="complete-1",
            )
            self.assertEqual(completed["taskState"], "completed")
            self.assertEqual(completed["artifactStatus"], "local-final")
            self.assertTrue((root / "selfworkflow" / "tasks").is_dir())
            ignored = subprocess.run(["git", "check-ignore", "-q", "--", "selfworkflow"], cwd=root)
            self.assertEqual(ignored.returncode, 0)

    def test_review_findings_block_verification_and_revision_invalidates_old_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git_repo(root)
            manager = WorkArtifactManager(root, "findings")
            captured = manager.transition(0, 0, None, "documents-captured", [_doc()], operation_nonce="c")
            blocked = manager.transition(
                1, 1, captured["manifestHash"], "review-recorded",
                review={"receiptId": "r", "packageHash": captured["packageHash"], "findings":[{"id":"f1","severity":"Important","status":"open"}], "independent": True},
                operation_nonce="r",
            )
            self.assertEqual(blocked["artifactStatus"], "candidate")
            with self.assertRaisesRegex(WorkArtifactError, "verification-(?:blocked|not-allowed)"):
                manager.transition(1, 2, blocked["manifestHash"], "verification-recorded", verification={"receiptId":"v","packageHash":blocked["packageHash"],"fresh":True,"passed":True}, operation_nonce="v")
            revised = manager.transition(1, 2, blocked["manifestHash"], "documents-revised", [_doc(content="# Revised\n")], operation_nonce="rev")
            self.assertEqual(revised["contentGeneration"], 2)
            with self.assertRaisesRegex(WorkArtifactError, "verification-(?:subject-mismatch|not-allowed)"):
                manager.transition(2, 3, revised["manifestHash"], "verification-recorded", verification={"receiptId":"v2","packageHash":captured["packageHash"],"fresh":True,"passed":True}, operation_nonce="v2")

    def test_cas_and_nonce_replay_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git_repo(root)
            manager = WorkArtifactManager(root, "cas")
            first = manager.transition(0, 0, None, "documents-captured", [_doc()], operation_nonce="same")
            replay = manager.transition(0, 0, None, "documents-captured", [_doc()], operation_nonce="same")
            self.assertEqual(replay, first)
            with self.assertRaisesRegex(WorkArtifactError, "operation-payload-mismatch"):
                manager.transition(0, 0, None, "documents-captured", [_doc(content="different")], operation_nonce="same")
            with self.assertRaisesRegex(WorkArtifactError, "cas-conflict"):
                manager.transition(0, 0, None, "documents-captured", [_doc("other")], operation_nonce="other")

    def test_sensitive_and_unbounded_inputs_do_not_echo_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git_repo(root)
            manager = WorkArtifactManager(root, "sensitive")
            secret = "-----BEGIN PRIVATE KEY-----\nsecret-value\n"
            with self.assertRaisesRegex(WorkArtifactError, "sensitive-content") as error:
                manager.transition(0, 0, None, "documents-captured", [_doc(content=secret)], operation_nonce="s")
            self.assertNotIn("secret-value", str(error.exception))
            with self.assertRaisesRegex(WorkArtifactError, "document-too-large"):
                manager.transition(0, 0, None, "documents-captured", [_doc(content="x" * (256 * 1024 + 1))], operation_nonce="large")

    def test_dry_run_is_zero_write_and_apply_requires_same_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git_repo(root)
            manager = WorkArtifactManager(root, "reconcile")
            captured = manager.transition(0, 0, None, "documents-captured", [_doc()], operation_nonce="c")
            reviewed = manager.transition(1, 1, captured["manifestHash"], "review-recorded", review={"receiptId":"r","packageHash":captured["packageHash"],"findings":[],"independent":True}, operation_nonce="r")
            post = manager.transition(1, 2, reviewed["manifestHash"], "post-review-recorded", review={"receiptId":"p","packageHash":reviewed["packageHash"],"findings":[],"independent":True}, operation_nonce="p")
            final = manager.transition(1, 3, post["manifestHash"], "verification-recorded", verification={"receiptId":"v","packageHash":post["packageHash"],"fresh":True,"passed":True}, operation_nonce="v")
            before = sorted(p.relative_to(root).as_posix() for p in (root / "selfworkflow").rglob("*"))
            report = manager.reconcile("dry-run", 1, 4, final["manifestHash"])
            after = sorted(p.relative_to(root).as_posix() for p in (root / "selfworkflow").rglob("*"))
            self.assertEqual(before, after)
            self.assertTrue(report["planHash"].startswith("sha256:"))
            with self.assertRaisesRegex(WorkArtifactError, "reconcile-plan-mismatch"):
                manager.reconcile("apply", 1, 4, final["manifestHash"], plan_hash="sha256:" + "0" * 64)

    def test_knowledge_package_and_publication_receipt_are_subject_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git_repo(root)
            manager = WorkArtifactManager(root, "knowledge")
            captured = manager.transition(0, 0, None, "documents-captured", [_doc()], operation_nonce="c")
            reviewed = manager.transition(1, 1, captured["manifestHash"], "review-recorded", review={"receiptId":"r","packageHash":captured["packageHash"],"findings":[],"independent":True}, operation_nonce="r")
            post = manager.transition(1, 2, reviewed["manifestHash"], "post-review-recorded", review={"receiptId":"p","packageHash":reviewed["packageHash"],"findings":[],"independent":True}, operation_nonce="p")
            final = manager.transition(1, 3, post["manifestHash"], "verification-recorded", verification={"receiptId":"v","packageHash":post["packageHash"],"fresh":True,"passed":True}, operation_nonce="v")
            package = manager.knowledge_package()
            self.assertEqual(package["manifestHash"], final["manifestHash"])
            publication = {
                "schemaVersion": 1, "backend": "selfopenwiki", "receiptId": "pub-1", "decision": "published",
                "subjectManifestHash": final["manifestHash"], "subjectPackageHash": final["packageHash"],
                "subjectContentGenerationHash": canonical_content_generation_hash(
                    [{"id": item["id"], "kind": item["kind"], "contentHash": item["contentHash"]} for item in package["documents"]], 1
                ),
                "publishedContentHash": "sha256:" + "c" * 64,
                "publishedAt": "2026-01-01T00:00:00Z",
            }
            publication["receiptHash"] = canonical_publication_receipt_hash(publication)
            published = manager.transition(1, 4, final["manifestHash"], "knowledge-published", publication=publication, operation_nonce="pub")
            self.assertEqual(published["taskState"], "knowledge-published")
            completed = manager.transition(1, 5, published["manifestHash"], "task-completed", operation_nonce="done")
            self.assertEqual(completed["taskState"], "completed")

    def test_schema_files_are_valid_and_limits_are_authoritative(self):
        for name in ("work-artifact-manifest.schema.json", "work-artifact-operation.schema.json", "work-artifact-publication-receipt.schema.json"):
            schema = json.loads((self.ROOT / "schemas" / name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        self.assertEqual(WDLC_LIMITS_V1["maxDocumentBytes"], 256 * 1024)
        self.assertEqual(WDLC_LIMITS_V1["maxArtifacts"], 16)


if __name__ == "__main__":
    unittest.main()
