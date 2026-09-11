from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

from selfworkflow.installer import InstallerError, create_install_plan
from selfworkflow.cli import main
from tests.installer.support import create_artifact


class InstallPlanTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_plan_is_read_only_hash_bound_and_schema_valid(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertEqual(after, before)
            self.assertEqual(plan["status"], "ready")
            self.assertEqual(plan["profile"], "custom-unverified")
            self.assertRegex(plan["planHash"], r"^sha256:[0-9a-f]{64}$")
            self.assertIn("skills/sample-skill/SKILL.md", plan["artifactFiles"])
            schema = json.loads(
                (self.ROOT / "schemas/install-plan.schema.json").read_text(encoding="utf-8")
            )
            Draft202012Validator(schema).validate(plan)

    def test_plan_pauses_on_damaged_managed_block_and_rejects_reparse_target(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            (codex / "AGENTS.md").write_text(
                "<!-- selfworkflow:begin -->\nbroken\n", encoding="utf-8"
            )
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            self.assertEqual(plan["status"], "paused")
            self.assertIn("managed-block-invalid", plan["issues"])

            link = root / "linked-agents"
            try:
                link.symlink_to(root / "real-agents", target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(InstallerError):
                create_install_plan(artifact, link, codex, state, "0.1.0")

    def test_plan_never_adopts_an_unmanaged_version_snapshot(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            initial = create_install_plan(artifact, agents, codex, state, "0.1.0")
            digest = initial["artifactHash"].removeprefix("sha256:")
            collision = agents / f"selfworkflow/versions/0.1.0/{digest}/WORKFLOW.md"
            collision.parent.mkdir(parents=True)
            collision.write_text("unmanaged\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            self.assertEqual(plan["status"], "paused")
            self.assertIn("unmanaged-snapshot-conflict:WORKFLOW.md", plan["issues"])

    def test_plan_pauses_before_retiring_unowned_caveman_skill(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            legacy = agents / "skills/caveman/SKILL.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("user-owned\n", encoding="utf-8")

            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")

            self.assertEqual(plan["status"], "paused")
            self.assertIn(
                "legacy-skill-ownership-unknown:skills/caveman/SKILL.md",
                plan["issues"],
            )

    def test_cli_writes_plan_and_requires_explicit_paths(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            output = root / "plan.json"
            arguments = [
                "install", "plan", "--artifact", str(artifact),
                "--agents-root", str(root / "agents"),
                "--codex-root", str(root / "codex"),
                "--state-root", str(root / "state"),
                "--version", "0.1.0", "--output", str(output),
            ]
            with mock.patch("sys.stdout"):
                self.assertEqual(main(arguments), 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], "ready")

    def test_plan_ignores_unmanaged_large_file_and_reparse_subtree(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            (codex / "session.jsonl").write_bytes(b"x" * (8 * 1024 * 1024 + 1))
            external = root / "plugin-cache"
            external.mkdir()
            link = codex / "plugins"
            try:
                link.symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")

            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")

            self.assertEqual(plan["status"], "ready")
            self.assertIn("stateRoot", plan["baselineHashes"])

    def test_plan_rejects_invalid_exact_managed_target_and_nested_roots(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            (codex / "AGENTS.md").write_bytes(b"x" * (8 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(InstallerError, "managed-file-invalid"):
                create_install_plan(artifact, agents, codex, state, "0.1.0")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents = root / "agents"
            with self.assertRaisesRegex(InstallerError, "roots-overlap"):
                create_install_plan(
                    artifact, agents, agents / "codex", root / "state", "0.1.0"
                )


if __name__ == "__main__":
    unittest.main()
