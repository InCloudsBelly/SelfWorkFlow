"""Small, deterministic hashing and path primitives for V3 provider artifacts."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable


HASH_PREFIX = "sha256:"


class HashingError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise HashingError("canonical-value-invalid") from None


def hash_bytes(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise HashingError("hash-bytes-invalid")
    return HASH_PREFIX + sha256(value).hexdigest()


def content_hash(value: Any) -> str:
    return hash_bytes(canonical_bytes(value))


def clone(value: Any) -> Any:
    return json.loads(canonical_bytes(value))


def require_hash(value: object, reason: str = "hash-invalid") -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith(HASH_PREFIX):
        raise HashingError(reason)
    try:
        int(value[7:], 16)
    except ValueError:
        raise HashingError(reason) from None
    return value


def canonical_project_root(value: str | Path) -> Path:
    """Resolve one existing, non-reparse directory without broad path discovery."""

    try:
        path = Path(value)
        if not path.is_absolute():
            raise HashingError("project-root-not-absolute")
        # Inspect the user-supplied path before resolving it.  Resolving first
        # would make a symlink disappear from the evidence we are checking.
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise HashingError("project-root-reparse")
        resolved = path.resolve(strict=True)
        if not resolved.is_dir() or resolved.is_symlink():
            raise HashingError("project-root-not-directory")
        current = Path(resolved.anchor)
        for part in resolved.parts[1:]:
            current /= part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise HashingError("project-root-reparse")
        return resolved
    except HashingError:
        raise
    except (OSError, ValueError, TypeError):
        raise HashingError("project-root-invalid") from None


def project_root_hash(root: str | Path) -> str:
    path = canonical_project_root(root)
    return content_hash({"kind": "canonical-project-root", "path": os.path.normcase(str(path))})


def canonical_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise HashingError("project-path-invalid")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in parts):
        raise HashingError("project-path-invalid")
    if value.startswith(("/", "\\")) or ":" in value or any(ord(c) < 32 for c in value):
        raise HashingError("project-path-invalid")
    return "/".join(parts)


def hash_file_content(path: str | Path, *, max_bytes: int = 1024 * 1024 * 1024) -> tuple[int, str]:
    """Read one regular file, bounded by size, for an injected/test workspace observer."""

    try:
        target = Path(path)
        info = target.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise HashingError("workspace-file-invalid")
        with target.open("rb") as stream:
            data = stream.read(max_bytes + 1)
        if len(data) != info.st_size or len(data) > max_bytes:
            raise HashingError("workspace-file-changed")
        return info.st_size, hash_bytes(data)
    except HashingError:
        raise
    except (OSError, ValueError):
        raise HashingError("workspace-file-unreadable") from None


def hash_items(items: Iterable[Any]) -> str:
    return content_hash(list(items))
