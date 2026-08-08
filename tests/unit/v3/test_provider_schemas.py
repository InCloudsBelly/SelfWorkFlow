import json
import unittest

from selfworkflow.v3.contracts import ContractError, load_contract


HASH = "sha256:" + "a" * 64


def _load(name, document):
    return load_contract(name, json.dumps(document))


class ProviderSchemaTests(unittest.TestCase):
    def test_all_phase_2a_schemas_are_registered(self):
        names = (
            "provider-descriptor.schema.json", "provider-local-config.schema.json",
            "provider-binding-snapshot.schema.json", "provider-support-matrix.schema.json",
            "provider-source-identity.schema.json", "provider-project-state-receipt.schema.json",
            "provider-operation-plan.schema.json", "provider-approval-receipt.schema.json",
            "provider-operation-receipt.schema.json", "provider-query-plan.schema.json",
            "provider-query-receipt.schema.json", "provider-mutation-evidence.schema.json",
            "workspace-fingerprint.schema.json",
        )
        for name in names:
            with self.subTest(name=name):
                with self.assertRaises(ContractError) as error:
                    load_contract(name, "{}")
                self.assertNotEqual(error.exception.reason, "contract-schema-not-registered")

    def test_source_identity_is_a_closed_tagged_union(self):
        valid = {
            "kind": "git-tree", "remote": "https://example.invalid/repo.git",
            "commit": "a" * 40, "treeHash": HASH, "dirty": False,
            "dirtyContentHash": HASH, "untrackedContentHash": HASH,
        }
        _load("provider-source-identity.schema.json", valid)
        for old_kind in ("git", "package-or-binary"):
            invalid = dict(valid)
            invalid["kind"] = old_kind
            with self.assertRaises(ContractError):
                _load("provider-source-identity.schema.json", invalid)

    def test_mutation_identity_rejects_old_enum_and_unknown_fields(self):
        base = {
            "schemaVersion": 3, "evidenceHash": HASH, "subjectKind": "operation-plan",
            "subjectPlanHash": HASH, "executionNonce": "nonce", "attemptRef": "attempt",
            "providerBindingHash": HASH, "canonicalProjectRootHash": HASH,
            "observedAt": "2026-08-09T00:00:00Z", "preStateIdentity": HASH,
            "postStateIdentity": HASH, "mutationTargetHash": HASH, "payloadHash": HASH,
            "evidenceKind": "filesystem-manifest", "before": [], "after": [],
        }
        _load("provider-mutation-evidence.schema.json", base)
        old = dict(base, evidenceKind="filesystem-delta")
        with self.assertRaises(ContractError):
            _load("provider-mutation-evidence.schema.json", old)
        with self.assertRaises(ContractError):
            _load("provider-mutation-evidence.schema.json", dict(base, secret="nope"))

    def test_descriptor_unknown_field_is_rejected(self):
        descriptor = {
            "schemaVersion": 3, "providerId": "builtin.cpp-core", "kind": "agent-native",
            "capabilities": ["code.context"], "sourceIdentityRef": "builtin-source",
            "license": {"spdxId": "MIT"}, "adapterRef": "builtin.adapter",
            "adapterHash": HASH, "supportMatrixRef": "builtin.matrix",
            "dataBoundary": "local-only", "remoteSourceTransfer": "forbidden",
            "operations": [{
                "operationId": "inspect", "triggerLevel": "automatic-readonly", "risk": "low",
                "sideEffects": [], "ownershipDomain": "selfworkflow-managed", "mutationTargets": [],
                "argvTemplate": "none", "cwdPolicy": "none", "envAllowlist": [],
                "networkPolicy": "none", "lockScope": "none", "timeoutSeconds": 1,
                "outputLimitBytes": 1, "preconditions": [], "verification": ["contract"],
                "rollback": "none",
            }],
        }
        _load("provider-descriptor.schema.json", descriptor)
        with self.assertRaises(ContractError):
            _load("provider-descriptor.schema.json", dict(descriptor, secret="nope"))


if __name__ == "__main__":
    unittest.main()
