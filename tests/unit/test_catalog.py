from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest import mock

import yaml
from jsonschema import Draft202012Validator


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "catalog"
STANDARD_CAPABILITIES = (
    "skill-discovery",
    "independent-context",
    "command-execution",
    "filesystem-read",
    "filesystem-write",
    "test-execution",
    "user-confirmation",
    "task-resume",
    "knowledge-read",
    "knowledge-write",
)
SECOND_SOURCE_BYTES = b"second controlled source\n"
SECOND_SOURCE_HASH = "sha256:" + hashlib.sha256(SECOND_SOURCE_BYTES).hexdigest()


def _open_object_schema_paths(schema):
    open_paths = []

    def visit(value, path):
        if isinstance(value, dict):
            if value.get("type") == "object":
                properties = value.get("properties")
                required = value.get("required")
                if (
                    value.get("additionalProperties") is not False
                    or not isinstance(properties, dict)
                    or not isinstance(required, list)
                    or len(required) != len(set(required))
                    or set(required) != set(properties)
                ):
                    open_paths.append(path)
            for key, item in value.items():
                visit(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(schema, "$")
    return tuple(open_paths)


@contextmanager
def _catalog_source(
    fixture_name="valid.yaml",
    *,
    mutate_domain=None,
    mutate_index=None,
    extra_sources=None,
):
    with tempfile.TemporaryDirectory(dir=REPOSITORY_ROOT) as temporary_directory:
        repository_root = Path(temporary_directory)
        source = repository_root / "catalog"
        domain_root = source / "domains"
        domain_root.mkdir(parents=True)
        shutil.copyfile(REPOSITORY_ROOT / "WORKFLOW.md", repository_root / "WORKFLOW.md")
        for relative_path, content in (extra_sources or {}).items():
            target = repository_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        workflow_root = repository_root / "workflow"
        workflow_root.mkdir()
        shutil.copyfile(
            REPOSITORY_ROOT / "workflow" / "lifecycle.yaml",
            workflow_root / "lifecycle.yaml",
        )
        shutil.copyfile(
            REPOSITORY_ROOT / "workflow" / "protected-rules.yaml",
            workflow_root / "protected-rules.yaml",
        )
        schema_root = repository_root / "schemas"
        schema_root.mkdir()
        shutil.copyfile(
            REPOSITORY_ROOT / "schemas" / "catalog.schema.json",
            schema_root / "catalog.schema.json",
        )
        shutil.copyfile(
            REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json",
            schema_root / "lifecycle.schema.json",
        )
        shutil.copyfile(
            REPOSITORY_ROOT / "schemas" / "protected-rules.schema.json",
            schema_root / "protected-rules.schema.json",
        )
        subprocess.run(
            ["git", "init", "-q"],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "add",
                "WORKFLOW.md",
                "workflow",
                "schemas",
                *sorted((extra_sources or {}).keys()),
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=SelfWorkFlow Tests",
                "-c",
                "user.email=selfworkflow-tests@example.invalid",
                "commit",
                "-q",
                "-m",
                "fixture sources",
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        source_revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        domain_document = yaml.safe_load(
            (FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8")
        )
        workflow_hash = "sha256:" + hashlib.sha256(
            (repository_root / "WORKFLOW.md").read_bytes()
        ).hexdigest()
        for entry in domain_document["entries"]:
            if "revision" in entry["source"]:
                entry["source"]["revision"] = f"git:{source_revision}"
            if entry["source"].get("path") == "WORKFLOW.md":
                entry["source"]["contentHash"] = workflow_hash
        if mutate_domain is not None:
            mutate_domain(domain_document)
        (domain_root / "fixture.yaml").write_text(
            yaml.safe_dump(domain_document, sort_keys=False),
            encoding="utf-8",
        )
        index_document = {
            "schemaVersion": 1,
            "domains": ["domains/fixture.yaml"],
            "standardCapabilities": list(STANDARD_CAPABILITIES),
        }
        if mutate_index is not None:
            mutate_index(index_document)
        (source / "index.yaml").write_text(
            yaml.safe_dump(
                index_document,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        yield source


class CatalogPublicApiTests(unittest.TestCase):
    def test_catalog_compiler_has_public_imports(self):
        from selfworkflow.catalog import CatalogError, CompiledCatalog, compile_catalog

        self.assertTrue(issubclass(CatalogError, ValueError))
        self.assertTrue(callable(compile_catalog))
        self.assertTrue(hasattr(CompiledCatalog, "catalog_hash"))

    def test_hash_bound_text_sources_are_forced_to_lf_in_fresh_checkouts(self):
        source_paths = (
            "WORKFLOW.md",
            "workflow/lifecycle.yaml",
            "workflow/protected-rules.yaml",
            "workflow/evidence.yaml",
        )
        for source_path in source_paths:
            result = subprocess.run(
                ["git", "check-attr", "eol", "--", source_path],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.stdout.strip(), f"{source_path}: eol: lf")


class CatalogCliTests(unittest.TestCase):
    def test_cli_compiles_twice_atomically_with_relative_and_absolute_paths(self):
        with tempfile.TemporaryDirectory(dir=REPOSITORY_ROOT) as temporary_directory:
            output = Path(temporary_directory) / "missing-parent" / "catalog.json"
            relative_output = output.relative_to(REPOSITORY_ROOT)
            base_command = [
                sys.executable,
                "-m",
                "selfworkflow.cli",
                "catalog",
                "compile",
            ]
            first = subprocess.run(
                base_command
                + ["--source", "catalog", "--output", str(relative_output)],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            first_bytes = output.read_bytes()
            second = subprocess.run(
                base_command
                + [
                    "--source",
                    str(REPOSITORY_ROOT / "catalog"),
                    "--output",
                    str(output),
                ],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(output.read_bytes(), first_bytes)
            self.assertRegex(first.stdout, r"^sha256:[0-9a-f]{64}\n$")
            self.assertEqual(second.stdout, first.stdout)
            self.assertEqual(first.stderr, "")
            self.assertEqual(second.stderr, "")
            failed = subprocess.run(
                base_command
                + [
                    "--source",
                    "secret-missing-catalog",
                    "--output",
                    str(output),
                ],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(output.read_bytes(), first_bytes)
            self.assertNotIn("secret-missing-catalog", failed.stderr)
            never_created = Path(temporary_directory) / "never-created" / "catalog.json"
            failed_new = subprocess.run(
                base_command
                + [
                    "--source",
                    "secret-missing-catalog",
                    "--output",
                    str(never_created),
                ],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed_new.returncode, 0)
            self.assertFalse(never_created.parent.exists())

    def test_cli_rejects_reparse_output_parent_even_when_target_is_inside_repo(self):
        with tempfile.TemporaryDirectory(dir=REPOSITORY_ROOT) as temporary_directory:
            temporary_root = Path(temporary_directory)
            real_parent = temporary_root / "real-parent"
            real_parent.mkdir()
            linked_parent = temporary_root / "linked-parent"
            try:
                os.symlink(real_parent.name, linked_parent, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error.winerror}")
            output = linked_parent / "catalog.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "selfworkflow.cli",
                    "catalog",
                    "compile",
                    "--source",
                    "catalog",
                    "--output",
                    str(output),
                ],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "SelfWorkFlow: catalog-compile-failed\n")
            self.assertFalse((real_parent / "catalog.json").exists())

    def test_cli_rejects_output_inside_source_or_outside_repository(self):
        with _catalog_source() as source:
            outside = source.parent.parent / f"{source.parent.name}-outside.json"
            outputs = (source / "compiled.json", outside)
            try:
                for output in outputs:
                    with self.subTest(output_kind="inside" if source in output.parents else "outside"):
                        result = subprocess.run(
                            [
                                sys.executable,
                                "-m",
                                "selfworkflow.cli",
                                "catalog",
                                "compile",
                                "--source",
                                str(source),
                                "--output",
                                str(output),
                            ],
                            cwd=REPOSITORY_ROOT,
                            check=False,
                            capture_output=True,
                            text=True,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(
                            result.stderr,
                            "SelfWorkFlow: catalog-compile-failed\n",
                        )
                        self.assertFalse(output.exists())
            finally:
                outside.unlink(missing_ok=True)


class CatalogCompilationTests(unittest.TestCase):
    def test_checked_in_v2_catalog_registers_unique_pipeline_modules(self):
        from selfworkflow.catalog import compile_catalog

        envelope = json.loads(compile_catalog(REPOSITORY_ROOT / "catalog").content)
        self.assertEqual(envelope["schemaVersion"], 2)
        modules = envelope["catalog"]["modules"]
        self.assertEqual(len(modules), len({module["id"] for module in modules}))
        self.assertTrue(all(module["contractVersion"] == 2 for module in modules))
        self.assertTrue(all(set(module["supportEvidence"]) == {
            "sourceIntegrity", "adapterSupport", "runtimeCapability", "behaviorEvidence"
        } for module in modules))
        knowledge = next(module for module in modules if module["id"] == "knowledge-update")
        self.assertEqual(knowledge["activation"], "explicit")
        self.assertEqual(knowledge["supportEvidence"]["adapterSupport"], "unverified")

    def test_checked_in_three_domain_catalog_compiles_from_real_sources(self):
        from selfworkflow.catalog import compile_catalog

        compiled = compile_catalog(REPOSITORY_ROOT / "catalog")
        envelope = json.loads(compiled.content)
        catalog = envelope["catalog"]
        self.assertEqual(
            catalog["domains"],
            ["code-quality", "knowledge", "workflow"],
        )
        self.assertEqual(
            [entry["id"] for entry in catalog["entries"]],
            [
                "code-quality",
                "code-quality-verification-contract",
                "grill-me",
                "knowledge-on-demand-loading",
                "workflow-core",
                "workflow-protected-rules",
                "workflow-quality",
            ],
        )
        for entry in catalog["entries"]:
            source = entry["source"]
            source_path = REPOSITORY_ROOT / source["path"]
            self.assertTrue(source_path.is_file())
            self.assertEqual(
                source["contentHash"],
                "sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest(),
            )
            if source["kind"] == "planned":
                self.assertEqual(entry["supportStatus"], "unverified")
        self.assertNotIn(str(REPOSITORY_ROOT), compiled.content.decode("utf-8"))
        for entry in catalog["entries"]:
            self.assertEqual(
                set(entry["selectors"]),
                {"fileExtensions", "operationTypes", "semanticTerms"},
            )
            self.assertEqual(
                set(entry["mandatoryWhen"]),
                {"match", "scopes", "fileExtensions", "operationTypes"},
            )

    def test_typed_selectors_and_conditional_mandatory_are_required_and_closed(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def remove_selectors(document):
            del document["entries"][0]["selectors"]

        with _catalog_source(mutate_domain=remove_selectors) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("catalog-structure-invalid",))

        def open_mandatory_when(document):
            document["entries"][0]["mandatoryWhen"]["unexpected"] = True

        with _catalog_source(mutate_domain=open_mandatory_when) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("catalog-structure-invalid",))

    def test_revision_must_exist_and_bind_the_source_bytes(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def nonexistent_revision(document):
            document["entries"][0]["source"]["revision"] = "git:" + "0" * 40

        with _catalog_source(mutate_domain=nonexistent_revision) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("source-revision-invalid",))

        with _catalog_source() as source:
            source_file = source.parent / "WORKFLOW.md"
            source_file.write_bytes(source_file.read_bytes() + b"changed after revision\n")
            domain_path = source / "domains" / "fixture.yaml"
            document = yaml.safe_load(domain_path.read_text(encoding="utf-8"))
            document["entries"][0]["source"]["contentHash"] = (
                "sha256:" + hashlib.sha256(source_file.read_bytes()).hexdigest()
            )
            domain_path.write_text(
                yaml.safe_dump(document, sort_keys=False),
                encoding="utf-8",
            )
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("source-revision-mismatch",))

    def test_conflicts_must_resolve_and_mandatory_conflicts_are_undirected(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def dangling_conflict(document):
            document["entries"][0]["conflicts"] = ["missing-entry"]

        with _catalog_source(mutate_domain=dangling_conflict) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("dangling-conflict",))

        def one_way_mandatory_conflict(document):
            first = document["entries"][0]
            first["mandatory"] = True
            first["conflicts"] = ["mandatory-b"]
            second = copy.deepcopy(first)
            second["id"] = "mandatory-b"
            second["displayName"] = "Mandatory B"
            second["conflicts"] = []
            second["aliases"] = []
            document["entries"].append(second)

        with _catalog_source(mutate_domain=one_way_mandatory_conflict) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("mandatory-conflict",))

    def test_catalog_schema_is_draft_2020_12_and_every_object_is_closed(self):
        from selfworkflow.catalog import compile_catalog

        schema = json.loads(
            (REPOSITORY_ROOT / "schemas" / "catalog.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        self.assertEqual(_open_object_schema_paths(schema), ())
        with _catalog_source() as source:
            envelope = json.loads(compile_catalog(source).content)
        Draft202012Validator(schema).validate(envelope)

    def test_index_domain_entry_and_source_objects_are_schema_closed(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        cases = (
            (None, lambda index: index.update({"extra": True}), "catalog-structure-invalid"),
            (lambda document: document.update({"extra": True}), None, "catalog-structure-invalid"),
            (
                lambda document: document["entries"][0].update({"extra": True}),
                None,
                "catalog-structure-invalid",
            ),
            (
                lambda document: document["entries"][0]["source"].update(
                    {"extra": True}
                ),
                None,
                "source-invalid",
            ),
            (
                lambda document: document["entries"][0].pop("triggers"),
                None,
                "catalog-structure-invalid",
            ),
        )
        for mutate_domain, mutate_index, expected_error in cases:
            with self.subTest(
                domain=getattr(mutate_domain, "__name__", None),
                index=getattr(mutate_index, "__name__", None),
            ):
                with _catalog_source(
                    mutate_domain=mutate_domain,
                    mutate_index=mutate_index,
                ) as source:
                    with self.assertRaises(CatalogError) as caught:
                        compile_catalog(source)
                self.assertEqual(caught.exception.errors, (expected_error,))

    def test_duplicate_yaml_keys_are_rejected(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            index_path = source / "index.yaml"
            index_path.write_text(
                index_path.read_text(encoding="utf-8").replace(
                    "schemaVersion: 1\n",
                    "schemaVersion: 1\nschemaVersion: 1\n",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("duplicate-key",))

    def test_duplicate_json_keys_in_catalog_schema_are_rejected(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            schema_path = source.parent / "schemas" / "catalog.schema.json"
            schema_path.write_text(
                schema_path.read_text(encoding="utf-8").replace(
                    '"title": "SelfWorkFlow compiled catalog envelope",',
                    '"title": "first",\n  "title": "second",',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("duplicate-key",))

    def test_catalog_schema_cannot_trigger_remote_reference_retrieval(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            schema_path = source.parent / "schemas" / "catalog.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["$defs"]["index"] = {
                "$ref": "https://example.invalid/catalog-index.json"
            }
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("network access attempted"),
            ) as urlopen:
                with self.assertRaises(CatalogError) as caught:
                    compile_catalog(source)
            urlopen.assert_not_called()
        self.assertEqual(caught.exception.errors, ("catalog-schema-invalid",))

    def test_yaml_alias_expansion_is_rejected(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            index_path = source / "index.yaml"
            index_path.write_text(
                "schemaVersion: 1\n"
                "domains: &domain_files\n"
                "  - domains/fixture.yaml\n"
                "standardCapabilities: *domain_files\n",
                encoding="utf-8",
            )
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("resource-limit",))

    def test_yaml_depth_budget_is_enforced_before_validation(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            (source / "index.yaml").write_text(
                '{"nested":' * 70 + "0" + "}" * 70,
                encoding="utf-8",
            )
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("resource-limit",))

    def test_yaml_node_budget_is_enforced_before_validation(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            (source / "index.yaml").write_text(
                json.dumps({"many": list(range(1100))}),
                encoding="utf-8",
            )
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("resource-limit",))

    def test_catalog_document_byte_budget_is_enforced_before_parsing(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            index_path = source / "index.yaml"
            index_path.write_text(
                index_path.read_text(encoding="utf-8")
                + "#"
                + "x" * (1024 * 1024),
                encoding="utf-8",
            )
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("resource-limit",))

    def test_logical_alias_count_budget_is_enforced(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def add_many_aliases(document):
            document["entries"][0]["aliases"] = [
                {"name": f"alias-{index:03d}", "target": "workflow-core"}
                for index in range(65)
            ]

        with _catalog_source(mutate_domain=add_many_aliases) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("resource-limit",))

    def test_domain_file_paths_reject_escape_and_non_yaml_files(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        for domain_path in ("../outside.yaml", "domains/fixture.json", "C:/secret.yaml"):
            def replace_domain(index, domain_path=domain_path):
                index["domains"] = [domain_path]

            with self.subTest(domain_path=domain_path):
                with _catalog_source(mutate_index=replace_domain) as source:
                    with self.assertRaises(CatalogError) as caught:
                        compile_catalog(source)
                self.assertEqual(caught.exception.errors, ("path-invalid",))

    def test_duplicate_domain_file_identity_is_rejected(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def duplicate_domain(index):
            index["domains"].append(index["domains"][0])

        with _catalog_source(mutate_index=duplicate_domain) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("duplicate-domain",))

    def test_distinct_files_cannot_declare_duplicate_domain_id(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            shutil.copyfile(
                source / "domains" / "fixture.yaml",
                source / "domains" / "second.yaml",
            )
            index_path = source / "index.yaml"
            index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
            index["domains"].append("domains/second.yaml")
            index_path.write_text(
                yaml.safe_dump(index, sort_keys=False),
                encoding="utf-8",
            )
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("duplicate-domain",))

    def test_valid_catalog_compiles_to_stable_canonical_envelope(self):
        from selfworkflow.catalog import compile_catalog

        with _catalog_source() as source:
            first = compile_catalog(source)
            second = compile_catalog(source)

        envelope = json.loads(first.content)
        self.assertEqual(set(envelope), {"schemaVersion", "catalog", "catalogHash"})
        payload_bytes = json.dumps(
            envelope["catalog"],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        expected_hash = "sha256:" + hashlib.sha256(payload_bytes).hexdigest()
        self.assertEqual(envelope["schemaVersion"], 1)
        self.assertEqual(envelope["catalog"]["domains"], ["workflow"])
        self.assertEqual(
            envelope["catalog"]["standardCapabilities"],
            list(STANDARD_CAPABILITIES),
        )
        self.assertEqual(
            envelope["catalog"]["entries"][0]["aliases"],
            [{"name": "core-workflow", "target": "workflow-core"}],
        )
        self.assertEqual(envelope["catalogHash"], expected_hash)
        self.assertEqual(first.catalog_hash, expected_hash)
        self.assertEqual(first.content, second.content)
        self.assertEqual(first.catalog_hash, second.catalog_hash)
        self.assertEqual(first.content[-1:], b"\n")
        self.assertFalse(first.content.endswith(b"\n\n"))
        self.assertEqual(
            first.content,
            json.dumps(
                envelope,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n",
        )

    def test_duplicate_stable_id_is_rejected_with_redacted_error(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source("duplicate-id.yaml") as source:
            sensitive_path = str(source)
            try:
                compile_catalog(source)
            except Exception as error:
                self.assertIsInstance(error, CatalogError)
                self.assertEqual(error.errors, ("duplicate-stable-id",))
                self.assertEqual(str(error), "catalog-validation-failed")
                self.assertIsNone(error.__cause__)
                self.assertIs(error.__suppress_context__, True)
                self.assertNotIn(
                    sensitive_path,
                    "".join(traceback.format_exception(error)),
                )
            else:
                self.fail("duplicate stable ID was accepted")

    def test_source_content_hash_is_required(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def remove_hash(document):
            del document["entries"][0]["source"]["contentHash"]

        with _catalog_source(mutate_domain=remove_hash) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("source-invalid",))

    def test_source_revision_is_required(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def remove_revision(document):
            del document["entries"][0]["source"]["revision"]

        with _catalog_source(mutate_domain=remove_revision) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("source-invalid",))

    def test_source_revision_and_content_hash_formats_are_strict(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        cases = (
            ("revision", "git:ABC"),
            ("revision", "branch:main"),
            ("contentHash", "sha256:ABC"),
            ("contentHash", "md5:" + "0" * 32),
        )
        for field, value in cases:
            def mutate(document, field=field, value=value):
                document["entries"][0]["source"][field] = value

            with self.subTest(field=field, value=value):
                with _catalog_source(mutate_domain=mutate) as source:
                    with self.assertRaises(CatalogError) as caught:
                        compile_catalog(source)
                self.assertEqual(caught.exception.errors, ("source-invalid",))

    def test_source_content_hash_must_match_existing_file_bytes(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def replace_hash(document):
            document["entries"][0]["source"]["contentHash"] = "sha256:" + "0" * 64

        with _catalog_source(mutate_domain=replace_hash) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("source-hash-mismatch",))

    def test_source_file_size_budget_precedes_hashing(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        oversized = b"x" * (8 * 1024 * 1024 + 1)
        oversized_hash = "sha256:" + hashlib.sha256(oversized).hexdigest()

        def use_oversized_source(document):
            document["entries"][0]["source"]["path"] = "OVERSIZED.md"
            document["entries"][0]["source"]["contentHash"] = oversized_hash

        with _catalog_source(
            mutate_domain=use_oversized_source,
            extra_sources={"OVERSIZED.md": oversized},
        ) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("resource-limit",))

    def test_source_path_cannot_escape_repository_root(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def escape_repository(document):
            document["entries"][0]["source"]["path"] = "../WORKFLOW.md"

        with _catalog_source(mutate_domain=escape_repository) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("path-invalid",))

    def test_domain_and_source_reparse_points_are_rejected(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        cases = ("domain", "source")
        for case in cases:
            with self.subTest(case=case):
                with _catalog_source() as source:
                    if case == "domain":
                        link = source / "domains" / "fixture.yaml"
                        target = source / "domains" / "real.yaml"
                    else:
                        link = source.parent / "WORKFLOW.md"
                        target = source.parent / "REAL-WORKFLOW.md"
                    link.replace(target)
                    try:
                        os.symlink(target.name, link)
                    except OSError as error:
                        self.skipTest(f"symbolic links unavailable: {error.winerror}")
                    with self.assertRaises(CatalogError) as caught:
                        compile_catalog(source)
                self.assertEqual(caught.exception.errors, ("path-reparse",))

    def test_catalog_control_document_reparse_point_is_rejected(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            index_link = source / "index.yaml"
            index_target = source / "real-index.yaml"
            index_link.replace(index_target)
            try:
                os.symlink(index_target.name, index_link)
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error.winerror}")
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("path-reparse",))

    def test_source_path_rejects_windows_unsafe_or_non_nfc_segments(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        paths = (
            "CON",
            "WORKFLOW.md.",
            "WORKFLOW.md:stream",
            "bad|name.md",
            "Cafe\u0301.md",
        )
        for unsafe_path in paths:
            def replace_path(document, unsafe_path=unsafe_path):
                document["entries"][0]["source"]["path"] = unsafe_path

            with self.subTest(path=unsafe_path):
                with _catalog_source(mutate_domain=replace_path) as source:
                    with self.assertRaises(CatalogError) as caught:
                        compile_catalog(source)
                self.assertEqual(caught.exception.errors, ("path-invalid",))

    def test_independent_semantic_errors_are_reported_in_fixed_order(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def add_independent_errors(document):
            document["entries"][0]["dependencies"] = ["missing-entry"]
            document["entries"][0]["requiredCapabilities"] = ["unknown-capability"]

        with _catalog_source(
            "duplicate-id.yaml",
            mutate_domain=add_independent_errors,
        ) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(
            caught.exception.errors,
            (
                "duplicate-stable-id",
                "dangling-dependency",
                "unknown-capability",
            ),
        )

    def test_public_input_failures_are_redacted_without_catching_base_exception(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        class HostilePath:
            def __fspath__(self):
                raise ValueError("TOP-SECRET-PATH")

        missing_name = "missing" + "-catalog"
        missing_source = REPOSITORY_ROOT / missing_name
        hostile_path = HostilePath()
        for call, sensitive in (
            (lambda: compile_catalog(missing_source), missing_name),
            (lambda: compile_catalog(hostile_path), "TOP-SECRET" + "-PATH"),
        ):
            with self.subTest(sensitive=sensitive):
                try:
                    call()
                except Exception as error:
                    self.assertIsInstance(error, CatalogError)
                    self.assertEqual(error.errors, ("catalog-input-invalid",))
                    self.assertEqual(str(error), "catalog-validation-failed")
                    self.assertIsNone(error.__cause__)
                    self.assertIs(error.__suppress_context__, True)
                    self.assertNotIn(
                        sensitive,
                        "".join(traceback.format_exception(error)),
                    )
                else:
                    self.fail("hostile public input was accepted")

        class InterruptingPath:
            def __fspath__(self):
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            compile_catalog(InterruptingPath())

    def test_planned_source_requires_unverified_support_status(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def make_planned(document):
            document["entries"][0]["source"]["kind"] = "planned"

        with _catalog_source(mutate_domain=make_planned) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(
            caught.exception.errors,
            ("planned-source-must-be-unverified",),
        )

        def make_unverified_planned(document):
            make_planned(document)
            document["entries"][0]["supportStatus"] = "unverified"

        with _catalog_source(mutate_domain=make_unverified_planned) as source:
            compiled = compile_catalog(source)
        self.assertTrue(compiled.content.endswith(b"\n"))

    def test_alias_target_must_resolve_to_stable_entry_id(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def point_to_unknown(document):
            document["entries"][0]["aliases"][0]["target"] = "missing-entry"

        with _catalog_source(mutate_domain=point_to_unknown) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("alias-target-unknown",))

    def test_alias_object_is_closed_and_uses_canonical_names(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def mutate_alias(document, alias):
            document["entries"][0]["aliases"][0] = alias

        cases = (
            {"name": "UpperCase", "target": "workflow-core"},
            {"name": "../escape", "target": "workflow-core"},
            {"name": "core-workflow"},
            {
                "name": "core-workflow",
                "target": "workflow-core",
                "statement": "free text",
            },
        )
        for alias in cases:
            with self.subTest(alias=alias):
                with _catalog_source(
                    mutate_domain=lambda document, alias=alias: mutate_alias(
                        document, alias
                    )
                ) as source:
                    with self.assertRaises(CatalogError) as caught:
                        compile_catalog(source)
                self.assertEqual(caught.exception.errors, ("alias-invalid",))

    def test_alias_names_cannot_collide_with_aliases_or_stable_ids(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def duplicate_alias(document):
            document["entries"][0]["aliases"].append(
                dict(document["entries"][0]["aliases"][0])
            )

        def collide_with_id(document):
            document["entries"][0]["aliases"][0]["name"] = "workflow-core"

        for mutate in (duplicate_alias, collide_with_id):
            with self.subTest(mutation=mutate.__name__):
                with _catalog_source(mutate_domain=mutate) as source:
                    with self.assertRaises(CatalogError) as caught:
                        compile_catalog(source)
                self.assertEqual(caught.exception.errors, ("alias-collision",))

    def test_alias_name_cannot_collide_with_display_name_identity(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def collide_with_display_name(document):
            document["entries"][0]["displayName"] = "CORE-WORKFLOW"

        with _catalog_source(mutate_domain=collide_with_display_name) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("alias-collision",))

    def test_same_display_name_cannot_map_to_different_content(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def add_conflicting_entry(document):
            other = copy.deepcopy(document["entries"][0])
            other["id"] = "other-entry"
            other["displayName"] = "CORE WORKFLOW"
            other["source"]["path"] = "SECOND.md"
            other["source"]["contentHash"] = SECOND_SOURCE_HASH
            other["aliases"] = []
            document["entries"].append(other)

        with _catalog_source(
            mutate_domain=add_conflicting_entry,
            extra_sources={"SECOND.md": SECOND_SOURCE_BYTES},
        ) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("content-identity-conflict",))

    def test_same_alias_cannot_map_to_different_content(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def add_conflicting_alias(document):
            other = copy.deepcopy(document["entries"][0])
            other["id"] = "other-entry"
            other["displayName"] = "Other entry"
            other["source"]["path"] = "SECOND.md"
            other["source"]["contentHash"] = SECOND_SOURCE_HASH
            other["aliases"][0]["target"] = "other-entry"
            document["entries"].append(other)

        with _catalog_source(
            mutate_domain=add_conflicting_alias,
            extra_sources={"SECOND.md": SECOND_SOURCE_BYTES},
        ) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("content-identity-conflict",))

    def test_dependency_must_resolve_to_stable_entry_id(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def add_dangling_dependency(document):
            document["entries"][0]["dependencies"] = ["missing-entry"]

        with _catalog_source(mutate_domain=add_dangling_dependency) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("dangling-dependency",))

    def test_dependency_cycle_is_rejected(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source("cycle.yaml") as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("dependency-cycle",))

    def test_mutually_conflicting_mandatory_entries_are_rejected(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source("conflict.yaml") as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("mandatory-conflict",))

    def test_required_capability_must_be_declared_by_lifecycle(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def add_unknown_capability(document):
            document["entries"][0]["requiredCapabilities"] = ["network-superpower"]

        with _catalog_source(mutate_domain=add_unknown_capability) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("unknown-capability",))

    def test_index_standard_capabilities_must_match_lifecycle_exactly(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def reorder_capabilities(index):
            index["standardCapabilities"] = list(
                reversed(index["standardCapabilities"])
            )

        with _catalog_source(mutate_index=reorder_capabilities) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(
            caught.exception.errors,
            ("standard-capability-mismatch",),
        )

    def test_lifecycle_is_schema_validated_before_capabilities_are_trusted(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        with _catalog_source() as source:
            lifecycle_path = source.parent / "workflow" / "lifecycle.yaml"
            lifecycle = yaml.safe_load(lifecycle_path.read_text(encoding="utf-8"))
            del lifecycle["derivedVerification"]
            lifecycle_path.write_text(
                yaml.safe_dump(lifecycle, sort_keys=False),
                encoding="utf-8",
            )
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("lifecycle-invalid",))

    def test_ordinary_skill_cannot_override_protected_rule_id(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        def add_override(document):
            document["entries"][0]["protectedRuleOperations"] = [
                {
                    "operation": "add-requirement",
                    "id": "no-silent-degradation",
                    "constraint": {
                        "kind": "verification-status",
                        "target": "tests",
                        "mode": "equals",
                        "value": "passed",
                    },
                }
            ]

        with _catalog_source(mutate_domain=add_override) as source:
            with self.assertRaises(CatalogError) as caught:
                compile_catalog(source)
        self.assertEqual(caught.exception.errors, ("protected-rule-override",))

    def test_protected_rule_operations_use_closed_task3_contract(self):
        from selfworkflow.catalog import CatalogError, compile_catalog

        valid = {
            "operation": "add-requirement",
            "id": "catalog-tests",
            "constraint": {
                "kind": "verification-status",
                "target": "catalog-tests",
                "mode": "equals",
                "value": "passed",
            },
        }
        invalid_operations = []
        for mutate in (
            lambda operation: operation.update({"operation": "replace"}),
            lambda operation: operation.update({"statement": "free text"}),
            lambda operation: operation["constraint"].update(
                {"kind": "disable-gate"}
            ),
            lambda operation: operation["constraint"].update({"value": "skip"}),
        ):
            operation = copy.deepcopy(valid)
            mutate(operation)
            invalid_operations.append(operation)

        for operation in invalid_operations:
            def set_operation(document, operation=operation):
                document["entries"][0]["protectedRuleOperations"] = [operation]

            with self.subTest(operation=operation):
                with _catalog_source(mutate_domain=set_operation) as source:
                    with self.assertRaises(CatalogError) as caught:
                        compile_catalog(source)
                self.assertEqual(
                    caught.exception.errors,
                    ("protected-rule-operation-invalid",),
                )

        def set_valid_operation(document):
            document["entries"][0]["protectedRuleOperations"] = [valid]

        with _catalog_source(mutate_domain=set_valid_operation) as source:
            self.assertTrue(compile_catalog(source).content)


if __name__ == "__main__":
    unittest.main()
