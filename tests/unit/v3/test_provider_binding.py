import unittest

from selfworkflow.v3.provider_binding import (
    ProviderBindingError,
    build_git_source_identity,
    build_binding_snapshot,
    validate_binding_snapshot,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


class ProviderBindingTests(unittest.TestCase):
    def test_git_identity_contains_dirty_and_untracked_content_hashes(self):
        identity = build_git_source_identity(
            "https://example.invalid/repo.git", "a" * 40, HASH_B, True, HASH_A,
        )
        self.assertEqual(identity["kind"], "git-tree")
        self.assertEqual(identity["dirtyContentHash"], HASH_A)
        self.assertEqual(identity["untrackedContentHash"], HASH_A)

    def test_snapshot_is_deterministic_and_content_addressed(self):
        bindings = [{
            "moduleId": "code.context", "providerId": "codegraph.local",
            "capabilityId": "code.context", "operationId": "inspect",
            "adapterHash": HASH_A, "sourceIdentityHash": HASH_B,
            "supportMatrixEntryRef": "codegraph-local-inspect",
            "supportMatrixEntryHash": HASH_A, "requirementMode": "preferred",
        }]
        first = build_binding_snapshot(list(reversed(bindings)))
        second = build_binding_snapshot(bindings)
        self.assertEqual(first, second)
        validate_binding_snapshot(first)
        self.assertEqual(first["bindingSnapshotHash"].startswith("sha256:"), True)

    def test_dynamic_freshness_or_query_output_is_rejected(self):
        binding = {
            "moduleId": "code.context", "providerId": "provider",
            "capabilityId": "code.context", "operationId": "inspect",
            "adapterHash": HASH_A, "sourceIdentityHash": HASH_B,
            "supportMatrixEntryRef": "entry", "supportMatrixEntryHash": HASH_A,
            "requirementMode": "preferred", "indexRevision": "fresh",
        }
        with self.assertRaises(ProviderBindingError) as error:
            build_binding_snapshot([binding])
        self.assertEqual(error.exception.reason, "provider-binding-dynamic-field")

    def test_external_snapshot_rejects_tamper_and_duplicate_binding(self):
        binding = {
            "moduleId": "code.context", "providerId": "provider",
            "capabilityId": "code.context", "operationId": "inspect",
            "adapterHash": HASH_A, "sourceIdentityHash": HASH_B,
            "supportMatrixEntryRef": "entry", "supportMatrixEntryHash": HASH_A,
            "requirementMode": "preferred",
        }
        snapshot = build_binding_snapshot([binding])
        tampered = dict(snapshot, bindings=[binding, dict(binding)])
        tampered["bindingSnapshotHash"] = snapshot["bindingSnapshotHash"]
        with self.assertRaises(ProviderBindingError) as error:
            validate_binding_snapshot(tampered)
        self.assertEqual(error.exception.reason, "provider-binding-hash-invalid")


if __name__ == "__main__":
    unittest.main()
