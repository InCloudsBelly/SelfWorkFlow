from pathlib import Path
import tempfile
import unittest

from selfworkflow.documents import publish_documents
from selfworkflow.installer import InstallerError, _canonical_hash, create_install_plan, apply_install_plan, verify_install, create_rollback_plan, apply_rollback_plan
from tests.installer.support import create_artifact, write_adapter
from tests.unit.test_documents import source_tree


class DocumentLinkTests(unittest.TestCase):
    def test_existing_document_binding_cannot_be_dropped_or_redirected_by_a_rehashed_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public, other = root / "public", root / "other"
            publish_documents(source, public)
            publish_documents(source, other)
            artifact = create_artifact(root)
            agents, codex, state = (root / n for n in ("agents", "codex", "state"))
            initial = create_install_plan(artifact, agents, codex, state, "0.1", document_root=public)
            result = apply_install_plan(initial, initial["planHash"])
            before = (codex / "AGENTS.md").read_bytes()
            changed = create_install_plan(artifact, agents, codex, state, "0.1", document_root=other)
            self.assertEqual(changed["status"], "paused")
            self.assertIn("document-root-binding-change", changed["issues"])
            for value, error in ((None, "document-root-binding-required"), (str(other.resolve()), "document-root-binding-change")):
                with self.subTest(value=value):
                    plan = create_install_plan(artifact, agents, codex, state, "0.1")
                    plan["status"] = "ready"
                    if value is None:
                        del plan["documentRoot"]
                    else:
                        plan["documentRoot"] = value
                    del plan["planHash"]
                    plan["planHash"] = _canonical_hash(plan)
                    with self.assertRaisesRegex(InstallerError, error):
                        apply_install_plan(plan, plan["planHash"])
                    self.assertEqual((codex / "AGENTS.md").read_bytes(), before)
                    self.assertFalse((agents / "skills/sample-skill/SKILL.md").exists())
            self.assertEqual(verify_install(result["manifestPath"])["status"], "verified")

    def test_changed_owned_skill_pauses_migration_without_removing_user_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public = root / "public"
            publish_documents(source, public)
            artifact = create_artifact(root)
            agents, codex, state = (root / n for n in ("agents", "codex", "state"))
            initial = create_install_plan(artifact, agents, codex, state, "0.1")
            apply_install_plan(initial, initial["planHash"])
            target = agents / "skills/sample-skill/SKILL.md"
            target.write_text("User changes\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1", document_root=public)
            self.assertEqual(plan["status"], "paused")
            self.assertIn("managed-skill-drift:skills/sample-skill/SKILL.md", plan["issues"])
            with self.assertRaises(InstallerError):
                apply_install_plan(plan, plan["planHash"])
            self.assertEqual(target.read_text(encoding="utf-8"), "User changes\n")

    def test_migration_retires_owned_skills_and_update_never_changes_host_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public = root / "public"
            publish_documents(source, public)
            artifact = create_artifact(root)
            write_adapter(artifact, "dsh", "DSH legacy note")
            agents, codex, dsh, state = (root / n for n in ("agents", "codex", "dsh", "state"))
            codex.mkdir()
            (codex / "AGENTS.md").write_text("User rules.\n", encoding="utf-8")
            user_rules = (codex / "AGENTS.md").read_bytes()
            legacy = create_install_plan(artifact, agents, codex, state, "0.1", dsh_root=dsh)
            apply_install_plan(legacy, legacy["planHash"])
            old = (codex / "AGENTS.md").read_bytes()
            user = agents / "skills/user/SKILL.md"
            user.parent.mkdir()
            user.write_text("User skill", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1", dsh_root=dsh, document_root=public)
            self.assertEqual(plan["status"], "ready")
            self.assertIn("skills/sample-skill/SKILL.md", plan["retiredSkillFiles"])
            result = apply_install_plan(plan, plan["planHash"])
            self.assertEqual(verify_install(result["manifestPath"])["status"], "verified")
            self.assertFalse((agents / "skills/sample-skill/SKILL.md").exists())
            self.assertEqual(user.read_text(encoding="utf-8"), "User skill")
            linked = (codex / "AGENTS.md").read_bytes()
            self.assertTrue(linked.startswith(user_rules))
            self.assertIn(b"public/WORKFLOW.md", linked)
            self.assertNotIn(b"artifact:", linked)
            self.assertNotIn(b"DSH legacy", (dsh / "AGENTS.md").read_bytes())
            (source / "skills/example/details.md").write_text("Updated rule\n", encoding="utf-8")
            publish_documents(source, public)
            self.assertEqual((codex / "AGENTS.md").read_bytes(), linked)
            again = create_install_plan(artifact, agents, codex, state, "0.1", dsh_root=dsh)
            self.assertEqual(again.get("documentRoot"), str(public.resolve()))
            self.assertEqual(again["status"], "already-installed")
            rollback = create_rollback_plan(result["transactionPath"])
            apply_rollback_plan(rollback, rollback["planHash"])
            self.assertEqual((codex / "AGENTS.md").read_bytes(), old)
            self.assertTrue((agents / "skills/sample-skill/SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
