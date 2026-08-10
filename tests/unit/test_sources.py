from pathlib import Path
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from selfworkflow.sources import (
    commit_superpowers_migration,
    recover_superpowers_migration,
    remove_staged_superpowers_source,
    SourceSelectionError,
    inspect_superpowers_source,
    lock_superpowers_source,
    stage_superpowers_source,
)
from selfworkflow.cli import main


def _commit(root: Path):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "--local", "core.autocrlf", "false"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=SelfWorkFlow Tests",
            "-c", "user.email=selfworkflow@example.invalid",
            "commit", "-q", "-m", "fixture",
        ],
        cwd=root,
        check=True,
    )


class SuperpowersSourceTests(unittest.TestCase):
    def test_git_inspection_ignores_inherited_config_and_executable_extensions(self):
        from selfworkflow.sources import _run

        inherited = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "url.file:///attacker.insteadOf",
            "GIT_CONFIG_VALUE_0": "https://github.com/obra/superpowers.git",
            "GIT_CONFIG_PARAMETERS": "'core.fsmonitor'='attacker.exe'",
        }
        with mock.patch.dict(os.environ, inherited, clear=False), mock.patch(
            "selfworkflow.sources.subprocess.run"
        ) as run:
            _run(Path.cwd(), "status", "--porcelain")

        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("GIT_CONFIG_COUNT", environment)
        self.assertNotIn("GIT_CONFIG_KEY_0", environment)
        self.assertNotIn("GIT_CONFIG_VALUE_0", environment)
        self.assertNotIn("GIT_CONFIG_PARAMETERS", environment)
        self.assertEqual(environment["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertIn("core.fsmonitor=false", command)
        self.assertIn(f"core.hooksPath={os.devnull}", command)

    def test_local_git_source_records_commit_dirty_inventory_and_hash_drift(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            skill = root / "skills" / "brainstorming" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm v1\n", encoding="utf-8")
            _commit(root)

            clean = inspect_superpowers_source(root)
            self.assertEqual(clean["sourceType"], "local-git")
            self.assertEqual(clean["supportStatus"], "supported")
            self.assertEqual(clean["reproducibilityStatus"], "reproducible")
            self.assertFalse(clean["dirty"])
            self.assertEqual(len(clean["commit"]), 40)
            self.assertEqual(clean["dirtyFiles"], [])
            clean_hash = clean["inventoryHash"]

            skill.write_text("brainstorm v2\n", encoding="utf-8")
            dirty = inspect_superpowers_source(root)
            self.assertTrue(dirty["dirty"])
            self.assertEqual(dirty["reproducibilityStatus"], "dirty-snapshot")
            self.assertNotEqual(dirty["inventoryHash"], clean_hash)
            self.assertEqual(dirty["dirtyFiles"][0]["path"], "skills/brainstorming/SKILL.md")

    def test_missing_and_non_git_sources_are_truthfully_unsupported(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            non_git = inspect_superpowers_source(root)
            missing = inspect_superpowers_source(root / "missing")
        self.assertEqual(non_git["supportStatus"], "unsupported")
        self.assertEqual(non_git["reason"], "not-git")
        self.assertEqual(missing["supportStatus"], "unsupported")
        self.assertEqual(missing["reason"], "missing")

    def test_lock_requires_explicit_selection_and_dirty_authorization(self):
        candidate = {
            "sourceType": "local-git",
            "supportStatus": "supported",
            "reproducibilityStatus": "dirty-snapshot",
            "commit": "a" * 40,
            "dirty": True,
            "inventoryHash": "sha256:" + "b" * 64,
            "dirtyFiles": [{"path": "SKILL.md", "sha256": "c" * 64}],
        }
        with self.assertRaises(SourceSelectionError):
            lock_superpowers_source(candidate, selected_by_user=False, allow_dirty=False)
        with self.assertRaises(SourceSelectionError):
            lock_superpowers_source(candidate, selected_by_user=True, allow_dirty=False)

        locked = lock_superpowers_source(
            candidate, selected_by_user=True, allow_dirty=True
        )
        self.assertEqual(locked["selectionStatus"], "selected")
        self.assertTrue(locked["dirtyAuthorized"])

    def test_refused_or_unavailable_source_pauses_writes_but_allows_disclosed_readonly(self):
        unavailable = {
            "sourceType": "missing",
            "supportStatus": "unsupported",
            "reproducibilityStatus": "unavailable",
            "reason": "missing",
        }
        with self.assertRaises(SourceSelectionError):
            lock_superpowers_source(unavailable, selected_by_user=True, allow_dirty=False)
        self.assertEqual(
            lock_superpowers_source(
                unavailable,
                selected_by_user=False,
                allow_dirty=False,
                readonly_fallback=True,
            ),
            {
                "selectionStatus": "declined",
                "allowedMode": "read-only-analysis",
                "reason": "superpowers-unavailable-or-declined",
            },
        )

    def test_cli_source_inspect_emits_the_read_only_report(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            (root / "skills/brainstorming").mkdir(parents=True)
            (root / "skills/brainstorming/SKILL.md").write_text(
                "brainstorm\n", encoding="utf-8"
            )
            _commit(root)
            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                result = main(["source", "inspect", "--path", str(root)])
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["supportStatus"], "supported")
        self.assertEqual(report["sourceLocator"], str(root.resolve()))

    def test_stage_copies_only_hash_bound_tracked_skills_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            (source / "README.md").write_text("not staged\n", encoding="utf-8")
            _commit(source)
            (source / "skills/untracked.txt").write_text("ignore\n", encoding="utf-8")
            report = inspect_superpowers_source(source)
            target = root / "agents/skills/superpowers"

            first = stage_superpowers_source(
                source, target, report["inventoryHash"]
            )
            second = stage_superpowers_source(
                source, target, report["inventoryHash"]
            )

            self.assertEqual(first["status"], "staged")
            self.assertEqual(second["status"], "already-staged")
            self.assertTrue((target / "brainstorming/SKILL.md").is_file())
            self.assertFalse((target / "untracked.txt").exists())
            self.assertFalse((target / "README.md").exists())
            lock = json.loads(
                (target / ".selfworkflow-source.json").read_text(encoding="utf-8")
            )
            self.assertEqual(lock["inventoryHash"], report["inventoryHash"])

    def test_stage_rejects_source_drift_and_unmanaged_target(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("v1\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            skill.write_text("v2\n", encoding="utf-8")
            with self.assertRaisesRegex(SourceSelectionError, "source-drift"):
                stage_superpowers_source(
                    source, root / "drift-target", report["inventoryHash"]
                )

            conflict = root / "agents/skills/superpowers"
            conflict.mkdir(parents=True)
            (conflict / "foreign.txt").write_text("keep\n", encoding="utf-8")
            current = inspect_superpowers_source(source)
            with self.assertRaisesRegex(SourceSelectionError, "target-conflict"):
                stage_superpowers_source(
                    source, conflict, current["inventoryHash"]
                )
            self.assertEqual(
                (conflict / "foreign.txt").read_text(encoding="utf-8"), "keep\n"
            )

    def test_stage_rejects_source_change_during_copy_without_publication(self):
        import shutil

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("v1\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            target = root / "agents/skills/superpowers"
            real_copy = shutil.copyfile

            def copy_then_mutate(source_path, target_path):
                result = real_copy(source_path, target_path)
                Path(source_path).write_text("v2\n", encoding="utf-8")
                return result

            with mock.patch(
                "selfworkflow.sources.shutil.copyfile",
                side_effect=copy_then_mutate,
            ):
                with self.assertRaisesRegex(SourceSelectionError, "source-drift"):
                    stage_superpowers_source(
                        source, target, report["inventoryHash"]
                    )
            self.assertFalse(target.exists())

    def test_compatible_link_migration_is_explicit_hash_bound_and_recoverable(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            target = root / "agents/skills/superpowers"
            target.parent.mkdir(parents=True)
            try:
                target.symlink_to(source / "skills", target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            state = root / "state"
            journal = state / "source-migrations/superpowers.json"
            backup = state / "source-migrations/backups/superpowers-link"

            with self.assertRaisesRegex(SourceSelectionError, "target-conflict"):
                stage_superpowers_source(source, target, report["inventoryHash"])

            staged = stage_superpowers_source(
                source,
                target,
                report["inventoryHash"],
                allow_compatible_link=True,
                state_root=state,
                migration_journal=journal,
                migration_backup=backup,
                protected_roots=(root / "agents", root / "codex", root / "artifact"),
            )

            self.assertEqual(staged["migrationStatus"], "staged")
            self.assertFalse(target.is_symlink())
            self.assertTrue((target / "brainstorming/SKILL.md").is_file())
            self.assertTrue(backup.is_symlink())
            restored = recover_superpowers_migration(journal)
            self.assertEqual(restored["status"], "restored")
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), (source / "skills").resolve())

    def test_compatible_link_migration_rejects_wrong_source_and_unsafe_backup(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            wrong = root / "wrong"
            wrong.mkdir()
            target = root / "agents/skills/superpowers"
            target.parent.mkdir(parents=True)
            try:
                target.symlink_to(wrong, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            state = root / "state"
            with self.assertRaisesRegex(SourceSelectionError, "target-conflict"):
                stage_superpowers_source(
                    source,
                    target,
                    report["inventoryHash"],
                    allow_compatible_link=True,
                    state_root=state,
                    migration_journal=state / "source-migrations/superpowers.json",
                    migration_backup=state / "source-migrations/backups/link",
                )

            target.unlink()
            target.symlink_to(source / "skills", target_is_directory=True)
            with self.assertRaisesRegex(SourceSelectionError, "migration-path-invalid"):
                stage_superpowers_source(
                    source,
                    target,
                    report["inventoryHash"],
                    allow_compatible_link=True,
                    state_root=state,
                    migration_journal=state / "source-migrations/superpowers.json",
                    migration_backup=source / "backup-link",
                )

            with mock.patch("selfworkflow.sources._same_volume", return_value=False):
                with self.assertRaisesRegex(SourceSelectionError, "migration-path-invalid"):
                    stage_superpowers_source(
                        source,
                        target,
                        report["inventoryHash"],
                        allow_compatible_link=True,
                        state_root=state,
                        migration_journal=state / "source-migrations/superpowers.json",
                        migration_backup=state / "source-migrations/backups/link",
                    )

    def test_migration_failure_restores_link_and_commit_closes_recovery(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            state = root / "state"
            target = root / "agents/skills/superpowers"
            target.parent.mkdir(parents=True)
            try:
                target.symlink_to(source / "skills", target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            journal = state / "source-migrations/superpowers.json"
            backup = state / "source-migrations/backups/link"

            with mock.patch(
                "selfworkflow.sources.shutil.copyfile",
                side_effect=OSError("copy failed"),
            ):
                with self.assertRaises(OSError):
                    stage_superpowers_source(
                        source,
                        target,
                        report["inventoryHash"],
                        allow_compatible_link=True,
                        state_root=state,
                        migration_journal=journal,
                        migration_backup=backup,
                    )
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), (source / "skills").resolve())

            stage_superpowers_source(
                source,
                target,
                report["inventoryHash"],
                allow_compatible_link=True,
                state_root=state,
                migration_journal=journal,
                migration_backup=backup,
            )
            committed = commit_superpowers_migration(journal)
            self.assertEqual(committed["status"], "committed")
            self.assertEqual(
                recover_superpowers_migration(journal)["status"], "committed"
            )
            self.assertFalse(target.is_symlink())

    def test_recovery_validates_backup_before_removing_staged_target(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            state = root / "state"
            target = root / "agents/skills/superpowers"
            target.parent.mkdir(parents=True)
            try:
                target.symlink_to(source / "skills", target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            journal = state / "source-migrations/superpowers.json"
            backup = state / "source-migrations/backups/link"
            stage_superpowers_source(
                source,
                target,
                report["inventoryHash"],
                allow_compatible_link=True,
                state_root=state,
                migration_journal=journal,
                migration_backup=backup,
                protected_roots=(root / "agents", root / "codex", root / "artifact"),
            )
            backup.unlink()

            with self.assertRaisesRegex(SourceSelectionError, "migration-backup-drift"):
                recover_superpowers_migration(journal)

            self.assertTrue((target / "brainstorming/SKILL.md").is_file())

    def test_recovery_rejects_tampered_journal_paths_without_touching_target(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            state = root / "state"
            target = root / "agents/skills/superpowers"
            target.parent.mkdir(parents=True)
            try:
                target.symlink_to(source / "skills", target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            journal = state / "source-migrations/superpowers.json"
            stage_superpowers_source(
                source,
                target,
                report["inventoryHash"],
                allow_compatible_link=True,
                state_root=state,
                migration_journal=journal,
                migration_backup=state / "source-migrations/backups/link",
                protected_roots=(root / "agents", root / "codex", root / "artifact"),
            )
            intent = json.loads(journal.read_text(encoding="utf-8"))
            intent["backup"] = str(source / "hostile-backup")
            journal.write_text(json.dumps(intent), encoding="utf-8")

            with self.assertRaisesRegex(SourceSelectionError, "migration-journal-invalid"):
                recover_superpowers_migration(journal)

            self.assertTrue((target / "brainstorming/SKILL.md").is_file())

    def test_prepared_intent_with_original_link_is_safely_closed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            state = root / "state"
            target = root / "agents/skills/superpowers"
            target.parent.mkdir(parents=True)
            try:
                target.symlink_to(source / "skills", target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            journal = state / "source-migrations/superpowers.json"
            backup = state / "source-migrations/backups/link"
            stage_superpowers_source(
                source,
                target,
                report["inventoryHash"],
                allow_compatible_link=True,
                state_root=state,
                migration_journal=journal,
                migration_backup=backup,
            )
            recover_superpowers_migration(journal)
            intent = json.loads(journal.read_text(encoding="utf-8"))
            intent["phase"] = "prepared"
            journal.write_text(json.dumps(intent), encoding="utf-8")

            result = recover_superpowers_migration(journal)

            self.assertEqual(result["status"], "restored")
            self.assertTrue(target.is_symlink())

    def test_recovery_and_staging_reject_lexical_reparse_paths(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            state = root / "state"
            target = root / "agents/skills/superpowers"
            target.parent.mkdir(parents=True)
            try:
                target.symlink_to(source / "skills", target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            journal = state / "source-migrations/superpowers.json"
            stage_superpowers_source(
                source,
                target,
                report["inventoryHash"],
                allow_compatible_link=True,
                state_root=state,
                migration_journal=journal,
                migration_backup=state / "source-migrations/backups/link",
            )
            alias = root / "journal-alias"
            alias.symlink_to(state / "source-migrations", target_is_directory=True)
            with self.assertRaisesRegex(SourceSelectionError, "reparse-path-rejected"):
                recover_superpowers_migration(alias / "superpowers.json")
            self.assertTrue((target / "brainstorming/SKILL.md").is_file())

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            real_state = root / "real-state"
            real_state.mkdir()
            state_alias = root / "state-alias"
            try:
                state_alias.symlink_to(real_state, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            target = root / "agents/skills/superpowers"
            target.parent.mkdir(parents=True)
            target.symlink_to(source / "skills", target_is_directory=True)
            with self.assertRaisesRegex(SourceSelectionError, "reparse-path-rejected"):
                stage_superpowers_source(
                    source,
                    target,
                    report["inventoryHash"],
                    allow_compatible_link=True,
                    state_root=state_alias,
                    migration_journal=state_alias / "source-migrations/superpowers.json",
                    migration_backup=state_alias / "source-migrations/backups/link",
                )
            self.assertTrue(target.is_symlink())

    def test_remove_staged_target_requires_exact_inventory_and_refuses_drift(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            skill = source / "skills/brainstorming/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm\n", encoding="utf-8")
            _commit(source)
            report = inspect_superpowers_source(source)
            target = root / "agents/skills/superpowers"
            stage_superpowers_source(source, target, report["inventoryHash"])
            (target / "brainstorming/SKILL.md").write_text(
                "user drift\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(SourceSelectionError, "staged-target-drift"):
                remove_staged_superpowers_source(target, report["inventoryHash"])
            self.assertTrue(target.exists())

            (target / "brainstorming/SKILL.md").write_text(
                "brainstorm\n", encoding="utf-8"
            )
            removed = remove_staged_superpowers_source(
                target, report["inventoryHash"]
            )
            self.assertEqual(removed["status"], "removed")
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
