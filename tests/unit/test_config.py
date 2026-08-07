import copy
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib
import traceback
import unittest
from unittest import mock

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_KNOWN_ADAPTER_IDENTIFIERS = {
    "anthropic": (("anthropic",),),
    "claude": (("claude",),),
    "codex": (("codex",),),
    "copilot": (("copilot",), ("co", "pilot")),
    "cursor": (("cursor",),),
    "gemini": (("gemini",),),
    "microsoft": (("microsoft",),),
    "openai": (("openai",), ("open", "ai")),
    "opencode": (("opencode",), ("open", "code")),
}
_ADAPTER_SUFFIXES = {"adapter", "client", "provider"}


def _find_known_adapter_identifiers(value):
    found = set()

    def identifier_parts(text):
        separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
        separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", separated)
        return tuple(re.findall(r"[A-Za-z0-9]+", separated.casefold()))

    def scan_text(text):
        parts = identifier_parts(text)
        candidates = {parts}
        if parts and parts[-1] in _ADAPTER_SUFFIXES:
            candidates.add(parts[:-1])
        for name, aliases in _KNOWN_ADAPTER_IDENTIFIERS.items():
            bounded = re.search(
                rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])",
                text,
                flags=re.IGNORECASE,
            )
            if bounded or any(alias in candidates for alias in aliases):
                found.add(name)

    def visit(node):
        if isinstance(node, dict):
            for key, nested_value in node.items():
                visit(key)
                visit(nested_value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                visit(item)
        elif isinstance(node, str):
            scan_text(node)

    visit(value)
    return tuple(sorted(found))


def _open_object_schema_paths(value):
    open_paths = []

    def visit(node, path):
        if isinstance(node, dict):
            if node.get("type") == "object":
                required = node.get("required")
                properties = node.get("properties")
                required_is_exact = (
                    isinstance(required, list)
                    and all(isinstance(name, str) for name in required)
                    and len(required) == len(set(required))
                    and isinstance(properties, dict)
                    and set(required) == set(properties)
                )
                if (
                    node.get("additionalProperties") is not False
                    or not required_is_exact
                ):
                    open_paths.append(path)
            for key, nested_value in node.items():
                visit(nested_value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, f"{path}[{index}]")

    visit(value, "$")
    return tuple(open_paths)


class ConfigLoadingTests(unittest.TestCase):
    def test_upgrade_only_config_matches_production_user_override_behavior(self):
        from selfworkflow.classifier import classify_task
        from selfworkflow.config import load_config

        policies = load_config(
            REPOSITORY_ROOT / "workflow" / "policies.yaml",
            REPOSITORY_ROOT / "schemas" / "policies.schema.json",
        )
        self.assertEqual(
            policies["upgrades"]["user"],
            {"mayIncrease": True, "mayDecrease": False},
        )

        classification = classify_task(
            "C3",
            "R3",
            global_minimum_complexity="C1",
            global_minimum_risk="R1",
            user_complexity="C2",
            user_risk="R2",
        )
        self.assertEqual(
            (classification.complexity.value, classification.risk.value),
            ("C3", "R3"),
        )
        self.assertEqual(
            classification.reasons,
            (
                "user complexity C2 rejected downgrade from C3",
                "user risk R2 rejected downgrade from R3",
            ),
        )

    def test_project_and_wheel_metadata_declare_locked_runtime_dependencies(self):
        import setuptools.build_meta

        expected = ("PyYAML==6.0.3", "jsonschema==4.26.0")
        project = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(tuple(project["project"]["dependencies"]), expected)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            project_root = temporary_root / "project"
            metadata_root = temporary_root / "metadata"
            project_root.mkdir()
            metadata_root.mkdir()
            shutil.copy2(REPOSITORY_ROOT / "pyproject.toml", project_root)
            shutil.copy2(REPOSITORY_ROOT / "README.md", project_root)
            shutil.copytree(REPOSITORY_ROOT / "src", project_root / "src")

            original_directory = Path.cwd()
            try:
                os.chdir(project_root)
                metadata_name = (
                    setuptools.build_meta.prepare_metadata_for_build_wheel(
                        str(metadata_root)
                    )
                )
            finally:
                os.chdir(original_directory)

            distribution = metadata.Distribution.at(
                metadata_root / metadata_name
            )
            declared = tuple(distribution.metadata.get_all("Requires-Dist") or ())

        self.assertEqual(declared, expected)

    def test_yaml_parser_resource_exception_is_redacted(self):
        import selfworkflow.config as config_module

        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            document_path.write_text("safe: value\n", encoding="utf-8")
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            with mock.patch.object(
                config_module._StrictSafeLoader,
                "compose_node",
                side_effect=ValueError("TOP-SECRET-RESOURCE"),
            ):
                caught_error = None
                try:
                    config_module.load_config(document_path, schema_path)
                except Exception as error:
                    caught_error = error
                else:
                    self.fail("parser resource exception was accepted")

        self.assertIsInstance(caught_error, config_module.ConfigError)
        self.assertEqual(caught_error.code, "document-invalid")
        self.assertIsNone(caught_error.__cause__)
        self.assertIs(caught_error.__suppress_context__, True)
        rendered = "".join(traceback.format_exception(caught_error))
        self.assertNotIn("TOP-SECRET-RESOURCE", str(caught_error))
        self.assertNotIn("TOP-SECRET-RESOURCE", rendered)

    def test_yaml_compose_node_count_has_documented_boundary(self):
        import selfworkflow.config as config_module

        expected_limit = 1024
        configured_limit = getattr(
            config_module,
            "MAX_YAML_NODES",
            expected_limit,
        )
        self.assertEqual(configured_limit, expected_limit)
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema"}

        def sequence_with_total_nodes(total_nodes, final_value="safe"):
            scalar_count = total_nodes - 1
            values = ["safe"] * scalar_count
            values[-1] = final_value
            return "".join(f"- {value}\n" for value in values)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            document_path.write_text(
                sequence_with_total_nodes(expected_limit),
                encoding="utf-8",
            )
            config_module.load_config(document_path, schema_path)

            document_path.write_text(
                sequence_with_total_nodes(
                    expected_limit + 1,
                    "TOP-SECRET-NODE",
                ),
                encoding="utf-8",
            )
            caught_error = None
            try:
                config_module.load_config(document_path, schema_path)
            except Exception as error:
                caught_error = error
            else:
                self.fail("over-node-count YAML was accepted")

        self.assertIsInstance(caught_error, config_module.ConfigError)
        self.assertEqual(caught_error.code, "document-invalid")
        self.assertIsNone(caught_error.__cause__)
        self.assertIs(caught_error.__suppress_context__, True)
        rendered = "".join(traceback.format_exception(caught_error))
        self.assertNotIn("TOP-SECRET-NODE", str(caught_error))
        self.assertNotIn("TOP-SECRET-NODE", rendered)

    def test_yaml_compose_depth_has_documented_boundary(self):
        import selfworkflow.config as config_module

        expected_limit = 64
        configured_limit = getattr(
            config_module,
            "MAX_YAML_DEPTH",
            expected_limit,
        )
        self.assertEqual(configured_limit, expected_limit)
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema"}

        def nested_sequence(depth, value):
            return "- " * (depth - 1) + value + "\n"

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            document_path.write_text(
                nested_sequence(expected_limit, "safe"),
                encoding="utf-8",
            )
            config_module.load_config(document_path, schema_path)

            for depth in (expected_limit + 1, 1500):
                with self.subTest(depth=depth):
                    document_path.write_text(
                        nested_sequence(depth, "TOP-SECRET-DEPTH"),
                        encoding="utf-8",
                    )
                    caught_error = None
                    try:
                        config_module.load_config(document_path, schema_path)
                    except Exception as error:
                        caught_error = error
                    else:
                        self.fail("over-depth YAML was accepted")

                    self.assertIsInstance(caught_error, config_module.ConfigError)
                    self.assertEqual(caught_error.code, "document-invalid")
                    self.assertIsNone(caught_error.__cause__)
                    self.assertIs(caught_error.__suppress_context__, True)
                    rendered = "".join(traceback.format_exception(caught_error))
                    self.assertNotIn("TOP-SECRET-DEPTH", str(caught_error))
                    self.assertNotIn("TOP-SECRET-DEPTH", rendered)

    def test_yaml_aliases_are_rejected_before_construction(self):
        import selfworkflow.config as config_module

        documents = (
            (
                "simple",
                "source: &TOP-SECRET-ANCHOR [safe]\n"
                "copy: *TOP-SECRET-ANCHOR\n",
            ),
            (
                "dag",
                "a: &a [safe, safe]\n"
                "b: &b [*a, *a]\n"
                "c: &c [*b, *b]\n"
                "d: [*c, *c]\n",
            ),
        )
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            for shape, document_text in documents:
                with self.subTest(shape=shape):
                    document_path.write_text(document_text, encoding="utf-8")
                    caught_error = None
                    try:
                        config_module.load_config(document_path, schema_path)
                    except Exception as error:
                        caught_error = error
                    else:
                        self.fail("YAML alias was accepted")

                    self.assertIsInstance(caught_error, config_module.ConfigError)
                    self.assertEqual(caught_error.code, "document-invalid")
                    self.assertIsNone(caught_error.__cause__)
                    self.assertIs(caught_error.__suppress_context__, True)
                    rendered = "".join(traceback.format_exception(caught_error))
                    self.assertNotIn("TOP-SECRET-ANCHOR", str(caught_error))
                    self.assertNotIn("TOP-SECRET-ANCHOR", rendered)

    def test_yaml_duplicate_keys_are_rejected_recursively_and_redacted(self):
        import selfworkflow.config as config_module

        documents = (
            ("top-level", "value: first\nvalue: second\n"),
            (
                "nested",
                "outer:\n"
                "  TOP-SECRET-DUPLICATE: first\n"
                "  TOP-SECRET-DUPLICATE: second\n",
            ),
        )
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            for level, document_text in documents:
                with self.subTest(level=level):
                    document_path.write_text(document_text, encoding="utf-8")
                    caught_error = None
                    try:
                        config_module.load_config(document_path, schema_path)
                    except Exception as error:
                        caught_error = error
                    else:
                        self.fail("duplicate YAML key was accepted")

                    self.assertIsInstance(caught_error, config_module.ConfigError)
                    self.assertEqual(caught_error.code, "document-invalid")
                    self.assertIsNone(caught_error.__cause__)
                    self.assertIs(caught_error.__suppress_context__, True)
                    rendered = "".join(traceback.format_exception(caught_error))
                    self.assertNotIn("TOP-SECRET-DUPLICATE", str(caught_error))
                    self.assertNotIn("TOP-SECRET-DUPLICATE", rendered)

    def test_schema_duplicate_keys_are_rejected_recursively_and_redacted(self):
        import selfworkflow.config as config_module

        schemas = (
            (
                "top-level",
                '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
                '"type":"object","type":"array"}',
            ),
            (
                "nested",
                '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
                '"properties":{"TOP-SECRET-DUPLICATE":{},'
                '"TOP-SECRET-DUPLICATE":{}}}',
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            document_path.write_text("{}\n", encoding="utf-8")

            for level, schema_text in schemas:
                with self.subTest(level=level):
                    schema_path.write_text(schema_text, encoding="utf-8")
                    caught_error = None
                    try:
                        config_module.load_config(document_path, schema_path)
                    except Exception as error:
                        caught_error = error
                    else:
                        self.fail("duplicate schema key was accepted")

                    self.assertIsInstance(caught_error, config_module.ConfigError)
                    self.assertEqual(caught_error.code, "schema-invalid")
                    self.assertIsNone(caught_error.__cause__)
                    self.assertIs(caught_error.__suppress_context__, True)
                    rendered = "".join(traceback.format_exception(caught_error))
                    self.assertNotIn("TOP-SECRET-DUPLICATE", str(caught_error))
                    self.assertNotIn("TOP-SECRET-DUPLICATE", rendered)

    def test_remote_schema_reference_is_rejected_without_retrieval(self):
        import selfworkflow.config as config_module

        secret_uri = "https://secret.invalid/TOP-SECRET-REF"
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": secret_uri,
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            document_path.write_text("value: safe\n", encoding="utf-8")
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            with mock.patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("network retrieval attempted"),
            ) as retrieve:
                caught_error = None
                try:
                    config_module.load_config(document_path, schema_path)
                except Exception as error:
                    caught_error = error
                else:
                    self.fail("remote schema reference was accepted")

        self.assertFalse(retrieve.called, "remote schema retrieval was attempted")
        error = caught_error
        self.assertIsInstance(error, config_module.ConfigError)
        self.assertEqual(error.code, "schema-reference-unavailable")
        self.assertIsNone(error.__cause__)
        self.assertIs(error.__suppress_context__, True)
        rendered = "".join(traceback.format_exception(error))
        self.assertNotIn(secret_uri, str(error))
        self.assertNotIn("secret.invalid", rendered)
        self.assertNotIn("TOP-SECRET-REF", rendered)

    def test_loads_lifecycle_from_explicit_document_and_schema_paths(self):
        try:
            from selfworkflow.config import load_config
        except ImportError:
            self.fail("load_config behavior is not implemented")

        config = load_config(
            REPOSITORY_ROOT / "workflow" / "lifecycle.yaml",
            REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json",
        )

        self.assertEqual(
            config["phases"],
            (
                "discovered",
                "capability-checked",
                "classified",
                "designed",
                "planned",
                "implemented",
                "reviewed",
                "verified",
                "completed",
            ),
        )

    def test_lifecycle_defines_orthogonal_statuses_and_standard_capabilities(self):
        from selfworkflow.config import load_config

        config = load_config(
            REPOSITORY_ROOT / "workflow" / "lifecycle.yaml",
            REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json",
        )

        self.assertEqual(
            config.get("executionStatuses"),
            ("active", "paused", "blocked", "failed", "completed"),
        )
        self.assertEqual(
            config.get("verificationStatuses"),
            ("not-applicable", "not-run", "partial", "passed", "failed"),
        )
        self.assertEqual(
            config.get("capabilities"),
            {
                "states": ("supported", "unsupported", "unverified"),
                "standardNames": (
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
                ),
            },
        )
        self.assertEqual(
            config.get("derivedVerification"),
            {"unverifiedFrom": ("not-run", "partial")},
        )

    def test_policies_define_classification_thresholds_and_upgrade_only_rules(self):
        from selfworkflow.config import load_config

        document_path = REPOSITORY_ROOT / "workflow" / "policies.yaml"
        schema_path = REPOSITORY_ROOT / "schemas" / "policies.schema.json"
        self.assertTrue(document_path.is_file(), "policies document is missing")
        self.assertTrue(schema_path.is_file(), "policies schema is missing")

        config = load_config(document_path, schema_path)

        self.assertEqual(tuple(config["classification"]["complexity"]), ("C0", "C1", "C2", "C3"))
        self.assertEqual(tuple(config["classification"]["risk"]), ("R0", "R1", "R2", "R3"))
        self.assertEqual(config["thresholds"]["requiresFullDesign"]["anyDimensionAtLeast"], 2)
        self.assertEqual(config["thresholds"]["suggestGrillMe"]["anyDimensionAtLeast"], 3)
        self.assertEqual(
            config["thresholds"]["suggestGrillMe"]["combinations"],
            ({"complexity": "C2", "risk": "R2"},),
        )
        self.assertEqual(config["upgrades"]["ambiguity"], {"increment": 1, "maximum": 3})
        self.assertFalse(config["upgrades"]["projectMinimum"]["mayDecreaseGlobalMinimum"])
        self.assertEqual(
            config["upgrades"]["user"],
            {"mayIncrease": True, "mayDecrease": False},
        )
        self.assertEqual(
            config["capabilityGate"]["pause"],
            {
                "status": "paused",
                "code": "required-capabilities-unavailable",
                "fields": (
                    "missingCapabilities",
                    "purposes",
                    "reasons",
                    "recommendations",
                    "oneTimeAlternatives",
                    "nonWaivableBoundaries",
                ),
                "oneTimeAlternatives": {
                    "requiresExplicitUserAuthorization": True,
                    "allowsManualVerification": True,
                    "allowsAutomaticDowngrade": False,
                },
                "nonWaivableBoundaries": (
                    "one-time alternatives require explicit user authorization",
                    "required capability cannot be treated as supported without evidence",
                ),
            },
        )

    def test_evidence_defines_required_fields_and_verification_outcomes(self):
        from selfworkflow.config import load_config

        document_path = REPOSITORY_ROOT / "workflow" / "evidence.yaml"
        schema_path = REPOSITORY_ROOT / "schemas" / "evidence.schema.json"
        self.assertTrue(document_path.is_file(), "evidence document is missing")
        self.assertTrue(schema_path.is_file(), "evidence schema is missing")

        config = load_config(document_path, schema_path)

        self.assertEqual(
            config["requiredFields"],
            (
                "classification",
                "capabilities",
                "selectedSkills",
                "acceptanceCriteria",
                "changes",
                "review",
                "verification",
                "skipped",
                "residualRisks",
            ),
        )
        self.assertEqual(config["verification"]["unverifiedFrom"], ("not-run", "partial"))
        self.assertEqual(
            config["verification"]["completionEligible"],
            ("passed", "not-applicable"),
        )

    def test_rejects_additional_properties_with_stable_error(self):
        import selfworkflow.config as config_module

        self.assertTrue(
            hasattr(config_module, "ConfigError"),
            "ConfigError behavior is not implemented",
        )
        source = yaml.safe_load(
            (REPOSITORY_ROOT / "workflow" / "lifecycle.yaml").read_text(
                encoding="utf-8"
            )
        )
        source["unexpected"] = "must-be-rejected"
        with tempfile.TemporaryDirectory() as temporary_directory:
            document_path = Path(temporary_directory) / "lifecycle.yaml"
            document_path.write_text(
                yaml.safe_dump(source, sort_keys=False),
                encoding="utf-8",
            )

            with self.assertRaises(config_module.ConfigError) as raised:
                config_module.load_config(
                    document_path,
                    REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json",
                )

        self.assertEqual(raised.exception.code, "configuration-invalid")
        self.assertEqual(str(raised.exception), "configuration-invalid")

    def test_heterogeneous_validation_errors_return_redacted_fixed_error(self):
        import selfworkflow.config as config_module

        secret = "TOP-SECRET-CONTROL"
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [False, {"required": [secret]}],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            document_path.write_text("{}\n", encoding="utf-8")
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            try:
                config_module.load_config(document_path, schema_path)
            except Exception as error:
                caught_error = error
            else:
                self.fail("invalid configuration was accepted")

        self.assertIsInstance(caught_error, config_module.ConfigError)
        self.assertEqual(caught_error.code, "configuration-invalid")
        self.assertEqual(str(caught_error), "configuration-invalid")
        self.assertIsNone(caught_error.__cause__)
        self.assertIs(caught_error.__suppress_context__, True)
        rendered = "".join(traceback.format_exception(caught_error))
        self.assertNotIn(secret, rendered)

    def test_rejects_missing_required_properties_with_stable_error(self):
        import selfworkflow.config as config_module

        source = yaml.safe_load(
            (REPOSITORY_ROOT / "workflow" / "lifecycle.yaml").read_text(
                encoding="utf-8"
            )
        )
        del source["schemaVersion"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            document_path = Path(temporary_directory) / "lifecycle.yaml"
            document_path.write_text(
                yaml.safe_dump(source, sort_keys=False),
                encoding="utf-8",
            )

            try:
                config_module.load_config(
                    document_path,
                    REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json",
                )
            except Exception as error:
                self.assertIsInstance(error, config_module.ConfigError)
                self.assertEqual(error.code, "configuration-invalid")
            else:
                self.fail("missing required property was accepted")

    def test_rejects_illegal_enumeration_with_stable_error(self):
        import selfworkflow.config as config_module

        source = yaml.safe_load(
            (REPOSITORY_ROOT / "workflow" / "lifecycle.yaml").read_text(
                encoding="utf-8"
            )
        )
        source["executionStatuses"][0] = "running"
        with tempfile.TemporaryDirectory() as temporary_directory:
            document_path = Path(temporary_directory) / "lifecycle.yaml"
            document_path.write_text(
                yaml.safe_dump(source, sort_keys=False),
                encoding="utf-8",
            )

            try:
                config_module.load_config(
                    document_path,
                    REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json",
                )
            except Exception as error:
                self.assertIsInstance(error, config_module.ConfigError)
                self.assertEqual(error.code, "configuration-invalid")
            else:
                self.fail("illegal enumeration was accepted")

    def test_parse_errors_are_deterministic_and_redacted(self):
        import selfworkflow.config as config_module

        errors = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            for secret in ("first-secret", "second-secret"):
                document_path = Path(temporary_directory) / f"{secret}.yaml"
                document_path.write_text(
                    f"schemaVersion: 1\nsecret: {secret}\nbroken: [",
                    encoding="utf-8",
                )
                try:
                    config_module.load_config(
                        document_path,
                        REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json",
                    )
                except Exception as error:
                    self.assertIsInstance(error, config_module.ConfigError)
                    errors.append(error)
                else:
                    self.fail("malformed YAML was accepted")

        self.assertEqual([error.code for error in errors], ["document-invalid"] * 2)
        self.assertEqual(str(errors[0]), str(errors[1]))
        self.assertNotIn("secret", str(errors[0]).lower())

    def test_document_read_errors_redact_the_explicit_path(self):
        import selfworkflow.config as config_module

        secret_path = REPOSITORY_ROOT / "missing-secret-document.yaml"
        try:
            config_module.load_config(
                secret_path,
                REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json",
            )
        except Exception as error:
            self.assertIsInstance(error, config_module.ConfigError)
            self.assertEqual(error.code, "document-read-failed")
            self.assertNotIn(str(secret_path), str(error))
        else:
            self.fail("missing document was accepted")

    def test_schema_read_errors_redact_the_explicit_path(self):
        import selfworkflow.config as config_module

        secret_path = REPOSITORY_ROOT / "missing-secret-schema.json"
        try:
            config_module.load_config(
                REPOSITORY_ROOT / "workflow" / "lifecycle.yaml",
                secret_path,
            )
        except Exception as error:
            self.assertIsInstance(error, config_module.ConfigError)
            self.assertEqual(error.code, "schema-read-failed")
            self.assertNotIn(str(secret_path), str(error))
        else:
            self.fail("missing schema was accepted")

    def test_schema_parse_errors_are_deterministic_and_redacted(self):
        import selfworkflow.config as config_module

        with tempfile.TemporaryDirectory() as temporary_directory:
            schema_path = Path(temporary_directory) / "secret-schema.json"
            schema_path.write_text('{"secret": "do-not-leak",', encoding="utf-8")
            try:
                config_module.load_config(
                    REPOSITORY_ROOT / "workflow" / "lifecycle.yaml",
                    schema_path,
                )
            except Exception as error:
                self.assertIsInstance(error, config_module.ConfigError)
                self.assertEqual(error.code, "schema-invalid")
                self.assertNotIn("do-not-leak", str(error))
            else:
                self.fail("malformed schema was accepted")

    def test_schema_json_rejects_nonfinite_numbers_before_validation(self):
        import selfworkflow.config as config_module

        secret = "TOP-SECRET-NUMERIC-SCHEMA"
        draft = "https://json-schema.org/draft/2020-12/schema"
        cases = tuple(
            (f"root-{label}", token, "null\n")
            for label, token in (
                ("nan", "NaN"),
                ("infinity", "Infinity"),
                ("negative-infinity", "-Infinity"),
                ("overflow", "1e999"),
            )
        ) + tuple(
            (f"nested-{label}", token, "score: 1\n")
            for label, token in (
                ("nan", "NaN"),
                ("infinity", "Infinity"),
                ("negative-infinity", "-Infinity"),
                ("overflow", "1e999"),
            )
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            for label, token, document_text in cases:
                with self.subTest(case=label):
                    if label.startswith("root-"):
                        schema_text = (
                            f'{{"$schema":"{draft}","title":"{secret}",'
                            f'"const":{token}}}'
                        )
                    else:
                        schema_text = (
                            f'{{"$schema":"{draft}","title":"{secret}",'
                            '"type":"object","properties":{"score":'
                            f'{{"type":"number","maximum":{token}}}}}}}'
                        )
                    document_path.write_text(document_text, encoding="utf-8")
                    schema_path.write_text(schema_text, encoding="utf-8")

                    try:
                        config_module.load_config(document_path, schema_path)
                    except Exception as error:
                        caught_error = error
                    else:
                        self.fail("non-finite schema number was accepted")

                    self.assertIsInstance(caught_error, config_module.ConfigError)
                    self.assertEqual(caught_error.code, "schema-invalid")
                    self.assertEqual(str(caught_error), "schema-invalid")
                    self.assertIsNone(caught_error.__cause__)
                    self.assertIs(caught_error.__suppress_context__, True)
                    rendered = "".join(traceback.format_exception(caught_error))
                    self.assertNotIn(secret, rendered)
                    self.assertNotIn(token, rendered)

    def test_deep_schema_json_recursion_is_redacted_as_schema_invalid(self):
        import selfworkflow.config as config_module

        secret = "TOP-SECRET-DEEP-SCHEMA"
        draft = "https://json-schema.org/draft/2020-12/schema"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            document_path.write_text("{}\n", encoding="utf-8")

            def assert_schema_invalid(label, schema_text):
                with self.subTest(case=label):
                    schema_path.write_text(schema_text, encoding="utf-8")
                    try:
                        config_module.load_config(document_path, schema_path)
                    except Exception as error:
                        caught_error = error
                    else:
                        self.fail("unsafe deep schema was accepted")

                    self.assertIsInstance(caught_error, config_module.ConfigError)
                    self.assertEqual(caught_error.code, "schema-invalid")
                    self.assertEqual(str(caught_error), "schema-invalid")
                    self.assertIsNone(caught_error.__cause__)
                    self.assertIs(caught_error.__suppress_context__, True)
                    rendered = "".join(traceback.format_exception(caught_error))
                    self.assertNotIn(secret, rendered)

            scan_depth = 998
            finite_nested = "[" * scan_depth + "0" + "]" * scan_depth
            schema_path.write_text(
                f'{{"$schema":"{draft}","title":"{secret}",'
                f'"x":{finite_nested}}}',
                encoding="utf-8",
            )
            self.assertEqual(
                config_module.load_config(document_path, schema_path),
                {},
            )

            overflow_nested = "[" * scan_depth + "1e999" + "]" * scan_depth
            assert_schema_invalid(
                "iterative-nonfinite-scan",
                f'{{"$schema":"{draft}","title":"{secret}",'
                f'"x":{overflow_nested}}}',
            )

            decode_depth = 20000
            decode_nested = "[" * decode_depth + "0" + "]" * decode_depth
            assert_schema_invalid(
                "json-decoder-recursion",
                f'{{"$schema":"{draft}","title":"{secret}",'
                f'"x":{decode_nested}}}',
            )

            check_depth = 200
            recursively_nested_schema = (
                '{"allOf":[' * check_depth
                + f'{{"title":"{secret}"}}'
                + "]}" * check_depth
            )
            assert_schema_invalid(
                "schema-check-recursion",
                recursively_nested_schema,
            )

    def test_invalid_draft_schema_is_rejected_with_stable_error(self):
        import selfworkflow.config as config_module

        invalid_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": 17,
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            schema_path = Path(temporary_directory) / "schema.json"
            schema_path.write_text(json.dumps(invalid_schema), encoding="utf-8")
            try:
                config_module.load_config(
                    REPOSITORY_ROOT / "workflow" / "lifecycle.yaml",
                    schema_path,
                )
            except Exception as error:
                self.assertIsInstance(error, config_module.ConfigError)
                self.assertEqual(error.code, "schema-invalid")
            else:
                self.fail("invalid Draft 2020-12 schema was accepted")

    def test_loaded_configuration_is_deeply_immutable_without_shared_references(self):
        from selfworkflow.config import load_config

        document_path = REPOSITORY_ROOT / "workflow" / "lifecycle.yaml"
        schema_path = REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json"
        first = load_config(document_path, schema_path)
        second = load_config(document_path, schema_path)

        self.assertIsNot(first, second)
        self.assertIsNot(first["capabilities"], second["capabilities"])
        with self.assertRaises(TypeError):
            first["phases"] = ()
        with self.assertRaises(TypeError):
            first["capabilities"]["states"] = ()
        with self.assertRaises(AttributeError):
            first["phases"].append("unexpected")

    def test_load_config_rejects_yaml_set_under_permissive_schema(self):
        import selfworkflow.config as config_module

        permissive_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema"
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / "document.yaml"
            schema_path = temporary_root / "schema.json"
            document_path.write_text(
                "values: !!set\n  ? first\n  ? second\n",
                encoding="utf-8",
            )
            schema_path.write_text(json.dumps(permissive_schema), encoding="utf-8")

            try:
                config_module.load_config(document_path, schema_path)
            except Exception as error:
                self.assertIsInstance(error, config_module.ConfigError)
                self.assertEqual(error.code, "document-data-invalid")
                self.assertEqual(str(error), "document-data-invalid")
            else:
                self.fail("non-JSON YAML set was accepted")

    def test_checked_in_yaml_keys_match_the_contract_exactly(self):
        documents = {
            name: yaml.safe_load(
                (REPOSITORY_ROOT / "workflow" / f"{name}.yaml").read_text(
                    encoding="utf-8"
                )
            )
            for name in ("lifecycle", "policies", "evidence")
        }
        lifecycle = documents["lifecycle"]
        policies = documents["policies"]
        evidence = documents["evidence"]

        self.assertEqual(
            set(lifecycle),
            {
                "schemaVersion",
                "phases",
                "executionStatuses",
                "verificationStatuses",
                "capabilities",
                "derivedVerification",
            },
        )
        self.assertEqual(set(lifecycle["capabilities"]), {"states", "standardNames"})
        self.assertEqual(set(lifecycle["derivedVerification"]), {"unverifiedFrom"})

        self.assertEqual(
            set(policies),
            {
                "schemaVersion",
                "classification",
                "globalMinimum",
                "thresholds",
                "upgrades",
                "capabilityGate",
            },
        )
        self.assertEqual(set(policies["classification"]), {"complexity", "risk"})
        self.assertEqual(
            set(policies["classification"]["complexity"]),
            {"C0", "C1", "C2", "C3"},
        )
        self.assertEqual(
            set(policies["classification"]["risk"]),
            {"R0", "R1", "R2", "R3"},
        )
        self.assertEqual(set(policies["globalMinimum"]), {"complexity", "risk"})
        self.assertEqual(
            set(policies["thresholds"]),
            {"requiresFullDesign", "suggestGrillMe"},
        )
        self.assertEqual(
            set(policies["thresholds"]["requiresFullDesign"]),
            {"anyDimensionAtLeast"},
        )
        self.assertEqual(
            set(policies["thresholds"]["suggestGrillMe"]),
            {"anyDimensionAtLeast", "combinations"},
        )
        self.assertEqual(
            set(policies["thresholds"]["suggestGrillMe"]["combinations"][0]),
            {"complexity", "risk"},
        )
        self.assertEqual(
            set(policies["upgrades"]),
            {"ambiguity", "projectMinimum", "user", "recordRejectedDowngrade"},
        )
        self.assertEqual(
            set(policies["upgrades"]["ambiguity"]),
            {"increment", "maximum"},
        )
        self.assertEqual(
            set(policies["upgrades"]["projectMinimum"]),
            {"mayIncreaseGlobalMinimum", "mayDecreaseGlobalMinimum"},
        )
        self.assertEqual(
            set(policies["upgrades"]["user"]),
            {"mayIncrease", "mayDecrease"},
        )
        self.assertEqual(
            set(policies["capabilityGate"]),
            {
                "acceptedStates",
                "pauseStates",
                "missingReportHandling",
                "ordering",
                "pause",
            },
        )
        self.assertEqual(
            set(policies["capabilityGate"]["pause"]),
            {
                "status",
                "code",
                "fields",
                "oneTimeAlternatives",
                "nonWaivableBoundaries",
            },
        )
        self.assertEqual(
            set(
                policies["capabilityGate"]["pause"]["oneTimeAlternatives"]
            ),
            {
                "requiresExplicitUserAuthorization",
                "allowsManualVerification",
                "allowsAutomaticDowngrade",
            },
        )

        self.assertEqual(
            set(evidence),
            {"schemaVersion", "requiredFields", "verification"},
        )
        self.assertEqual(
            set(evidence["verification"]),
            {"unverifiedFrom", "completionEligible"},
        )

    def test_workflow_sources_exclude_known_adapter_identifiers(self):
        scanner = globals().get("_find_known_adapter_identifiers")
        self.assertTrue(callable(scanner), "known adapter scanner is missing")

        loaded_sources = []
        for name in ("lifecycle", "policies", "evidence"):
            loaded_sources.append(
                yaml.safe_load(
                    (REPOSITORY_ROOT / "workflow" / f"{name}.yaml").read_text(
                        encoding="utf-8"
                    )
                )
            )
            loaded_sources.append(
                json.loads(
                    (REPOSITORY_ROOT / "schemas" / f"{name}.schema.json").read_text(
                        encoding="utf-8"
                    )
                )
            )

        for source in loaded_sources:
            self.assertEqual(scanner(source), ())

        detected = scanner(
            {
                "OpenAIAdapter": {
                    "provider": "CoPilot",
                    "AnthropicAdapter": "GeminiProvider",
                    "MicrosoftClient": True,
                },
                "runtime": ["Claude", "Cursor", "OpenCode", "Codex"],
            }
        )
        self.assertEqual(
            detected,
            (
                "anthropic",
                "claude",
                "codex",
                "copilot",
                "cursor",
                "gemini",
                "microsoft",
                "openai",
                "opencode",
            ),
        )
        self.assertEqual(scanner({"cursorPosition": 1}), ())

    def test_every_object_schema_node_rejects_additional_properties(self):
        checker = globals().get("_open_object_schema_paths")
        self.assertTrue(callable(checker), "object schema checker is missing")

        for name in ("lifecycle", "policies", "evidence"):
            schema = json.loads(
                (REPOSITORY_ROOT / "schemas" / f"{name}.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(checker(schema), ())

        loosened_fixture = {
            "type": "object",
            "additionalProperties": False,
            "required": ["nested"],
            "properties": {
                "nested": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": [],
                    "properties": {},
                }
            },
        }
        self.assertEqual(
            checker(loosened_fixture),
            ("$.properties.nested",),
        )

    def test_object_schema_required_and_properties_contract_is_closed(self):
        checker = _open_object_schema_paths
        lifecycle_schema = json.loads(
            (REPOSITORY_ROOT / "schemas" / "lifecycle.schema.json").read_text(
                encoding="utf-8"
            )
        )
        capabilities_path = "$.properties.capabilities"

        def capabilities(schema):
            return schema["properties"]["capabilities"]

        mutations = (
            lambda schema: capabilities(schema)["required"].remove("states"),
            lambda schema: capabilities(schema)["properties"].update(
                {"extensionData": {"type": "string"}}
            ),
            lambda schema: capabilities(schema)["required"].append("states"),
            lambda schema: capabilities(schema)["required"].append(7),
            lambda schema: capabilities(schema).__setitem__("required", "states"),
            lambda schema: capabilities(schema).__setitem__("properties", []),
        )

        for mutate in mutations:
            schema = copy.deepcopy(lifecycle_schema)
            mutate(schema)
            with self.subTest(mutation=mutate):
                self.assertEqual(checker(schema), (capabilities_path,))


if __name__ == "__main__":
    unittest.main()
