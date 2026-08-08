import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from selfworkflow.v3.provider_config import (
    ProviderFallbackReceipt,
    ProviderConfigError,
    build_provider_registry,
    load_provider_config,
    resolve_provider,
)
from selfworkflow.v3.provider_binding import (
    build_git_source_identity,
    validate_source_identity,
)
from selfworkflow.v3.support_matrix import build_support_matrix, validate_support_matrix


HASH = "sha256:" + "a" * 64
EMPTY_HASH = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
EVIDENCE = {key: HASH for key in (
    "source", "adapter", "positive", "false", "conflict", "failure",
    "contextCost", "nativeValidation",
)}


class ProviderConfigTests(unittest.TestCase):
    def _registry(self, states):
        catalog = {"schemaVersion": 3, "providers": []}
        descriptors = {}
        matrices = {}
        sources = {}
        for index, (provider_id, state) in enumerate(states.items()):
            source_ref = provider_id.replace(".", "-") + "-source"
            source = validate_source_identity(build_git_source_identity(
                f"https://example.invalid/{provider_id}",
                format(index + 1, "040x"), HASH, False, EMPTY_HASH, EMPTY_HASH,
            ))
            sources[source_ref] = source
            descriptors[provider_id] = {
                "schemaVersion": 3, "providerId": provider_id, "kind": "agent-native",
                "capabilities": ["code.context"], "sourceIdentityRef": source_ref,
                "license": {"spdxId": "MIT"}, "adapterRef": provider_id + ".adapter",
                "adapterHash": HASH, "supportMatrixRef": provider_id + ".matrix",
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
            matrix = build_support_matrix(provider_id, [{
                "entryId": provider_id.replace(".", "-") + "-inspect",
                "capabilityId": "code.context", "operationId": "inspect",
                "platform": "windows", "adapterVersion": "3", "adapterHash": HASH,
                "sourceIdentityRef": source_ref, "sourceIdentityHash": source.identity_hash,
                "state": state, "observedAt": "2026-08-09T00:00:00Z",
                "validUntil": "2026-09-09T00:00:00Z",
                "evidence": EVIDENCE if state == "supported" else {},
            }])
            matrices[provider_id] = validate_support_matrix(matrix)
            catalog["providers"].append({
                "providerId": provider_id, "descriptorRef": provider_id + ".yaml",
                "lifecycle": "supported" if state == "supported" else "unverified",
            })
        return build_provider_registry(catalog, descriptors, matrices, sources)

    def _write_config(self, root, provider_path):
        target = Path(root) / "SelfWorkFlow" / "config" / "providers.local.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({
            "schemaVersion": 3,
            "providers": [{
                "providerId": "codegraph.local",
                "sourcePath": str(provider_path),
                "enabled": True,
            }],
        }), encoding="utf-8")
        return target

    def test_default_path_is_injected_and_missing_config_does_not_scan(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "unrelated-provider").mkdir()
            config = load_provider_config(root=root_path)
            self.assertEqual(config, {"schemaVersion": 3, "providers": []})

    def test_explicit_task_failure_never_falls_back(self):
        registry = self._registry({"public.provider": "supported"})
        with self.assertRaises(ProviderConfigError) as error:
            resolve_provider(
                "code.context", "inspect",
                task_explicit="missing", public=["public.provider"], registry=registry,
            )
        self.assertEqual(error.exception.reason, "provider-task-explicit-invalid")
        self.assertNotIn("missing", str(error.exception))

    def test_precedence_and_visible_fallback_receipt(self):
        registry = self._registry({
            "project.provider": "unsupported", "machine.provider": "supported",
            "public.provider": "supported",
        })
        result = resolve_provider(
            "code.context", "inspect",
            project=["project.provider"], user_machine=["machine.provider"],
            public=["public.provider"], registry=registry,
        )
        self.assertEqual(result.provider_id, "machine.provider")
        self.assertIsNotNone(result.fallback_receipt)
        receipt = result.fallback_receipt.document
        self.assertEqual(receipt["selectedLayer"], "user-machine")
        self.assertEqual(len(receipt["candidates"]), 3)
        self.assertEqual(receipt["candidates"][0]["rejectionReason"], "support-unsupported")

    def test_conflicting_same_layer_is_stable_failure(self):
        registry = self._registry({"a": "supported", "b": "supported"})
        with self.assertRaises(ProviderConfigError) as error:
            resolve_provider(
                "code.context", "inspect",
                user_machine=["a", "b"], registry=registry,
            )
        self.assertEqual(error.exception.reason, "provider-config-conflict")

    def test_candidate_and_unverified_cannot_be_selected_as_supported(self):
        registry = self._registry({"candidate": "unverified", "unverified": "unverified"})
        with self.assertRaises(ProviderConfigError) as error:
            resolve_provider(
                "code.context", "inspect",
                task_explicit={"providerId": "candidate", "state": "supported"},
                builtin=["unverified"], registry=registry,
            )
        self.assertEqual(error.exception.reason, "provider-task-explicit-invalid")

    def test_user_config_is_explicitly_loaded_and_path_is_not_echoed(self):
        with tempfile.TemporaryDirectory() as root:
            provider_path = Path(root) / "provider"
            provider_path.mkdir()
            self._write_config(root, provider_path.resolve())
            config = load_provider_config(root=root)
            self.assertEqual(config["providers"][0]["providerId"], "codegraph.local")

    def test_config_read_is_bounded_to_one_mib(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "SelfWorkFlow" / "config" / "providers.local.yaml"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"x" * (1024 * 1024 + 1))
            with self.assertRaises(ProviderConfigError) as error:
                load_provider_config(root=root)
        self.assertEqual(error.exception.reason, "provider-config-resource-limit")

    def test_config_rejects_duplicate_alias_multidoc_and_non_json_yaml(self):
        payloads = (
            "schemaVersion: 3\nschemaVersion: 3\nproviders: []\n",
            "schemaVersion: 3\nproviders: &p []\ncopy: *p\n",
            "schemaVersion: 3\nproviders: []\n---\nschemaVersion: 3\nproviders: []\n",
            "schemaVersion: 3\nproviders: []\nvalue: 2026-08-09\n",
        )
        for payload in payloads:
            with self.subTest(payload=payload[:20]), tempfile.TemporaryDirectory() as root:
                target = Path(root) / "SelfWorkFlow" / "config" / "providers.local.yaml"
                target.parent.mkdir(parents=True)
                target.write_text(payload, encoding="utf-8")
                with self.assertRaises(ProviderConfigError):
                    load_provider_config(root=root)

    def test_config_rejects_invalid_utf8_and_parent_identity_change(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "SelfWorkFlow" / "config" / "providers.local.yaml"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"\xff\xfe")
            with self.assertRaises(ProviderConfigError):
                load_provider_config(root=root)
        with tempfile.TemporaryDirectory() as root:
            provider_path = Path(root) / "provider"
            provider_path.mkdir()
            self._write_config(root, provider_path.resolve())
            with patch("selfworkflow.v3.catalog._same_parent_identities", return_value=False):
                with self.assertRaises(ProviderConfigError) as error:
                    load_provider_config(root=root)
            self.assertEqual(error.exception.reason, "provider-config-path-changed")

    def test_source_path_must_be_existing_canonical_absolute_and_is_redacted(self):
        with tempfile.TemporaryDirectory() as root:
            provider_path = Path(root) / "provider"
            provider_path.mkdir()
            noncanonical = provider_path.parent / "." / provider_path.name
            self._write_config(root, str(noncanonical) + "\\..\\provider")
            with self.assertRaises(ProviderConfigError) as error:
                load_provider_config(root=root)
            self.assertEqual(error.exception.reason, "provider-config-path-invalid")
            self.assertNotIn(str(provider_path), str(error.exception))

    def test_invalid_path_fails_without_disclosing_path(self):
        with self.assertRaises(ProviderConfigError) as error:
            resolve_provider(
                "code.context", "inspect",
                user_config={"schemaVersion": 3, "providers": [{
                    "providerId": "local", "sourcePath": "C:relative:secret",
                    "enabled": True,
                }]},
            )
        self.assertEqual(error.exception.reason, "provider-config-path-invalid")
        self.assertNotIn("secret", str(error.exception))

    def test_registry_cross_binds_descriptor_adapter_source_and_support(self):
        registry = self._registry({"trusted": "supported"})
        result = resolve_provider(
            "code.context", "inspect", public=["trusted"], registry=registry,
        )
        binding = result.binding.document
        self.assertEqual(binding["providerId"], "trusted")
        self.assertEqual(binding["adapterHash"], HASH)
        self.assertRegex(registry.registry_hash, r"^sha256:[0-9a-f]{64}$")

    def test_registry_is_immutable_against_candidate_state_dict_tamper(self):
        registry = self._registry({"candidate": "unverified", "trusted": "supported"})
        candidate = {"providerId": "candidate", "state": "supported"}
        result = resolve_provider(
            "code.context", "inspect", project=[candidate], public=["trusted"],
            registry=registry,
        )
        self.assertEqual(result.provider_id, "trusted")
        self.assertEqual(
            result.fallback_receipt.document["candidates"][0]["rejectionReason"],
            "support-unverified",
        )

    def test_fallback_receipt_hash_binds_every_candidate_input(self):
        registry = self._registry({
            "first": "unsupported", "second": "unsupported", "trusted": "supported",
        })
        first = resolve_provider(
            "code.context", "inspect", project=["first"], public=["trusted"],
            registry=registry,
        ).fallback_receipt
        second = resolve_provider(
            "code.context", "inspect", project=["second"], public=["trusted"],
            registry=registry,
        ).fallback_receipt
        self.assertNotEqual(first.receipt_hash, second.receipt_hash)
        with self.assertRaises(TypeError):
            ProviderFallbackReceipt({})


if __name__ == "__main__":
    unittest.main()
