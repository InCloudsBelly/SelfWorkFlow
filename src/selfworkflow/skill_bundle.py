"""Keep the cloneable repository Skill and its installable copy current."""

from __future__ import annotations

import hashlib
from contextlib import ExitStack
from pathlib import Path
import re
import tempfile

import yaml

from selfworkflow.documents import (
    DocumentError, _bound_release, _collect, _publication_lock, _publish_documents,
    _read_release, _revision, _safe, _validate_links, document_binding,
)
from selfworkflow.installer import _atomic_write


_ROUTE = "skills/selfworkflow/references/public/WORKFLOW.md"
_VERSION = re.compile(r"(?m)^规则版本：[^\r\n]*(?:\r?\n|$)")


def _versioned_entry(raw: bytes, revision: str) -> bytes:
    text = raw.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    version = f"规则版本：`{revision[:12]}`{newline}"
    matches = list(_VERSION.finditer(text))
    if len(matches) > 1:
        raise DocumentError("skill-version-invalid")
    if matches:
        text = _VERSION.sub(lambda _: version, text)
    else:
        text = text.rstrip("\r\n") + newline * 2 + version
    return text.encode("utf-8")


def _entries(source: Path) -> tuple[bytes, bytes]:
    try:
        raw = _safe(source / "SKILL.md").read_bytes()
        text = raw.decode("utf-8")
        front = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
        metadata = yaml.safe_load(front[1]) if front else None
    except (OSError, UnicodeError, yaml.YAMLError):
        raise DocumentError("skill-entry-missing-or-invalid") from None
    if not isinstance(metadata, dict) or metadata.get("name") != "selfworkflow" or not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
        raise DocumentError("skill-entry-invalid")
    if text.count(f"]({_ROUTE})") != 1:
        raise DocumentError("skill-entry-route-invalid")
    portable = text.replace(f"]({_ROUTE})", "](references/public/WORKFLOW.md)")
    return raw, portable.encode("utf-8")


def _source_files(source: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="selfworkflow-skill-source-") as folder:
        return _collect(source, Path(folder))


def check_skill(repository_root: str | Path) -> dict:
    source = _safe(Path(repository_root).absolute())
    root_entry, portable = _entries(source)
    target = _safe(source / "skills/selfworkflow/SKILL.md")
    if not target.is_file() or target.read_bytes() != portable:
        raise DocumentError("skill-entry-drift")
    expected = _revision(_source_files(source))
    binding = document_binding(source / "skills/selfworkflow/references/public")
    if binding["revision"] != expected:
        raise DocumentError("skill-bundle-stale")
    if document_binding(source / "public")["revision"] != expected:
        raise DocumentError("skill-public-entry-stale")
    if _versioned_entry(root_entry, expected) != root_entry:
        raise DocumentError("skill-version-stale")
    for release in Path(binding["documentRoot"]).parent.iterdir():
        if release.is_dir() and re.fullmatch(r"[0-9a-f]{64}", release.name) and release.name != expected:
            if _revision(_read_release(release)) != release.name:
                raise DocumentError("skill-retained-release-drift")
            _validate_links(release)
    return {"status": "verified", "revision": expected, "entry": str(source / "SKILL.md"), "documentRoot": binding["documentRoot"]}


def sync_skill(repository_root: str | Path) -> dict:
    source = _safe(Path(repository_root).absolute())
    root_entry, portable = _entries(source)
    with _publication_lock(source / "selfworkflow-skill"), ExitStack() as locks:
        outputs = (source / "skills/selfworkflow/references/public", source / "public")
        # Refuse busy or damaged destinations before switching either entry.
        for output in outputs:
            locks.enter_context(_publication_lock(output))
            if (output / "WORKFLOW.md").exists():
                _bound_release(output)
        target = _safe(source / "skills/selfworkflow/SKILL.md")
        before = target.read_bytes() if target.exists() else None
        files = _source_files(source)
        revision = _revision(files)
        versioned = _versioned_entry(root_entry, revision)
        portable = _versioned_entry(portable, revision)
        result = _publish_documents(source, outputs[0], files=files, _already_locked=True)
        # Both entry points receive one collected snapshot, never two source reads.
        _publish_documents(source, outputs[1], files=files, _already_locked=True)
        if (source / "SKILL.md").read_bytes() != root_entry:
            raise DocumentError("skill-source-entry-drift")
        _atomic_write(source / "SKILL.md", versioned, expected_state=(
            True, "sha256:" + hashlib.sha256(root_entry).hexdigest(),
        ))
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, portable, expected_state=(
            before is not None,
            "sha256:" + hashlib.sha256(before).hexdigest() if before is not None else None,
        ))
        verified = check_skill(source)
    return {**result, "status": "synchronized", "skillEntry": verified["entry"]}
