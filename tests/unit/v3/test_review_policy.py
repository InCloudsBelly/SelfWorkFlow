from pathlib import Path
import tempfile
import unittest


class ReviewPolicyTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[3]

    def test_authoritative_policy_is_strict_loaded_hashed_and_immutable(self):
        from selfworkflow.v3.review_policy import load_post_grill_review_policy

        policy = load_post_grill_review_policy(
            self.ROOT / "workflow/v3/post-grill-review.yaml"
        )
        self.assertTrue(policy._is_valid())
        self.assertTrue(policy.policy_hash.startswith("sha256:"))
        document = policy.document
        document["dispatch"]["forkContext"] = True
        self.assertFalse(policy.document["dispatch"]["forkContext"])
        with self.assertRaises(AttributeError):
            policy._policy_hash = "sha256:" + "0" * 64

    def test_policy_semantic_drift_fails_closed(self):
        from selfworkflow.v3.review_policy import ReviewPolicyError, load_post_grill_review_policy

        source = (self.ROOT / "workflow/v3/post-grill-review.yaml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "post-grill-review.yaml"
            path.write_text(
                source.replace("forkContext: false", "forkContext: true"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ReviewPolicyError, "post-grill-review-policy-invalid"):
                load_post_grill_review_policy(path)


if __name__ == "__main__":
    unittest.main()
