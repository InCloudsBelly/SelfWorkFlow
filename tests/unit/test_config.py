import json
from pathlib import Path
import tempfile
import unittest

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_VENDOR_TOKENS = ("openai", "codex", "claude", "cursor", "opencode", "copilot")


def _find_vendor_tokens(value):
    found = set()

    def visit(node):
        if isinstance(node, dict):
            for key, nested_value in node.items():
                visit(key)
                visit(nested_value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                visit(item)
        elif isinstance(node, str):
            normalized = node.casefold()
            found.update(token for token in _VENDOR_TOKENS if token in normalized)

    visit(value)
    return tuple(sorted(found))


def _open_object_schema_paths(value):
    open_paths = []

    def visit(node, path):
        if isinstance(node, dict):
            if (
                node.get("type") == "object"
                and node.get("additionalProperties") is not False
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
        self.assertFalse(config["upgrades"]["user"]["mayDecreaseBelowMinimum"])
        self.assertEqual(
            config["capabilityGate"]["pause"],
            {"status": "paused", "code": "required-capabilities-unavailable"},
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
            {"mayIncrease", "mayDecreaseBelowMinimum"},
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
        self.assertEqual(set(policies["capabilityGate"]["pause"]), {"status", "code"})

        self.assertEqual(
            set(evidence),
            {"schemaVersion", "requiredFields", "verification"},
        )
        self.assertEqual(
            set(evidence["verification"]),
            {"unverifiedFrom", "completionEligible"},
        )

    def test_workflow_documents_and_schemas_are_vendor_neutral_recursively(self):
        scanner = globals().get("_find_vendor_tokens")
        self.assertTrue(callable(scanner), "vendor token scanner is missing")

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
                "OpenAIAdapter": {"provider": "CoPilot"},
                "runtime": ["Claude", "Cursor", "OpenCode", "Codex"],
            }
        )
        self.assertEqual(
            detected,
            ("claude", "codex", "copilot", "cursor", "openai", "opencode"),
        )

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
            "properties": {
                "nested": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {},
                }
            },
        }
        self.assertEqual(
            checker(loosened_fixture),
            ("$.properties.nested",),
        )


if __name__ == "__main__":
    unittest.main()
