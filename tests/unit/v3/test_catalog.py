import hashlib
import io
import importlib.util
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import yaml


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_yaml(path: Path, document: object) -> str:
    content = yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return _hash(content)


@contextmanager
def _workspace(*, module_ids=("review",), module_order=None, domain_order=None):
    temporary = TemporaryDirectory()
    root = Path(temporary.name)
    module_order = module_order or list(module_ids)
    domain_order = domain_order or ["foundation"]
    module_refs = []
    for module_id in module_order:
        module = {
            "schemaVersion": 3,
            "id": module_id,
            "sourceHash": _hash(module_id.encode("utf-8")),
            "stage": "reviewed",
            "slot": "review.primary",
            "selectionMode": "static",
            "invocation": {"kind": "agent-native", "ref": "review"},
            "dependencies": [],
            "conflicts": [],
            "contextCost": {"estimatedContextCost": 1, "estimatedExecutionCost": 1},
            "supportEvidence": {
                "sourceIntegrity": "supported",
                "adapterSupport": "supported",
                "runtimeCapability": "supported",
                "behaviorEvidence": "supported",
            },
        }
        ref = f"modules/{module_id}.yaml"
        module_refs.append({"id": module_id, "ref": ref, "hash": _write_yaml(root / "catalog" / "v3" / ref, module)})
    domain_refs = []
    for domain_id in domain_order:
        ref = f"domains/{domain_id}.yaml"
        domain = {"schemaVersion": 3, "id": domain_id, "modules": list(module_ids)}
        domain_refs.append({"id": domain_id, "ref": ref, "hash": _write_yaml(root / "catalog" / "v3" / ref, domain)})
    index = {"schemaVersion": 3, "domains": domain_refs, "modules": module_refs}
    _write_yaml(root / "catalog" / "v3" / "index.yaml", index)
    try:
        yield temporary, root
    finally:
        temporary.cleanup()


def _compiler():
    from selfworkflow.v3.catalog import CatalogError, compile_catalog

    return CatalogError, compile_catalog


