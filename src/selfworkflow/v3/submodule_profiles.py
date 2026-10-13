"""Path-limited Git submodule preparation for the normal dependency profile."""

from __future__ import annotations

import os
import argparse
import json
from pathlib import Path
import subprocess
from typing import Callable, Sequence


_TEA_PATH = "dependencies/upstream/tea"
_MATT_SKILLS_PATH = "dependencies/upstream/matt-pocock-skills"
_PONYTAIL_PATH = "dependencies/upstream/ponytail"
_ANTHROPIC_PATH = "dependencies/upstream/anthropic-skills"
_NORMAL_PATHS = (
    _TEA_PATH, _MATT_SKILLS_PATH, _PONYTAIL_PATH, _ANTHROPIC_PATH,
    "dependencies/upstream/ui-ux-pro-max", "dependencies/upstream/composio-skills",
    "dependencies/upstream/obsidian-skills",
)


class SubmoduleProfileError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def commands_for_profile(profile: str) -> tuple[tuple[str, ...], ...]:
    if profile != "normal":
        raise SubmoduleProfileError("submodule-profile-invalid")
    return tuple(
        command
        for path in _NORMAL_PATHS
        for command in (
            ("git", "submodule", "sync", "--", path),
            ("git", "submodule", "update", "--init", "--", path),
        )
    )


def _native(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("GIT_CONFIG") or key in {
            "GIT_ATTR_NOSYSTEM", "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS",
            "GIT_SSH_COMMAND", "GIT_SSH", "GIT_ASKPASS", "GIT_EXEC_PATH",
            "GIT_PROXY_COMMAND", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
            "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES",
            "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_PREFIX",
        }:
            environment.pop(key, None)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    safe_command = (
        [
            command[0],
            "-c", "core.hooksPath=NUL",
            "-c", "core.fsmonitor=false",
            "-c", "core.autocrlf=true",
        ]
        + list(command[1:])
    )
    return subprocess.run(
        safe_command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="strict", check=False, env=environment, timeout=120,
    )


def apply_submodule_profile(
    repository: str | Path,
    profile: str = "normal",
    *,
    runner: Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]] = _native,
) -> dict[str, object]:
    """Sync and initialize only allowlisted paths, restoring the old HEAD on failure."""

    commands = commands_for_profile(profile)
    root = Path(repository).resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise SubmoduleProfileError("submodule-repository-invalid")
    states: dict[str, tuple[str, str | None, str | None, str | None]] = {}
    for submodule_path in _NORMAL_PATHS:
        listing = runner(
            ("git", "ls-files", "--stage", "--", submodule_path), root
        )
        fields = listing.stdout.strip().split() if listing.returncode == 0 else []
        if len(fields) < 2 or fields[0] != "160000":
            raise SubmoduleProfileError("submodule-gitlink-invalid")
        config_key = f"submodule.{submodule_path}.url"
        configured_url = runner(
            ("git", "config", "--local", "--get", config_key), root
        )
        if configured_url.returncode not in (0, 1):
            raise SubmoduleProfileError("submodule-config-invalid")
        previous_url = configured_url.stdout.strip() if configured_url.returncode == 0 else None
        previous_commit: str | None = None
        previous_branch: str | None = None
        if (root / submodule_path / ".git").exists():
            head = runner(
                ("git", "-C", submodule_path, "rev-parse", "HEAD"), root
            )
            dirty = runner(
                (
                    "git", "-C", submodule_path, "status", "--porcelain=v1",
                    "--untracked-files=all",
                ),
                root,
            )
            if head.returncode != 0 or dirty.returncode != 0 or dirty.stdout:
                raise SubmoduleProfileError("submodule-dirty")
            previous_commit = head.stdout.strip()
            branch = runner(
                ("git", "-C", submodule_path, "symbolic-ref", "-q", "HEAD"), root
            )
            if branch.returncode not in (0, 1):
                raise SubmoduleProfileError("submodule-state-invalid")
            previous_branch = branch.stdout.strip() if branch.returncode == 0 else None
            if previous_branch is not None and not previous_branch.startswith("refs/heads/"):
                raise SubmoduleProfileError("submodule-state-invalid")
        states[submodule_path] = (fields[1], previous_commit, previous_branch, previous_url)

    failed = False
    for command in commands:
        result = runner(command, root)
        if result.returncode != 0:
            failed = True
            break
    if failed:
        if not _restore_submodules(states, root, runner):
            raise SubmoduleProfileError("submodule-rollback-failed")
        raise SubmoduleProfileError("submodule-update-failed")

    commits: dict[str, str] = {}
    for submodule_path, (target_commit, _, _, _) in states.items():
        head = runner(
            ("git", "-C", submodule_path, "rev-parse", "HEAD"), root
        )
        dirty = runner(
            (
                "git", "-C", submodule_path, "status", "--porcelain=v1",
                "--untracked-files=all",
            ),
            root,
        )
        if (
            head.returncode != 0
            or head.stdout.strip() != target_commit
            or dirty.returncode != 0
            or dirty.stdout
        ):
            if not _restore_submodules(states, root, runner):
                raise SubmoduleProfileError("submodule-rollback-failed")
            raise SubmoduleProfileError("submodule-postcondition-invalid")
        commits[submodule_path] = target_commit
    return {
        "status": "ready",
        "profile": profile,
        "paths": list(_NORMAL_PATHS),
        "commit": commits[_TEA_PATH],
        "commits": commits,
    }


