from pathlib import Path
import tempfile
import unittest

import yaml

from selfworkflow.adapters import _copy_matt_skills
from selfworkflow.documents import publish_documents


ROOT = Path(__file__).resolve().parents[2]


class MattDeliveryTests(unittest.TestCase):
    """Exercise the importer and cloneable document consumer, not model routing."""

    def test_runtime_publishes_workflow_owned_pr_and_retro_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            _copy_matt_skills(ROOT, destination, include_grill_me=False)
            for name in ("pr", "retro"):
                with self.subTest(name=name):
                    published = destination / "skills/matt-pocock" / name / "SKILL.md"
                    self.assertTrue(published.is_file(), name)
                    local = ROOT / "workflow/skills" / name / "SKILL.md"
                    self.assertEqual(published.read_text("utf-8"), local.read_text("utf-8"))
                    metadata = yaml.safe_load(published.read_text("utf-8").split("---", 2)[1])
                    self.assertEqual(metadata["name"], name)
                    self.assertEqual(metadata.get("disable-model-invocation", False), name == "retro")
            self.assertTrue((destination / "skills/matt-pocock/LICENSE").is_file())

    def test_cloneable_documents_include_delivery_routes_and_optional_methods(self):
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(publish_documents(ROOT, Path(temporary) / "public")["documentRoot"])
            self.assertIn("workflow/modules/delivery.md", (release / "WORKFLOW.md").read_text("utf-8"))
            delivery = (release / "workflow/modules/delivery.md").read_text("utf-8")
            for relative in ("methods/implement-spec/METHOD.md", "methods/matt-pocock/pr/METHOD.md", "methods/matt-pocock/retro/METHOD.md"):
                with self.subTest(relative=relative):
                    self.assertTrue((release / relative).is_file())
                    self.assertIn(Path(relative).parent.name, delivery)
            index = (release / "methods/INDEX.md").read_text("utf-8")
            self.assertIn("[pr]", index)
            self.assertIn("[retro]", index)
            spec = (release / "methods/implement-spec/METHOD.md").read_text("utf-8")
            metadata = yaml.safe_load(spec.split("---", 2)[1])
            self.assertEqual(metadata["metadata"]["activation"], "task-conditional")
            # Agent-policy selection may be implicit; the Host contract stays explicit.
            contract = yaml.safe_load(spec.split("```yaml\n", 1)[1].split("\n```", 1)[0])
            self.assertEqual(contract["activation"], "explicit")
            self.assertEqual(contract["minimumTickets"], 2)
