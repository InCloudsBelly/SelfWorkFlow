import unittest

from selfworkflow.v3.provider_binding import (
    ProviderBindingError,
    ValidatedSourceIdentity,
    build_binary_source_identity,
    build_git_source_identity,
    build_host_native_source_identity,
    build_service_source_identity,
    build_binding_snapshot,
    create_provider_binding,
    source_identity_hash,
    validate_binding_snapshot,
    validate_source_identity,
)
from selfworkflow.v3.support_matrix import build_support_matrix, validate_support_matrix


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
EMPTY_HASH = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
EVIDENCE = {key: HASH_A for key in (
    "source", "adapter", "positive", "false", "conflict", "failure",
    "contextCost", "nativeValidation",
)}


class ProviderBindingTests(unittest.TestCase):
    def _binding(self, *, layer="user-machine"):
        source = validate_source_identity(build_git_source_identity(
            "https://example.invalid/repo", "a" * 40, HASH_A,
            False, EMPTY_HASH, EMPTY_HASH,
        ))
        matrix = build_support_matrix("codegraph.local", [{
            "entryId": "codegraph-local-inspect", "capabilityId": "code.context",
            "operationId": "inspect", "platform": "windows", "adapterVersion": "3",
            "adapterHash": HASH_A, "sourceIdentityRef": "codegraph-local-source",
            "sourceIdentityHash": source.identity_hash, "state": "supported",
            "observedAt": "2026-08-09T00:00:00Z", "validUntil": "2026-09-09T00:00:00Z",
            "evidence": EVIDENCE,
        }])
        support = validate_support_matrix(matrix).entry("codegraph-local-inspect")
        return create_provider_binding(
            "code.context", layer, "preferred", support, source,
        )

    def test_git_identity_contains_dirty_and_untracked_content_hashes(self):
        identity = build_git_source_identity(
            "https://example.invalid/repo.git", "a" * 40, HASH_B, True, HASH_A,
        )
        self.assertEqual(identity["kind"], "git-tree")
        self.assertEqual(identity["dirtyContentHash"], HASH_A)
        self.assertEqual(identity["untrackedContentHash"], HASH_A)

    def test_git_remote_is_canonical_for_https_ssh_and_scp_forms(self):
        cases = (
            ("HTTPS://Example.COM:443/org/./repo.git/", "https://example.com/org/repo"),
            ("ssh://git@Example.COM:22/org/repo.git", "ssh://git@example.com/org/repo"),
            ("git@Example.COM:org/repo.git", "git@example.com:org/repo"),
        )
        for remote, expected in cases:
            with self.subTest(remote=remote):
                identity = build_git_source_identity(
                    remote, "a" * 40, HASH_A, False, EMPTY_HASH, EMPTY_HASH,
                )
                self.assertEqual(identity["remote"], expected)
                validate_source_identity(identity)

    def test_git_identity_rejects_bad_commit_remote_and_clean_inventory(self):
        cases = (
            ("https://example.com/repo", "a" * 39, EMPTY_HASH, EMPTY_HASH),
            ("https://user:secret@example.com/repo", "a" * 40, EMPTY_HASH, EMPTY_HASH),
            ("https://example.com/repo?token=secret", "a" * 40, EMPTY_HASH, EMPTY_HASH),
            ("https://example.com/repo", "a" * 40, HASH_A, EMPTY_HASH),
        )
        for remote, commit, dirty_hash, untracked_hash in cases:
            with self.subTest(remote=remote, commit=commit), self.assertRaises(ProviderBindingError):
                build_git_source_identity(
                    remote, commit, HASH_A, False, dirty_hash, untracked_hash,
                )

    def test_all_source_identity_variants_are_semantically_validated_and_sealed(self):
        identities = (
            build_binary_source_identity("pkg", "1.0", HASH_A, HASH_B, HASH_A),
            build_service_source_identity(HASH_A, "mcp", HASH_B, "local-only"),
            build_host_native_source_identity("code.context", "1", HASH_A),
        )
        for identity in identities:
            artifact = validate_source_identity(identity)
            self.assertRegex(source_identity_hash(artifact), r"^sha256:[0-9a-f]{64}$")
        with self.assertRaises(TypeError):
            ValidatedSourceIdentity({"kind": "host-native"})

    def test_snapshot_is_deterministic_and_content_addressed(self):
        bindings = [self._binding()]
        first = build_binding_snapshot(list(reversed(bindings)))
        second = build_binding_snapshot(bindings)
        self.assertEqual(first, second)
        validate_binding_snapshot(first)
        self.assertEqual(first["bindingSnapshotHash"].startswith("sha256:"), True)
        self.assertEqual(first["bindings"][0]["configurationLayer"], "user-machine")
        self.assertEqual(
            first["bindings"][0]["supportMatrixEntryHash"],
            bindings[0].support_entry.entry_hash,
        )

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
        self.assertEqual(error.exception.reason, "provider-binding-not-validated")

    def test_external_snapshot_rejects_tamper_and_duplicate_binding(self):
        snapshot = build_binding_snapshot([self._binding()])
        binding = snapshot["bindings"][0]
        tampered = dict(snapshot, bindings=[binding, dict(binding)])
        tampered["bindingSnapshotHash"] = snapshot["bindingSnapshotHash"]
        with self.assertRaises(ProviderBindingError) as error:
            validate_binding_snapshot(tampered)
        self.assertEqual(error.exception.reason, "provider-binding-hash-invalid")

    def test_binding_rejects_source_support_cross_mismatch(self):
        binding = self._binding()
        other_source = validate_source_identity(build_git_source_identity(
            "https://example.invalid/other", "b" * 40, HASH_B,
            False, EMPTY_HASH, EMPTY_HASH,
        ))
        with self.assertRaises(ProviderBindingError) as error:
            create_provider_binding(
                "code.context", "project", "preferred",
                binding.support_entry, other_source,
            )
        self.assertEqual(error.exception.reason, "provider-binding-source-mismatch")


if __name__ == "__main__":
    unittest.main()
