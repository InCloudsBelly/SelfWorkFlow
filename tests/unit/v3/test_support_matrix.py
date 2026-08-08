import unittest

from selfworkflow.v3.support_matrix import (
    SupportMatrixError,
    ValidatedSupportEntry,
    build_support_matrix,
    is_selectable,
    validate_support_matrix,
)


HASH = "sha256:" + "a" * 64
EVIDENCE = {key: HASH for key in (
    "source", "adapter", "positive", "false", "conflict", "failure",
    "contextCost", "nativeValidation",
)}


def _entry(state="supported", evidence=None):
    return {"entryId": "codegraph-inspect", "capabilityId": "code.context", "operationId": "inspect", "platform": "windows", "adapterVersion": "3", "adapterHash": HASH, "sourceIdentityRef": "source", "sourceIdentityHash": HASH, "state": state, "observedAt": "2026-08-09T00:00:00Z", "validUntil": "2026-09-09T00:00:00Z", "evidence": EVIDENCE if evidence is None else evidence}


class SupportMatrixTests(unittest.TestCase):
    def test_supported_requires_every_evidence_dimension(self):
        matrix = build_support_matrix("codegraph", [_entry()])
        artifact = validate_support_matrix(matrix)
        self.assertTrue(is_selectable(artifact, "codegraph-inspect"))
        incomplete = dict(EVIDENCE)
        incomplete.pop("nativeValidation")
        with self.assertRaises(SupportMatrixError) as error:
            build_support_matrix("codegraph", [_entry(evidence=incomplete)])
        self.assertEqual(error.exception.reason, "provider-support-evidence-incomplete")

    def test_unverified_is_reportable_but_fake_supported_is_fixture_only(self):
        matrix = build_support_matrix("codegraph", [_entry("unverified", {})])
        artifact = validate_support_matrix(matrix)
        self.assertFalse(is_selectable(artifact, "codegraph-inspect"))
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

    def test_entry_hash_is_canonical_and_entry_tamper_is_rejected(self):
        matrix = build_support_matrix("codegraph", [_entry()])
        self.assertRegex(matrix["entries"][0]["entryHash"], r"^sha256:[0-9a-f]{64}$")
        matrix["entries"][0]["state"] = "unverified"
        import hashlib, json
        body = {key: value for key, value in matrix.items() if key != "matrixHash"}
        matrix["matrixHash"] = "sha256:" + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self.assertRaises(SupportMatrixError) as error:
            validate_support_matrix(matrix)
        self.assertEqual(error.exception.reason, "provider-support-entry-hash-invalid")

    def test_ids_and_support_tuples_are_unique_and_time_ordered(self):
        duplicate = _entry()
        with self.assertRaises(SupportMatrixError):
            build_support_matrix("codegraph", [duplicate, dict(duplicate)])
        invalid_time = _entry()
        invalid_time["validUntil"] = "2026-08-08T00:00:00Z"
        with self.assertRaises(SupportMatrixError) as error:
            build_support_matrix("codegraph", [invalid_time])
        self.assertEqual(error.exception.reason, "provider-support-time-invalid")

    def test_plain_supported_dict_and_public_constructor_are_rejected(self):
        with self.assertRaises(SupportMatrixError) as error:
            is_selectable({"state": "supported"})
        self.assertEqual(error.exception.reason, "provider-support-entry-not-validated")
        with self.assertRaises(TypeError):
            ValidatedSupportEntry({"state": "supported"})

    def test_supported_evidence_must_be_hash_or_reference(self):
        bad = dict(EVIDENCE, nativeValidation="claimed")
        with self.assertRaises(SupportMatrixError) as error:
            build_support_matrix("codegraph", [_entry(evidence=bad)])
        self.assertEqual(error.exception.reason, "provider-support-evidence-invalid")

    def test_test_fixture_evidence_cannot_support_a_production_provider(self):
        fixture_evidence = {
            key: "ref:test-fixture/evidence"
            for key in EVIDENCE
        }
        with self.assertRaises(SupportMatrixError) as error:
            build_support_matrix("codegraph", [_entry(evidence=fixture_evidence)])
        self.assertEqual(
            error.exception.reason,
            "provider-test-evidence-production",
        )


if __name__ == "__main__":
    unittest.main()
