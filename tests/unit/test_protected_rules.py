import json
import importlib.util
from dataclasses import FrozenInstanceError
from pathlib import Path
import re
import traceback
import unittest

from jsonschema import Draft202012Validator
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _open_object_schema_paths(value):
    open_paths = []

    def visit(node, path):
        if isinstance(node, dict):
            if node.get("type") == "object":
                required = node.get("required")
                properties = node.get("properties")
                if (
                    node.get("additionalProperties") is not False
                    or not isinstance(required, list)
                    or not isinstance(properties, dict)
                    or len(required) != len(set(required))
                    or set(required) != set(properties)
                ):
                    open_paths.append(path)
            for key, nested in node.items():
                visit(nested, f"{path}.{key}")
        elif isinstance(node, list):
            for index, nested in enumerate(node):
                visit(nested, f"{path}[{index}]")

    visit(value, "$")
    return tuple(open_paths)


class ProtectedRulesTests(unittest.TestCase):
    def test_checked_in_contract_contains_the_closed_protected_invariants(self):
        document_path = REPOSITORY_ROOT / "workflow" / "protected-rules.yaml"
        schema_path = REPOSITORY_ROOT / "schemas" / "protected-rules.schema.json"
        self.assertTrue(document_path.is_file(), "protected rules are missing")
        self.assertTrue(schema_path.is_file(), "protected rules schema is missing")
        document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)
        self.assertEqual(_open_object_schema_paths(schema), ())
        self.assertEqual(
            tuple(rule["id"] for rule in document["rules"]),
            (
                "truthful-capability-review-verification",
                "no-silent-degradation",
                "protect-credentials-and-sensitive-data",
                "authorize-side-effects-and-irreversible-actions",
                "protect-user-existing-changes",
                "require-fresh-verification-before-completion",
            ),
        )
        self.assertEqual(
            tuple(rule["strength"] for rule in document["rules"]),
            (
                "agent-policy",
                "agent-policy",
                "agent-policy",
                "agent-policy",
                "agent-policy",
                "enforced",
            ),
        )
        self.assertEqual(
            document["mergeOrder"],
            ["protected", "skill", "project", "overlay"],
        )
        self.assertEqual(
            document["ownerModificationGate"],
            {
                "destructiveChangeConfirmed": True,
                "versionBump": "major",
                "independentReview": {
                    "status": "passed",
                    "requiresEvidenceHash": True,
                },
                "behavioralTests": {
                    "status": "passed",
                    "requiresEvidenceHash": True,
                },
            },
        )

    def test_lower_priority_layers_cannot_replace_a_protected_rule(self):
        module_spec = importlib.util.find_spec("selfworkflow.evidence")
        self.assertIsNotNone(module_spec, "protected rule merge is missing")
        from selfworkflow.evidence import WorkflowEvidenceError
        from selfworkflow.evidence import merge_protected_rules

        protected = yaml.safe_load(
            (REPOSITORY_ROOT / "workflow" / "protected-rules.yaml").read_text(
                encoding="utf-8"
            )
        )
        secret = "hostile-sensitive-layer-value"
        errors = []
        for kind in ("skill", "project", "overlay"):
            with self.subTest(kind=kind):
                layer = {
                    "kind": kind,
                    "name": secret,
                    "rules": [
                        {
                            "id": "no-silent-degradation",
                            "strength": "agent-policy",
                        }
                    ],
                }
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    merge_protected_rules(protected, [layer])
                errors.append(caught.exception)

        self.assertEqual(
            [error.code for error in errors],
            ["protected-rule-override-denied"] * 3,
        )
        self.assertEqual(
            {error.message for error in errors},
            {"A lower-priority rule cannot replace a protected rule."},
        )
        self.assertTrue(all(secret not in str(error) for error in errors))

    def test_rule_merge_is_deterministic_and_deeply_immutable(self):
        from selfworkflow.evidence import merge_protected_rules

        protected = yaml.safe_load(
            (REPOSITORY_ROOT / "workflow" / "protected-rules.yaml").read_text(
                encoding="utf-8"
            )
        )
        layers = [
            {
                "kind": "overlay",
                "name": "personal",
                "rules": [
                    {"id": "extension-shared", "strength": "enforced"},
                ],
            },
            {
                "kind": "skill",
                "name": "general",
                "rules": [
                    {"id": "extension-shared", "strength": "agent-policy"},
                    {"id": "extension-skill", "strength": "agent-policy"},
                ],
            },
            {
                "kind": "project",
                "name": "repository",
                "rules": [
                    {"id": "extension-project", "strength": "enforced"},
                ],
            },
        ]

        first = merge_protected_rules(protected, layers)
        second = merge_protected_rules(protected, list(reversed(layers)))

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(rule.id for rule in first.rules),
            tuple(sorted(rule.id for rule in first.rules)),
        )
        shared = first.rule_for("extension-shared")
        self.assertIsNotNone(shared)
        self.assertEqual(
            (shared.strength, shared.source_kind, shared.source_name),
            ("enforced", "overlay", "personal"),
        )
        with self.assertRaises(FrozenInstanceError):
            shared.strength = "agent-policy"
        with self.assertRaises(TypeError):
            first.rules[0] = shared

    def test_owner_changes_require_the_complete_exact_breaking_change_gate(self):
        from selfworkflow.evidence import WorkflowEvidenceError
        from selfworkflow.evidence import merge_protected_rules

        protected = yaml.safe_load(
            (REPOSITORY_ROOT / "workflow" / "protected-rules.yaml").read_text(
                encoding="utf-8"
            )
        )
        owner_rules = [dict(rule) for rule in protected["rules"]]
        owner_rules[0]["strength"] = "enforced"
        authorization = {
            "destructiveChangeConfirmed": True,
            "versionBump": "major",
            "independentReview": {
                "status": "passed",
                "evidenceHash": "sha256:" + "a" * 64,
            },
            "behavioralTests": {
                "status": "passed",
                "evidenceHash": "sha256:" + "b" * 64,
            },
        }

        invalid_authorizations = [
            {key: value for key, value in authorization.items() if key != missing}
            for missing in authorization
        ]
        invalid_authorizations.append(
            {**authorization, "destructiveChangeConfirmed": 1}
        )

        class TruthyString(str):
            pass

        invalid_authorizations.append(
            {**authorization, "versionBump": TruthyString("major")}
        )
        invalid_authorizations.append(
            {
                **authorization,
                "independentReview": {
                    **authorization["independentReview"],
                    "status": TruthyString("passed"),
                },
            }
        )
        invalid_authorizations.append(
            {
                **authorization,
                "behavioralTests": {
                    **authorization["behavioralTests"],
                    "evidenceHash": TruthyString("sha256:" + "b" * 64),
                },
            }
        )

        for invalid in invalid_authorizations:
            with self.subTest(invalid=tuple(invalid)):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    merge_protected_rules(
                        protected,
                        owner_rules=owner_rules,
                        owner_authorization=invalid,
                    )
                self.assertEqual(
                    caught.exception.code,
                    "protected-rule-owner-authorization-required",
                )
                self.assertEqual(
                    caught.exception.message,
                    "A protected-rule change requires the complete breaking-change gate.",
                )

        merged = merge_protected_rules(
            protected,
            owner_rules=owner_rules,
            owner_authorization=authorization,
        )
        changed = merged.rule_for("truthful-capability-review-verification")
        self.assertIsNotNone(changed)
        self.assertEqual(changed.strength, "enforced")
        self.assertEqual(changed.source_name, "repository-owner")
        self.assertTrue(changed.protected)

    def test_hostile_and_unordered_rule_inputs_fail_with_redacted_errors(self):
        from selfworkflow.evidence import WorkflowEvidenceError
        from selfworkflow.evidence import merge_protected_rules

        protected = yaml.safe_load(
            (REPOSITORY_ROOT / "workflow" / "protected-rules.yaml").read_text(
                encoding="utf-8"
            )
        )
        secret = "TOP-SECRET-HOSTILE-RULE-INPUT"

        class HostileMapping(dict):
            def items(self):
                raise RuntimeError(secret)

        cases = []
        hostile_gate = dict(protected)
        hostile_gate["ownerModificationGate"] = HostileMapping()
        cases.append(hostile_gate)
        unordered_order = dict(protected)
        unordered_order["mergeOrder"] = {
            "protected",
            "skill",
            "project",
            "overlay",
        }
        cases.append(unordered_order)

        for invalid in cases:
            with self.subTest(case=type(invalid["mergeOrder"]).__name__):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    merge_protected_rules(invalid)
                error = caught.exception
                self.assertEqual(error.code, "protected-rules-invalid")
                self.assertEqual(error.message, "The protected-rule document is invalid.")
                self.assertIsNone(error.__cause__)
                self.assertTrue(error.__suppress_context__)
                self.assertNotIn(secret, str(error))
                self.assertNotIn(secret, "".join(traceback.format_exception(error)))

    def test_workflow_document_describes_only_the_implemented_core(self):
        document_path = REPOSITORY_ROOT / "WORKFLOW.md"
        self.assertTrue(document_path.is_file(), "WORKFLOW.md is missing")
        text = document_path.read_text(encoding="utf-8")
        headings = tuple(
            line.strip()
            for line in text.splitlines()
            if line.startswith("## ")
        )
        self.assertEqual(
            headings,
            (
                "## Lifecycle",
                "## Phase capability contract",
                "## Rule precedence",
                "## Completion evidence",
                "## On-demand loading",
            ),
        )
        self.assertIn(
            "agent-policy rules are behavior-tested policies, not technical enforcement",
            text,
        )
        self.assertIn("passed", text)
        self.assertIn("not-applicable", text)
        self.assertIn("read-only", text)

        forbidden = re.compile(
            r"\b(catalog|router|installer|mcp|openai|anthropic|codex|claude)\b",
            flags=re.IGNORECASE,
        )
        self.assertIsNone(forbidden.search(text))
        links = re.findall(r"\[[^]]+\]\(([^)]+)\)", text)
        self.assertTrue(links)
        for target in links:
            with self.subTest(target=target):
                self.assertFalse(target.startswith(("http://", "https://")))
                self.assertTrue((REPOSITORY_ROOT / target).is_file())


if __name__ == "__main__":
    unittest.main()
