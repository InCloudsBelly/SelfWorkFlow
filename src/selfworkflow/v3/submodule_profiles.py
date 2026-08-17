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
_NORMAL_PATHS = (_TEA_PATH, _MATT_SKILLS_PATH)


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
    return subprocess.run(
        list(command), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="strict", check=False, env=os.environ.copy(),
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
    states: dict[str, tuple[str, str | None]] = {}
    for submodule_path in _NORMAL_PATHS:
        listing = runner(
            ("git", "ls-files", "--stage", "--", submodule_path), root
        )
        fields = listing.stdout.strip().split() if listing.returncode == 0 else []
        if len(fields) < 2 or fields[0] != "160000":
            raise SubmoduleProfileError("submodule-gitlink-invalid")
        previous_commit: str | None = None
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
        states[submodule_path] = (fields[1], previous_commit)

    failed = False
    for command in commands:
        result = runner(command, root)
        if result.returncode != 0:
            failed = True
            break
    if failed:
        for submodule_path, (_, previous_commit) in states.items():
            if previous_commit:
                runner(
                    (
                        "git", "-C", submodule_path, "checkout", "--detach",
                        previous_commit,
                    ),
                    root,
                )
            else:
                runner(
                    ("git", "submodule", "deinit", "-f", "--", submodule_path),
                    root,
                )
        raise SubmoduleProfileError("submodule-update-failed")

    commits: dict[str, str] = {}
    for submodule_path, (target_commit, previous_commit) in states.items():
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
            for restore_path, (_, restore_commit) in states.items():
                if restore_commit:
                    runner(
                        (
                            "git", "-C", restore_path, "checkout", "--detach",
                            restore_commit,
                        ),
                        root,
                    )
            raise SubmoduleProfileError("submodule-postcondition-invalid")
        commits[submodule_path] = target_commit
    return {
        "status": "ready",
        "profile": profile,
        "paths": list(_NORMAL_PATHS),
        "commit": commits[_TEA_PATH],
        "commits": commits,
    }


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
