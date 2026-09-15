import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from selfworkflow.v3.submodule_profiles import (
    SubmoduleProfileError,
    _native,
    _restore_submodules,
    apply_submodule_profile,
    commands_for_profile,
)


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["GIT_ALLOW_PROTOCOL"] = "file"
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True,
        text=True, encoding="utf-8", env=env,
    )


def _file_transport_runner(command, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Test-only runner for the local bare remotes created by this fixture."""

    env = dict(os.environ)
    env["GIT_ALLOW_PROTOCOL"] = "file"
    return subprocess.run(
        list(command), cwd=cwd, check=False, capture_output=True,
        text=True, encoding="utf-8", errors="strict", env=env,
    )


def _commit_file(repository: Path, value: str) -> str:
    (repository / "content.txt").write_text(value, encoding="utf-8")
    _git(repository, "add", "content.txt")
    _git(repository, "commit", "-m", value)
    return _git(repository, "rev-parse", "HEAD").stdout.strip()


class SubmoduleProfileTests(unittest.TestCase):
    def test_native_git_scrubs_repository_locator_environment(self):
        from subprocess import CompletedProcess

        environment = {
            "GIT_DIR": "foreign-git",
            "GIT_WORK_TREE": "foreign-worktree",
            "GIT_INDEX_FILE": "foreign-index",
            "GIT_CONFIG_GLOBAL": "foreign-config",
        }
        with mock.patch.dict(os.environ, environment, clear=False), mock.patch(
            "selfworkflow.v3.submodule_profiles.subprocess.run",
            return_value=CompletedProcess(["git"], 0, "", ""),
        ) as run:
            _native(("git", "status"), Path.cwd())

        command = run.call_args.args[0]
        used_environment = run.call_args.kwargs["env"]
        self.assertIn("core.hooksPath=NUL", command)
        self.assertIn("core.autocrlf=true", command)
        self.assertNotIn("GIT_DIR", used_environment)
        self.assertNotIn("GIT_WORK_TREE", used_environment)
        self.assertNotIn("GIT_INDEX_FILE", used_environment)
        self.assertEqual(used_environment["GIT_CONFIG_NOSYSTEM"], "1")

    def test_submodule_rollback_reports_failed_restore_or_postcondition(self):
        root = Path(tempfile.mkdtemp(prefix="selfworkflow-submodule-rollback-"))
        try:
            existing = root / "existing"
            existing.mkdir()
            (existing / ".git").write_text("gitdir\n", encoding="utf-8")
            states = {"existing": ("b" * 40, "a" * 40, None, None)}

            def failed_runner(command, _cwd):
                if "checkout" in command:
                    return subprocess.CompletedProcess(command, 1, "", "failed")
                return subprocess.CompletedProcess(command, 1, "", "failed")

            self.assertFalse(_restore_submodules(states, root, failed_runner))
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_submodule_rollback_reattaches_the_original_branch(self):
        root = Path(tempfile.mkdtemp(prefix="selfworkflow-submodule-branch-"))
        try:
            existing = root / "existing"
            existing.mkdir()
            (existing / ".git").write_text("gitdir\n", encoding="utf-8")
            states = {"existing": ("b" * 40, "a" * 40, "refs/heads/feature", None)}
            calls = []

            def successful_runner(command, _cwd):
                calls.append(tuple(command))
                if "symbolic-ref" in command:
                    return subprocess.CompletedProcess(command, 0, "refs/heads/feature\n", "")
                if command[-2:] == ("--get", "submodule.existing.url"):
                    return subprocess.CompletedProcess(command, 1, "", "")
                if "rev-parse" in command:
                    return subprocess.CompletedProcess(command, 0, "a" * 40 + "\n", "")
                return subprocess.CompletedProcess(command, 0, "", "")

            self.assertTrue(_restore_submodules(states, root, successful_runner))
            self.assertIn(
                ("git", "-C", "existing", "checkout", "feature"), calls
            )
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_normal_profile_commands_are_path_limited_and_never_remote(self):
        commands = commands_for_profile("normal")
        flattened = " ".join(part for command in commands for part in command)
        self.assertIn("dependencies/upstream/tea", flattened)
        self.assertIn("dependencies/upstream/matt-pocock-skills", flattened)
        self.assertIn("dependencies/upstream/graft", flattened)
        self.assertIn("dependencies/upstream/ponytail", flattened)
        self.assertNotIn("dependencies/heavy", flattened)
        self.assertNotIn("--remote", flattened)
        with self.assertRaisesRegex(SubmoduleProfileError, "submodule-profile-invalid"):
            commands_for_profile("everything")
        root = Path(__file__).resolve().parents[2]
        script = (root / "scripts/install-selfworkflow.ps1").read_text(encoding="utf-8")
        batch = (root / "Install_SelfWorkFlow.bat").read_text(encoding="utf-8")
        self.assertIn("selfworkflow.v3.submodule_profiles", script)
        self.assertNotIn("submodule update --remote", script)
        self.assertNotIn("dependencies/heavy", script)
        self.assertIn("PonytailLockPath", script)
        self.assertIn('"source", "ponytail-verify"', script)
        self.assertIn("preserved-existing-binding", script)
        self.assertIn("GIT_TERMINAL_PROMPT=0", batch)

    def test_clone_repeat_gitlink_update_offline_rollback_and_heavy_isolation(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            tea_source = root / "tea-source"
            tea_source.mkdir()
            _git(tea_source, "init")
            _git(tea_source, "config", "user.email", "tests@example.invalid")
            _git(tea_source, "config", "user.name", "SelfWorkflow Tests")
            first = _commit_file(tea_source, "first")
            second = _commit_file(tea_source, "second")
            tea_remote = root / "tea.git"
            _git(root, "clone", "--bare", str(tea_source), str(tea_remote))

            parent = root / "parent"
            parent.mkdir()
            _git(parent, "init")
            _git(parent, "config", "user.email", "tests@example.invalid")
            _git(parent, "config", "user.name", "SelfWorkflow Tests")
            _git(parent, "-c", "protocol.file.allow=always", "submodule", "add", str(tea_remote), "dependencies/upstream/tea")
            _git(parent / "dependencies/upstream/tea", "checkout", "--detach", first)
            _git(parent, "-c", "protocol.file.allow=always", "submodule", "add", str(tea_remote), "dependencies/upstream/matt-pocock-skills")
            _git(parent / "dependencies/upstream/matt-pocock-skills", "checkout", "--detach", first)
            _git(parent, "-c", "protocol.file.allow=always", "submodule", "add", str(tea_remote), "dependencies/upstream/graft")
            _git(parent / "dependencies/upstream/graft", "checkout", "--detach", first)
            _git(parent, "-c", "protocol.file.allow=always", "submodule", "add", str(tea_remote), "dependencies/upstream/ponytail")
            _git(parent / "dependencies/upstream/ponytail", "checkout", "--detach", first)
            _git(parent, "add", ".gitmodules", "dependencies/upstream/tea", "dependencies/upstream/matt-pocock-skills", "dependencies/upstream/graft", "dependencies/upstream/ponytail")
            _git(parent, "commit", "-m", "pin first")
            parent_remote = root / "parent.git"
            _git(root, "clone", "--bare", str(parent), str(parent_remote))

            clone = root / "clone"
            _git(root, "clone", str(parent_remote), str(clone))
            first_result = apply_submodule_profile(
                clone, "normal", runner=_file_transport_runner,
            )
            self.assertEqual(first_result["status"], "ready")
            self.assertEqual(_git(clone / "dependencies/upstream/tea", "rev-parse", "HEAD").stdout.strip(), first)
            self.assertEqual(_git(clone / "dependencies/upstream/matt-pocock-skills", "rev-parse", "HEAD").stdout.strip(), first)
            self.assertEqual(_git(clone / "dependencies/upstream/graft", "rev-parse", "HEAD").stdout.strip(), first)
            self.assertEqual(_git(clone / "dependencies/upstream/ponytail", "rev-parse", "HEAD").stdout.strip(), first)
            self.assertFalse((clone / "dependencies/heavy").exists())
            self.assertEqual(
                apply_submodule_profile(
                    clone, "normal", runner=_file_transport_runner,
                )["status"],
                "ready",
            )

            _git(parent / "dependencies/upstream/tea", "checkout", "--detach", second)
            _git(parent, "add", "dependencies/upstream/tea")
            _git(parent, "commit", "-m", "pin second")
            _git(parent, "push", str(parent_remote), "HEAD")
            _git(clone, "pull", "--ff-only", "--recurse-submodules=no")
            apply_submodule_profile(
                clone, "normal", runner=_file_transport_runner,
            )
            self.assertEqual(_git(clone / "dependencies/upstream/tea", "rev-parse", "HEAD").stdout.strip(), second)
            self.assertEqual(_git(clone / "dependencies/upstream/matt-pocock-skills", "rev-parse", "HEAD").stdout.strip(), first)
            self.assertEqual(_git(clone / "dependencies/upstream/graft", "rev-parse", "HEAD").stdout.strip(), first)
            self.assertEqual(_git(clone / "dependencies/upstream/ponytail", "rev-parse", "HEAD").stdout.strip(), first)

            third = _commit_file(tea_source, "offline-only")
            _git(parent / "dependencies/upstream/tea", "fetch", str(tea_source), third)
            _git(parent / "dependencies/upstream/tea", "checkout", "--detach", third)
            _git(parent, "add", "dependencies/upstream/tea")
            _git(parent, "commit", "-m", "pin unavailable")
            _git(parent, "push", str(parent_remote), "HEAD")
            pulled = _git(clone, "pull", "--ff-only", "--recurse-submodules=no", check=False)
            self.assertEqual(pulled.returncode, 0, pulled.stderr)
            with self.assertRaisesRegex(SubmoduleProfileError, "submodule-update-failed"):
                apply_submodule_profile(
                    clone, "normal", runner=_file_transport_runner,
                )
            self.assertEqual(_git(clone / "dependencies/upstream/tea", "rev-parse", "HEAD").stdout.strip(), second)
            self.assertEqual(_git(clone / "dependencies/upstream/matt-pocock-skills", "rev-parse", "HEAD").stdout.strip(), first)
            self.assertEqual(_git(clone / "dependencies/upstream/graft", "rev-parse", "HEAD").stdout.strip(), first)
            self.assertEqual(_git(clone / "dependencies/upstream/ponytail", "rev-parse", "HEAD").stdout.strip(), first)
            self.assertFalse((clone / "dependencies/heavy").exists())


if __name__ == "__main__":
    unittest.main()