def _restore_submodules(
    states: dict[str, tuple[str, str | None, str | None, str | None]],
    root: Path,
    runner: Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]],
) -> bool:
    rollback_ok = True
    for submodule_path, (_, previous_commit, previous_branch, previous_url) in states.items():
        path = root / submodule_path
        result: subprocess.CompletedProcess[str] | None = None
        if previous_commit:
            result = runner(
                (
                    "git", "-C", submodule_path, "checkout", "--detach",
                    previous_commit,
                ),
                root,
            )
            if result.returncode == 0 and previous_branch:
                result = runner(
                    (
                        "git", "-C", submodule_path, "checkout",
                        previous_branch.removeprefix("refs/heads/"),
                    ),
                    root,
                )
        elif (path / ".git").exists():
            result = runner(
                ("git", "submodule", "deinit", "-f", "--", submodule_path),
                root,
            )
        if result is not None and result.returncode != 0:
            rollback_ok = False
        config_key = f"submodule.{submodule_path}.url"
        if previous_url:
            config_result = runner(
                ("git", "config", "--local", "--replace-all", config_key, previous_url),
                root,
            )
            if config_result.returncode != 0:
                rollback_ok = False
        else:
            runner(
                ("git", "config", "--local", "--unset-all", config_key), root
            )

    for submodule_path, (_, previous_commit, previous_branch, previous_url) in states.items():
        path = root / submodule_path
        if previous_commit:
            head = runner(
                ("git", "-C", submodule_path, "rev-parse", "HEAD"), root
            )
            dirty = runner(
                (
                    "git", "-C", submodule_path, "status", "--porcelain=v1",
                    "--untracked-files=all",
                ),
                root,
            )
            if (
                head.returncode != 0
                or head.stdout.strip() != previous_commit
                or dirty.returncode != 0
                or dirty.stdout
            ):
                rollback_ok = False
            branch = runner(
                ("git", "-C", submodule_path, "symbolic-ref", "-q", "HEAD"), root
            )
            if (
                previous_branch is None and branch.returncode == 0
                or previous_branch is not None
                and (branch.returncode != 0 or branch.stdout.strip() != previous_branch)
            ):
                rollback_ok = False
        elif (path / ".git").exists():
            rollback_ok = False
        config_key = f"submodule.{submodule_path}.url"
        configured_url = runner(
            ("git", "config", "--local", "--get", config_key), root
        )
        if previous_url is None:
            if configured_url.returncode == 0 and configured_url.stdout.strip():
                rollback_ok = False
        elif (
            configured_url.returncode != 0
            or configured_url.stdout.strip() != previous_url
        ):
            rollback_ok = False
    return rollback_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--profile", choices=("normal",), default="normal")
    arguments = parser.parse_args(argv)
    try:
        result = apply_submodule_profile(arguments.repository, arguments.profile)
    except SubmoduleProfileError as error:
        print(json.dumps({"status": "failed", "reason": error.reason}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
