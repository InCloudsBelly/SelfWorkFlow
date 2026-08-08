from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from selfworkflow.release import evaluate_release


def _manifest():
    return {
        "schemaVersion": 1,
        "version": "0.1.0",
        "source": {"commit": "a" * 40, "dirty": False},
        "dependencyLockHash": "sha256:" + "b" * 64,
        "runtimeHash": "sha256:" + "c" * 64,
        "tests": [
            {"suite": suite, "command": f"verify {suite}", "executedAt": "2026-08-08T00:00:00Z", "status": "passed", "outputHash": "sha256:" + character * 64}
            for suite, character in (("unit", "d"), ("conformance", "e"), ("installer", "f"), ("behavioral", "1"))
        ],
        "review": {"reviewerId": "fresh-reviewer", "implementationContextId": "impl", "reviewContextId": "review", "level": "L2", "decision": "passed"},
        "hostEvidence": {
            "codex-cli": "supported", "codex-desktop": "supported",
            "claude-code": "experimental-unverified", "cursor": "experimental-unverified",
            "opencode": "experimental-unverified", "copilot": "instructions-only",
        },
        "knowledgeEvidence": {"c7-openwiki": "experimental-unverified"},
        "skipped": [],
        "residualRisks": [],
    }


class ReleaseGateTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_release_schema_is_closed_and_complete_candidate_can_pass(self):
        manifest = _manifest()
        schema = json.loads(
            (self.ROOT / "docs/releases/release-manifest.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(manifest)
        self.assertEqual(evaluate_release(manifest), {"eligible": True, "issues": ()})

    def test_missing_native_evidence_failed_tests_dirty_source_or_nonindependent_review_blocks(self):
        mutations = []
        native = _manifest(); native["hostEvidence"]["codex-cli"] = "experimental-unverified"; mutations.append((native, "host-evidence-missing:codex-cli"))
        failed = _manifest(); failed["tests"][0]["status"] = "failed"; mutations.append((failed, "test-not-passed:unit"))
        dirty = _manifest(); dirty["source"]["dirty"] = True; mutations.append((dirty, "source-dirty"))
        review = _manifest(); review["review"]["reviewContextId"] = "impl"; mutations.append((review, "review-not-independent"))
        for manifest, issue in mutations:
            with self.subTest(issue=issue):
                result = evaluate_release(manifest)
                self.assertFalse(result["eligible"])
                self.assertIn(issue, result["issues"])


if __name__ == "__main__":
    unittest.main()