class V3CatalogCompilerTests(unittest.TestCase):
    def test_v3_catalog_compiler_module_exists(self):
        spec = importlib.util.find_spec("selfworkflow.v3.catalog")
        self.assertIsNotNone(spec, "v3-catalog-compiler-not-found")

    def test_yaml_read_is_bounded_and_rechecks_bytes_after_lstat(self):
        from selfworkflow.v3.catalog import CatalogError, _read_bytes

        limit = 8
        payload = b"x" * (limit + 2)
        read_sizes = []

        class TrackingStream(io.BytesIO):
            def read(self, size=-1):
                read_sizes.append(size)
                return super().read(size)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "changing.yaml"
            path.write_bytes(payload)
            metadata = SimpleNamespace(st_size=limit, st_file_attributes=0)
            with (
                patch.object(Path, "lstat", return_value=metadata),
                patch.object(Path, "open", return_value=TrackingStream(payload)),
                self.assertRaises(CatalogError) as raised,
            ):
                _read_bytes(path, limit)

        self.assertEqual(raised.exception.reason, "v3-yaml-resource-limit")
        self.assertEqual(read_sizes, [limit + 1])

    def test_public_api_compiles_a_v3_envelope(self):
        CatalogError, compile_catalog = _compiler()
        with _workspace() as (temporary, root):
            compiled = compile_catalog(root / "catalog" / "v3" / "index.yaml")
        self.assertIsInstance(compiled.document, dict)
        self.assertEqual(compiled.document["schemaVersion"], 3)
        self.assertEqual(compiled.document["catalogHash"], compiled.catalog_hash)
        self.assertEqual(json.loads(compiled.content), compiled.document)
        self.assertRegex(compiled.catalog_hash, r"^sha256:[0-9a-f]{64}$")

    def test_only_the_v3_index_path_is_accepted(self):
        CatalogError, compile_catalog = _compiler()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            v2 = root / "catalog" / "index.yaml"
            v2.parent.mkdir(parents=True)
            v2.write_text("schemaVersion: 2\n", encoding="utf-8")
            with self.assertRaises(CatalogError) as raised:
                compile_catalog(v2)
        self.assertEqual(raised.exception.reason, "v3-catalog-path-invalid")
        self.assertNotIn(str(root), str(raised.exception))

    def test_rejects_version_mixing_unknown_fields_and_duplicate_keys(self):
        CatalogError, compile_catalog = _compiler()
        with _workspace() as (temporary, root):
            index = root / "catalog" / "v3" / "index.yaml"
            index.write_text("schemaVersion: 2\ndomains: []\nmodules: []\n", encoding="utf-8")
            with self.assertRaises(CatalogError) as version_error:
                compile_catalog(index)
            self.assertEqual(version_error.exception.reason, "v3-catalog-version-mismatch")
            index.write_text("schemaVersion: 3\ndomains: []\nmodules: []\nextra: true\n", encoding="utf-8")
            with self.assertRaises(CatalogError) as field_error:
                compile_catalog(index)
            self.assertEqual(field_error.exception.reason, "v3-catalog-unknown-field")
            index.write_text("schemaVersion: 3\nschemaVersion: 3\ndomains: []\nmodules: []\n", encoding="utf-8")
            with self.assertRaises(CatalogError) as duplicate_error:
                compile_catalog(index)
            self.assertEqual(duplicate_error.exception.reason, "v3-yaml-duplicate-key")

    def test_rejects_non_utf8_multidocument_and_alias_yaml(self):
        CatalogError, compile_catalog = _compiler()
        with _workspace() as (temporary, root):
            index = root / "catalog" / "v3" / "index.yaml"
            index.write_bytes(b"\xff\xfe")
            with self.assertRaises(CatalogError) as encoding_error:
                compile_catalog(index)
            self.assertEqual(encoding_error.exception.reason, "v3-yaml-invalid")
            index.write_text("schemaVersion: 3\ndomains: []\nmodules: []\n---\n{}\n", encoding="utf-8")
            with self.assertRaises(CatalogError) as document_error:
                compile_catalog(index)
            self.assertEqual(document_error.exception.reason, "v3-yaml-multiple-documents")
            index.write_text("schemaVersion: 3\ndomains: &x []\nmodules: *x\n", encoding="utf-8")
            with self.assertRaises(CatalogError) as alias_error:
                compile_catalog(index)
            self.assertEqual(alias_error.exception.reason, "v3-yaml-alias-forbidden")

    def test_rejects_traversal_and_reparse_source_refs(self):
        CatalogError, compile_catalog = _compiler()
        with _workspace() as (temporary, root):
            index = root / "catalog" / "v3" / "index.yaml"
            document = yaml.safe_load(index.read_text(encoding="utf-8"))
            document["modules"][0]["ref"] = "../outside.yaml"
            index.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaises(CatalogError) as traversal_error:
                compile_catalog(index)
            self.assertEqual(traversal_error.exception.reason, "v3-catalog-ref-invalid")
        with _workspace() as (temporary, root):
            index = root / "catalog" / "v3" / "index.yaml"
            link = root / "catalog" / "v3" / "modules" / "link.yaml"
            try:
                link.symlink_to(root / "catalog" / "v3" / "modules" / "review.yaml")
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error}")
            document = yaml.safe_load(index.read_text(encoding="utf-8"))
            document["modules"][0]["ref"] = "modules/link.yaml"
            document["modules"][0]["hash"] = _hash(link.resolve().read_bytes())
            index.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaises(CatalogError) as reparse_error:
                compile_catalog(index)
            self.assertEqual(reparse_error.exception.reason, "v3-catalog-ref-reparse")

    def test_rejects_duplicate_ids_unknown_domain_module_and_hash_drift(self):
        CatalogError, compile_catalog = _compiler()
        with _workspace(module_ids=("review", "review")) as (temporary, root):
            with self.assertRaises(CatalogError) as duplicate_error:
                compile_catalog(root / "catalog" / "v3" / "index.yaml")
            self.assertEqual(duplicate_error.exception.reason, "v3-catalog-duplicate-id")
        with _workspace() as (temporary, root):
            index = root / "catalog" / "v3" / "index.yaml"
            document = yaml.safe_load(index.read_text(encoding="utf-8"))
            domain = root / "catalog" / "v3" / "domains" / "foundation.yaml"
            domain.write_text("schemaVersion: 3\nid: foundation\nmodules: [missing]\n", encoding="utf-8")
            document["domains"][0]["hash"] = _hash(domain.read_bytes())
            index.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaises(CatalogError) as unknown_error:
                compile_catalog(index)
            self.assertEqual(unknown_error.exception.reason, "v3-domain-module-unknown")
        with _workspace() as (temporary, root):
            index = root / "catalog" / "v3" / "index.yaml"
            document = yaml.safe_load(index.read_text(encoding="utf-8"))
            document["modules"][0]["hash"] = "sha256:" + "0" * 64
            index.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaises(CatalogError) as drift_error:
                compile_catalog(index)
            self.assertEqual(drift_error.exception.reason, "v3-catalog-source-hash-mismatch")

    def test_rejects_dependency_cycles_and_asymmetric_conflicts(self):
        CatalogError, compile_catalog = _compiler()
        with _workspace(module_ids=("a", "b")) as (temporary, root):
            for module_id, dependency in (("a", "b"), ("b", "a")):
                path = root / "catalog" / "v3" / "modules" / f"{module_id}.yaml"
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
                document["dependencies"] = [dependency]
                path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            index = yaml.safe_load((root / "catalog" / "v3" / "index.yaml").read_text(encoding="utf-8"))
            for item in index["modules"]:
                item["hash"] = _hash((root / "catalog" / "v3" / item["ref"]).read_bytes())
            (root / "catalog" / "v3" / "index.yaml").write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
            with self.assertRaises(CatalogError) as cycle_error:
                compile_catalog(root / "catalog" / "v3" / "index.yaml")
            self.assertEqual(cycle_error.exception.reason, "v3-catalog-dependency-cycle")
        with _workspace(module_ids=("a", "b")) as (temporary, root):
            path = root / "catalog" / "v3" / "modules" / "a.yaml"
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            document["conflicts"] = ["b"]
            path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            index = yaml.safe_load((root / "catalog" / "v3" / "index.yaml").read_text(encoding="utf-8"))
            for item in index["modules"]:
                item["hash"] = _hash((root / "catalog" / "v3" / item["ref"]).read_bytes())
            (root / "catalog" / "v3" / "index.yaml").write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
            with self.assertRaises(CatalogError) as conflict_error:
                compile_catalog(root / "catalog" / "v3" / "index.yaml")
            self.assertEqual(conflict_error.exception.reason, "v3-catalog-conflict-asymmetric")

    def test_catalog_hash_and_sort_are_stable_under_input_order(self):
        CatalogError, compile_catalog = _compiler()
        with _workspace(module_ids=("zeta", "alpha"), module_order=["zeta", "alpha"], domain_order=["foundation"]) as (temporary, first_root):
            first = compile_catalog(first_root / "catalog" / "v3" / "index.yaml")
        with _workspace(module_ids=("zeta", "alpha"), module_order=["alpha", "zeta"], domain_order=["foundation"]) as (temporary, second_root):
            second = compile_catalog(second_root / "catalog" / "v3" / "index.yaml")
        self.assertEqual(first.catalog_hash, second.catalog_hash)
        self.assertEqual(first.content, second.content)
        self.assertEqual([item["id"] for item in first.document["catalog"]["modules"]], ["alpha", "zeta"])

    def test_checked_in_v3_catalog_is_the_small_supported_mainline(self):
        CatalogError, compile_catalog = _compiler()
        root = Path(__file__).resolve().parents[3]
        compiled = compile_catalog(root / "catalog" / "v3" / "index.yaml")
        modules = compiled.document["catalog"]["modules"]
        self.assertGreater(len(modules), 0)
        self.assertTrue(all(module["schemaVersion"] == 3 for module in modules))
        serialized = compiled.content.decode("utf-8")
        self.assertNotIn("provider", serialized.lower())
        self.assertNotIn("tea", serialized.lower())
        self.assertNotIn("c++", serialized.lower())


if __name__ == "__main__":
    unittest.main()
