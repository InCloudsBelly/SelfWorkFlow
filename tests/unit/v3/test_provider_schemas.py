import json
import unittest

from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.hashing import content_hash


HASH = "sha256:" + "a" * 64


def _load(name, document):
    return load_contract(name, json.dumps(document))


def _rehash(document, field):
    document[field] = content_hash({key: value for key, value in document.items() if key != field})
    return document


class ProviderSchemaTests(unittest.TestCase):
    def test_all_phase_2a_schemas_are_registered(self):
        names = (
            "provider-descriptor.schema.json", "provider-local-config.schema.json",
            "provider-binding-snapshot.schema.json", "provider-support-matrix.schema.json",
            "provider-source-identity.schema.json", "provider-project-state-receipt.schema.json",
            "provider-operation-plan.schema.json", "provider-approval-receipt.schema.json",
            "provider-operation-receipt.schema.json", "provider-query-plan.schema.json",
            "provider-query-receipt.schema.json", "provider-mutation-evidence.schema.json",
            "workspace-fingerprint.schema.json", "provider-fallback-receipt.schema.json",
            "provider-project-lease.schema.json", "provider-machine-authorization.schema.json",
            "provider-stale-unlock-authorization.schema.json",
            "provider-command-template.schema.json", "trusted-command-registry.schema.json",
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
            "providerBindingHash": HASH, "providerId": "provider", "canonicalProjectRootHash": HASH,
            "startedAt": "2026-08-09T00:00:00Z", "completedAt": "2026-08-09T00:00:00Z",
            "observedAt": "2026-08-09T00:00:00Z", "preStateIdentity": HASH,
            "postStateIdentity": HASH, "mutationTargetHash": HASH, "payloadHash": HASH,
            "evidenceKind": "filesystem-manifest", "actualTargets": [{"targetKind": "filesystem", "targetId": "managed/index", "action": "modify"}], "before": [], "after": [{"path": "managed/index", "type": "file", "size": 1, "contentHash": HASH, "reparseIdentityHash": HASH}],
        }
        base["payloadHash"] = content_hash({"before": base["before"], "after": base["after"]})
        _rehash(base, "evidenceHash")
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

    def test_provider_timestamp_requires_rfc3339_utc_z(self):
        evidence = {
            "schemaVersion": 3, "evidenceHash": HASH, "subjectKind": "operation-plan",
            "subjectPlanHash": HASH, "executionNonce": "nonce", "attemptRef": "attempt",
            "providerBindingHash": HASH, "providerId": "provider", "canonicalProjectRootHash": HASH,
            "startedAt": "2026-08-09T00:00:00Z", "completedAt": "2026-08-09T00:00:00Z",
            "observedAt": "2026-08-09T08:00:00+08:00", "preStateIdentity": HASH,
            "postStateIdentity": HASH, "mutationTargetHash": HASH, "payloadHash": HASH,
            "evidenceKind": "filesystem-manifest", "actualTargets": [{"targetKind": "filesystem", "targetId": "managed/index", "action": "modify"}], "before": [], "after": [{"path": "managed/index", "type": "file", "size": 1, "contentHash": HASH, "reparseIdentityHash": HASH}],
        }
        evidence["payloadHash"] = content_hash({"before": evidence["before"], "after": evidence["after"]})
        _rehash(evidence, "evidenceHash")
        with self.assertRaises(ContractError):
            _load("provider-mutation-evidence.schema.json", evidence)
        evidence["observedAt"] = "2026-08-09T00:00:00Z"
        _rehash(evidence, "evidenceHash")
        _load("provider-mutation-evidence.schema.json", evidence)

    def test_provider_timestamp_ranges_are_monotonic(self):
        project_state = {
            "schemaVersion": 3, "receiptHash": HASH, "providerId": "provider",
            "sourceIdentityHash": HASH, "canonicalProjectRootHash": HASH,
            "workspaceFingerprintHash": HASH, "indexRevision": "1",
            "health": "ready", "sourceContentFresh": "fresh",
            "relationshipFresh": "fresh", "capturedAt": "2026-08-09T00:00:01Z",
            "validUntil": "2026-08-09T00:00:00Z", "pendingFiles": [],
            "parseFailures": [],
        }
        approval = {
            "schemaVersion": 3, "receiptHash": HASH, "subjectKind": "operation-plan",
            "authorizationSubjectHash": HASH, "decision": "approved",
            "confirmationSource": "user-confirmation", "scope": "one operation",
            "targetHashes": [HASH], "issuedAt": "2026-08-09T00:00:01Z",
            "expiresAt": "2026-08-09T00:00:00Z", "nonce": "nonce",
            "revocationState": "active",
        }
        operation = {
            "schemaVersion": 3, "receiptHash": HASH, "operationPlanHash": HASH,
            "executionNonce": "nonce", "attemptRef": "attempt", "providerId": "provider",
            "bindingSnapshotHash": HASH, "canonicalProjectRootHash": HASH, "startedAt": "2026-08-09T00:00:01Z",
            "completedAt": "2026-08-09T00:00:00Z", "outcome": "failed",
            "replayState": "terminal-failed",
            "mutationEvidenceRefs": [],
        }
        for schema, document in (
            ("provider-project-state-receipt.schema.json", project_state),
            ("provider-approval-receipt.schema.json", approval),
            ("provider-operation-receipt.schema.json", operation),
        ):
            with self.subTest(schema=schema):
                with self.assertRaises(ContractError) as error:
                    _load(schema, document)
                self.assertEqual(error.exception.validator, "semantic")

    def test_query_and_mutation_paths_are_normalized_project_relative(self):
        receipt = {
            "schemaVersion": 3, "receiptHash": HASH, "queryPlanHash": HASH,
            "executionNonce": "nonce", "attemptRef": "attempt", "providerId": "provider",
            "adapterHash": HASH, "sourceIdentityHash": HASH, "projectStateReceiptHash": HASH,
            "workspaceFingerprintHash": HASH, "canonicalProjectRootHash": HASH, "indexRevision": "1", "indexCompleteness": "complete",
            "startedAt": "2026-08-09T00:00:00Z", "completedAt": "2026-08-09T00:00:00Z",
            "pendingFiles": [], "parseFailures": [], "returnedFiles": [{
                "path": "Source/main.cpp", "byteRange": [0, 1], "contentHash": HASH,
            }], "truncated": False, "preQueryWorkspaceFingerprintHash": HASH,
            "postQueryWorkspaceFingerprintHash": HASH, "actualSideEffects": "none",
            "replayState": "terminal-succeeded",
            "mutationEvidenceRefs": [],
        }
        _rehash(receipt, "receiptHash")
        with self.assertRaises(ContractError) as valid_unbound:
            _load("provider-query-receipt.schema.json", receipt)
        self.assertEqual(valid_unbound.exception.reason, "provider-receipt-plan-required")
        for invalid in ("../secret", "/absolute", "C:/secret", "Source\\secret.cpp"):
            changed = json.loads(json.dumps(receipt))
            changed["returnedFiles"][0]["path"] = invalid
            with self.subTest(path=invalid), self.assertRaises(ContractError):
                _load("provider-query-receipt.schema.json", changed)


if __name__ == "__main__":
    unittest.main()
