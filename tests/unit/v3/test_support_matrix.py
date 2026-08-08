import unittest

from selfworkflow.v3.support_matrix import (
    SupportMatrixError,
    build_support_matrix,
    validate_support_matrix,
)


HASH = "sha256:" + "a" * 64
EVIDENCE = {key: "evidence-" + key.lower() for key in (
    "source", "adapter", "positive", "false", "conflict", "failure",
    "contextCost", "nativeValidation",
)}


def _entry(state="supported", evidence=None):
    return {"entryId": "codegraph-inspect", "capabilityId": "code.context", "operationId": "inspect", "platform": "windows", "adapterVersion": "3", "sourceIdentityRef": "source", "sourceIdentityHash": HASH, "state": state, "observedAt": "2026-08-09T00:00:00Z", "validUntil": "2026-09-09T00:00:00Z", "evidence": EVIDENCE if evidence is None else evidence}


class SupportMatrixTests(unittest.TestCase):
    def test_supported_requires_every_evidence_dimension(self):
        matrix = build_support_matrix("codegraph", [_entry()])
        validate_support_matrix(matrix)
        incomplete = dict(EVIDENCE)
        incomplete.pop("nativeValidation")
        with self.assertRaises(SupportMatrixError) as error:
            build_support_matrix("codegraph", [_entry(evidence=incomplete)])
        self.assertEqual(error.exception.reason, "provider-support-evidence-incomplete")

    def test_unverified_is_reportable_but_fake_supported_is_fixture_only(self):
        matrix = build_support_matrix("codegraph", [_entry("unverified", {})])
        validate_support_matrix(matrix)
        with self.assertRaises(SupportMatrixError) as error:
            build_support_matrix("fake.provider", [_entry()])
        self.assertEqual(error.exception.reason, "provider-fake-supported-production")

    def test_matrix_hash_is_deterministic(self):
        first = build_support_matrix("codegraph", [_entry("unverified", {})])
        second = build_support_matrix("codegraph", list(reversed([_entry("unverified", {})])))
        self.assertEqual(first["matrixHash"], second["matrixHash"])

    def test_matrix_hash_tamper_is_rejected(self):
        matrix = build_support_matrix("codegraph", [_entry("unverified", {})])
        matrix["entries"][0]["notes"] = "changed"
        with self.assertRaises(SupportMatrixError) as error:
            validate_support_matrix(matrix)
        self.assertEqual(error.exception.reason, "provider-support-matrix-hash-invalid")


if __name__ == "__main__":
    unittest.main()
