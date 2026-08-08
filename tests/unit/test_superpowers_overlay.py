from pathlib import Path
import json
import tempfile
import unittest

import yaml

from selfworkflow.superpowers import decide_overlay, stage_selected_skills
from selfworkflow.catalog import compile_catalog


class SuperpowersOverlayTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_checked_in_overlay_and_grill_skill_are_stable_and_vendor_neutral(self):
        stage_map = yaml.safe_load(
            (self.ROOT / "overlays/superpowers/stage-map.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            stage_map["stages"]["implemented"]["debug"],
            ["systematic-debugging"],
        )
        policies = yaml.safe_load(
            (self.ROOT / "overlays/superpowers/policies.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(policies["grillMe"]["activation"], "explicit-only")
        self.assertTrue(
            policies["grillMe"]["postReview"]["independentContextRequired"]
        )
        skill = (self.ROOT / "skills/grill-me/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("description: Use when ", skill)
        self.assertIn("independent", skill.casefold())
        self.assertNotIn("codex", skill.casefold())

    def test_catalog_registers_new_skills_without_overstating_behavior_support(self):
        envelope = json.loads(compile_catalog(self.ROOT / "catalog").content)
        entries = {
            item["id"]: item for item in envelope["catalog"]["entries"]
        }
        for skill_id in ("grill-me", "code-quality", "workflow-quality"):
            self.assertIn(skill_id, entries)
            self.assertEqual(entries[skill_id]["source"]["kind"], "skill")
            self.assertEqual(entries[skill_id]["supportStatus"], "unverified")

    def test_stage_mapping_loads_only_current_phase_skills(self):
        cases = {
            ("designed", "design"): ("brainstorming",),
            ("planned", "plan"): ("writing-plans",),
            ("implemented", "implement"): ("test-driven-development",),
            ("implemented", "debug"): ("systematic-debugging",),
            ("reviewed", "review"): (
                "requesting-code-review", "receiving-code-review"
            ),
            ("verified", "verify"): ("verification-before-completion",),
        }
        for (stage, operation), expected in cases.items():
            with self.subTest(stage=stage, operation=operation):
                decision = decide_overlay(
                    stage=stage,
                    operation=operation,
                    complexity=1,
                    risk=1,
                    explicit_grill=False,
                    source_status="supported",
                    write_task=True,
                )
                self.assertEqual(decision["selectedSkills"], expected)

    def test_grill_is_explicit_and_requires_independent_brainstorm_review(self):
        ordinary = decide_overlay(
            stage="designed", operation="design", complexity=3, risk=3,
            explicit_grill=False, source_status="supported", write_task=True,
        )
        self.assertNotIn("grill-me", ordinary["selectedSkills"])
        self.assertTrue(ordinary["grillRecommended"])

        grilled = decide_overlay(
            stage="designed", operation="design", complexity=2, risk=2,
            explicit_grill=True, source_status="supported", write_task=True,
        )
        self.assertEqual(grilled["selectedSkills"], ("grill-me", "brainstorming"))
        self.assertEqual(
            grilled["postGrillReview"],
            {"skill": "brainstorming", "independentContextRequired": True},
        )

    def test_missing_superpowers_pauses_writes_without_silent_downgrade(self):
        paused = decide_overlay(
            stage="implemented", operation="implement", complexity=1, risk=1,
            explicit_grill=False, source_status="unsupported", write_task=True,
        )
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["selectedSkills"], ())
        self.assertIn("superpowers", paused["issues"])

        readonly = decide_overlay(
            stage="discovered", operation="analyze", complexity=1, risk=1,
            explicit_grill=False, source_status="unsupported", write_task=False,
        )
        self.assertEqual(readonly["status"], "active")
        self.assertEqual(readonly["allowedMode"], "read-only-analysis")
        self.assertIn("superpowers", readonly["issues"])

    def test_staging_copies_only_selected_skills_and_never_mutates_source(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / "runtime"
            for name in ("brainstorming", "writing-plans"):
                skill = source / "skills" / name / "SKILL.md"
                skill.parent.mkdir(parents=True)
                skill.write_text(name + "\n", encoding="utf-8")
            before = {
                path.relative_to(source).as_posix(): path.read_bytes()
                for path in source.rglob("*") if path.is_file()
            }

            receipt = stage_selected_skills(source, target, ("brainstorming",))

            self.assertEqual(receipt["selectedSkills"], ("brainstorming",))
            self.assertTrue((target / "brainstorming" / "SKILL.md").is_file())
            self.assertFalse((target / "writing-plans").exists())
            after = {
                path.relative_to(source).as_posix(): path.read_bytes()
                for path in source.rglob("*") if path.is_file()
            }
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
