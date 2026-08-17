from pathlib import Path
import json
import tempfile
import unittest

import yaml

from selfworkflow.superpowers import stage_selected_skills
from selfworkflow.catalog import compile_catalog


class SuperpowersOverlayTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_legacy_overlay_remains_isolated_and_grill_comes_from_matt_foundation(self):
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
        self.assertFalse((self.ROOT / "skills/grill-me/SKILL.md").exists())
        skill = (
            self.ROOT
            / "dependencies/upstream/matt-pocock-skills/skills/productivity/grill-me/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("grill", skill.casefold())

    def test_catalog_registers_new_skills_without_overstating_behavior_support(self):
        envelope = json.loads(compile_catalog(self.ROOT / "catalog").content)
        entries = {
            item["id"]: item for item in envelope["catalog"]["entries"]
        }
        for skill_id in ("code-quality", "workflow-quality"):
            self.assertIn(skill_id, entries)
            self.assertEqual(entries[skill_id]["source"]["kind"], "skill")
            self.assertEqual(entries[skill_id]["supportStatus"], "unverified")
        self.assertNotIn("grill-me", entries)
        self.assertEqual(
            entries["matt-skills-foundation"]["supportStatus"], "supported"
        )

    def test_catalog_is_the_only_runtime_stage_mapping(self):
        source = (self.ROOT / "src/selfworkflow/superpowers.py").read_text(encoding="utf-8")
        self.assertNotIn("_STAGE_MAP", source)
        envelope = json.loads(compile_catalog(self.ROOT / "catalog").content)
        modules = {module["id"]: module for module in envelope["catalog"]["modules"]}
        self.assertEqual(modules["design-core"]["slot"], "design.primary")
        self.assertEqual(modules["design-grilling"]["activation"], "full-default")
        self.assertEqual(modules["design-grill-me"]["activation"], "deep-default")
        self.assertEqual(modules["plan-core"]["slot"], "plan.primary")
        self.assertEqual(modules["implement-tdd"]["slot"], "implement.tdd")
        self.assertEqual(modules["verify-execution"]["slot"], "verify.execution")

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
