from pathlib import Path
import json
import tempfile
import unittest

from selfworkflow.adapters import build_runtime
from selfworkflow.installer import (
    InstallerError,
    apply_install_plan,
    apply_rollback_plan,
    create_install_plan,
    create_rollback_plan,
    doctor,
    verify_install,
)


class InstallSandboxAcceptanceTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_full_lifecycle_preserves_unmanaged_bytes_is_idempotent_and_rolls_back(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = root / "runtime"
            build_runtime(self.ROOT, artifact, "0.1.0.dev0")
            agents, codex, state = root / "agents", root / "codex", root / "state"
            existing_skill = agents / "skills/existing/SKILL.md"
            existing_skill.parent.mkdir(parents=True)
            existing_skill.write_bytes(b"existing-skill\r\n")
            codex.mkdir()
            agents_file = codex / "AGENTS.md"
            agents_file.write_bytes(b"user-instructions\r\n")
            before = {"skill": existing_skill.read_bytes(), "agents": agents_file.read_bytes()}

            dry_before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            report = doctor(agents, codex, state)
            dry_after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertEqual(dry_after, dry_before)
            self.assertEqual(report["securityStatus"], "unverified")

            plan = create_install_plan(artifact, agents, codex, state, "0.1.0.dev0")
            applied = apply_install_plan(plan, plan["planHash"])
            self.assertEqual(verify_install(applied["manifestPath"])["status"], "verified")
            self.assertEqual(existing_skill.read_bytes(), before["skill"])
            self.assertIn(b"user-instructions\r\n", agents_file.read_bytes())

            repeat_plan = create_install_plan(artifact, agents, codex, state, "0.1.0.dev0")
            repeat = apply_install_plan(repeat_plan, repeat_plan["planHash"])
            self.assertEqual(repeat["status"], "already-installed")

            rollback = create_rollback_plan(applied["transactionPath"])
            self.assertEqual(
                apply_rollback_plan(rollback, rollback["planHash"])["status"],
                "rolled-back",
            )
            self.assertEqual(existing_skill.read_bytes(), before["skill"])
            self.assertEqual(agents_file.read_bytes(), before["agents"])
            self.assertFalse((agents / "skills/code-quality/SKILL.md").exists())

    def test_conflict_drift_and_incomplete_transaction_pause_without_overwrite(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = root / "runtime"
            build_runtime(self.ROOT, artifact, "0.1.0.dev0")
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            agents_file = codex / "AGENTS.md"
            agents_file.write_text("<!-- selfworkflow:begin -->\nbroken\n", encoding="utf-8")
            paused = create_install_plan(artifact, agents, codex, state, "0.1.0.dev0")
            self.assertEqual(paused["status"], "paused")
            before = agents_file.read_bytes()
            with self.assertRaises(InstallerError):
                apply_install_plan(paused, paused["planHash"])
            self.assertEqual(agents_file.read_bytes(), before)

            agents_file.write_text("clean\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0.dev0")
            agents_file.write_text("drift\n", encoding="utf-8")
            with self.assertRaises(InstallerError):
                apply_install_plan(plan, plan["planHash"])
            self.assertEqual(agents_file.read_text(encoding="utf-8"), "drift\n")

            transactions = state / "transactions"
            transactions.mkdir(parents=True)
            (transactions / "incomplete.json").write_text(
                json.dumps({"transactionId": "incomplete", "state": "applying"}),
                encoding="utf-8",
            )
            self.assertEqual(
                doctor(agents, codex, state)["incompleteTransactions"][0]["action"],
                "manual-attention",
            )


if __name__ == "__main__":
    unittest.main()
