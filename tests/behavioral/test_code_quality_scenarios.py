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
                "test-driven-production-intrusion",
                "local-test-seam",
                "implementation-contract-boundary-drift",
                "in-budget-private-detail",
                "adjacent-diagnostic-subsystem",
                "unplanned-regression-blocker",
                "stable-callers-reverse-dependency",
                "shared-invariant-owner-migration",
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
            "intrusion budget",
            "impact radius",
            "test coverage must not drive production architecture",
            "public enum",
            "global build macro",
            "test-owned translation unit",
            "explicit user approval",
            "implementation contract",
            "first test or production-code edit",
            "explicit implementation confirmation",
            "safety, performance, compatibility, maintenance, and rollback",
            "contract becomes invalid",
            "design exploration",
            "implementation convergence",
            "discovering a problem does not authorize solving it",
            "the approved plan is the execution boundary",
            "unplanned finding",
            "blocks a broad regression",
            "revise the plan",
            "complete the current objective",
            "bounded convergence check",
            "stable existing callers",
            "shared invariant",
            "testing convenience",
            "unverified",
        ):
            self.assertIn(phrase.casefold(), code_quality.casefold())
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

    def test_code_quality_supports_read_only_analysis_without_change_rules(self):
        code_quality = (ROOT / "skills/code-quality/SKILL.md").read_text(
            encoding="utf-8"
        )
        catalog = yaml.safe_load(
            (ROOT / "catalog/domains/code-quality.yaml").read_text(encoding="utf-8")
        )
        entry = next(item for item in catalog["entries"] if item["id"] == "code-quality")

        self.assertIn("reading or explaining behavior code", code_quality)
        self.assertIn("## Read-only reasoning core", code_quality)
        self.assertIn("does not activate change rules", code_quality)
        self.assertIn("analyze", entry["selectors"]["operationTypes"])
        self.assertIn("read code", entry["selectors"]["semanticTerms"])

    def test_baseline_records_the_observed_old_rule_failure(self):
        baseline = (ROOT / "docs/provenance/code-quality-baseline.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "observed baseline failure",
            "public EMeshPass",
            "test-only enum slot",
            "production Renderer path",
            "narrowest compatible owner-layer change",
        ):
            self.assertIn(phrase, baseline)


if __name__ == "__main__":
    unittest.main()
