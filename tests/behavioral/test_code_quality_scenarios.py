from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class CodeQualityScenarioTests(unittest.TestCase):
    def test_scenarios_cover_all_approved_failure_classes(self):
        value = yaml.safe_load(
            (ROOT / "tests/behavioral/scenarios/code-quality.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(value["schemaVersion"], 1)
        self.assertEqual(
            {scenario["id"] for scenario in value["scenarios"]},
            {
                "downstream-compensation",
                "partial-persistence",
                "stale-recovery-data",
                "shared-path-regression",
                "dirty-worktree",
                "false-noop-success",
                "application-layer-intrusion",
                "batch-configuration-write",
            },
        )
        self.assertTrue(all(scenario["critical"] for scenario in value["scenarios"]))

    def test_skills_are_standalone_generic_and_contain_core_invariants(self):
        code_quality = (ROOT / "skills/code-quality/SKILL.md").read_text(encoding="utf-8")
        workflow_quality = (ROOT / "skills/workflow-quality/SKILL.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "failure envelope",
            "last-good",
            "first-bad",
            "root-cause owner",
            "detection point",
            "caches",
            "rebuild scope",
            "shared paths",
            "no-op",
            "existing changes",
            "plan -> review -> confirm -> apply -> reread",
        ):
            self.assertIn(phrase, code_quality)
        self.assertIn("fresh evidence", workflow_quality)
        combined = code_quality + workflow_quality
        for content in (code_quality, workflow_quality):
            frontmatter = content.split("---", 2)[1]
            description = next(
                line.removeprefix("description: ")
                for line in frontmatter.splitlines()
                if line.startswith("description: ")
            )
            self.assertTrue(description.startswith("Use when "))
        self.assertNotIn("kuaishou", combined.casefold())
        self.assertNotIn(":\\", combined)

    def test_baseline_is_truthfully_unverified_until_real_agent_run(self):
        baseline = (ROOT / "docs/provenance/code-quality-baseline.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("unverified", baseline)
        self.assertIn("Access denied", baseline)


if __name__ == "__main__":
    unittest.main()
