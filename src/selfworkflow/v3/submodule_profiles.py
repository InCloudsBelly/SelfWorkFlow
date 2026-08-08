"""Path-limited Git submodule preparation for the normal dependency profile."""

from __future__ import annotations

import os
import argparse
import json
from pathlib import Path
import subprocess
from typing import Callable, Sequence


_TEA_PATH = "dependencies/upstream/tea"


class SubmoduleProfileError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def commands_for_profile(profile: str) -> tuple[tuple[str, ...], ...]:
    if profile != "normal":
        raise SubmoduleProfileError("submodule-profile-invalid")
    return (
        ("git", "submodule", "sync", "--", _TEA_PATH),
        ("git", "submodule", "update", "--init", "--", _TEA_PATH),
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
    listing = runner(("git", "ls-files", "--stage", "--", _TEA_PATH), root)
    fields = listing.stdout.strip().split() if listing.returncode == 0 else []
    if len(fields) < 2 or fields[0] != "160000":
        raise SubmoduleProfileError("submodule-gitlink-invalid")
    target_commit = fields[1]
    path = root / _TEA_PATH
    previous_commit: str | None = None
    initialized = (path / ".git").exists()
    if initialized:
        head = runner(("git", "-C", _TEA_PATH, "rev-parse", "HEAD"), root)
        dirty = runner(
            ("git", "-C", _TEA_PATH, "status", "--porcelain=v1", "--untracked-files=all"),
            root,
        )
        if head.returncode != 0 or dirty.returncode != 0 or dirty.stdout:
            raise SubmoduleProfileError("submodule-dirty")
        previous_commit = head.stdout.strip()

    failed = False
    for command in commands:
        result = runner(command, root)
        if result.returncode != 0:
            failed = True
            break
    if failed:
        if previous_commit:
            runner(("git", "-C", _TEA_PATH, "checkout", "--detach", previous_commit), root)
        else:
            runner(("git", "submodule", "deinit", "-f", "--", _TEA_PATH), root)
        raise SubmoduleProfileError("submodule-update-failed")

    head = runner(("git", "-C", _TEA_PATH, "rev-parse", "HEAD"), root)
    dirty = runner(
        ("git", "-C", _TEA_PATH, "status", "--porcelain=v1", "--untracked-files=all"),
        root,
    )
    if head.returncode != 0 or head.stdout.strip() != target_commit or dirty.returncode != 0 or dirty.stdout:
        if previous_commit:
            runner(("git", "-C", _TEA_PATH, "checkout", "--detach", previous_commit), root)
        raise SubmoduleProfileError("submodule-postcondition-invalid")
    return {"status": "ready", "profile": profile, "paths": [_TEA_PATH], "commit": target_commit}


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
