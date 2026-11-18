"""Keep the cloneable repository Skill and its installable copy current."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import re
import tempfile

import yaml

from selfworkflow.documents import (
    DocumentError, _collect, _entry, _entry_bytes, _entry_state, _file_bytes,
    _prepare_release, _publication_lock, _read_bound_release, _read_release, _revision,
    _safe, _stage_release, _validate_links, document_binding,
)
from selfworkflow.installer import _atomic_write


_ROUTE = "skills/selfworkflow/references/public/WORKFLOW.md"
_VERSION = re.compile(r"(?m)^规则版本：[^\r\n]*(?:\r?\n|$)")
_CORE_START = "<!-- selfworkflow:core -->"
_CORE_END = "<!-- /selfworkflow:core -->"
_CORE = re.compile(r"(?ms)^<!-- selfworkflow:core -->\r?\n.*?^<!-- /selfworkflow:core -->(?:\r?\n)?")


def _core_entry(raw: bytes, revision: str, core: str, public: str) -> bytes:
    if _CORE_START in core or _CORE_END in core:
        raise DocumentError("skill-core-invalid")
    text = raw.decode("utf-8")
    if text.count(_CORE_START) != text.count(_CORE_END) or text.count(_CORE_START) > 1:
        raise DocumentError("skill-core-invalid")
    if _CORE_START in text and not _CORE.search(text):
        raise DocumentError("skill-core-invalid")
    newline = "\r\n" if "\r\n" in text else "\n"
    core = core.removeprefix("documentRoot 为本文件目录，revision 为目录名。\n\n")
    prefix = f"{public}/releases/{revision}/"
    core = re.sub(
        r"\[([^\]\n]+)\]\(([^)]+)\)",
        lambda match: match[0] if match[2].startswith(("#", "http:", "https:", "mailto:"))
        else f"{match[1]}（`{match[2]}`）",
        core,
    )
    block = (
        f"{_CORE_START}\n"
        f"无需再读公共转发页。[绑定规则源]({prefix}WORKFLOW.md)的目录为 documentRoot，"
        "目录名为 revision；子任务/续接沿用。下文文件路径相对 documentRoot（项目配置相对项目根）。\n\n"
        f"{core.rstrip()}\n{_CORE_END}\n"
    )
    return (_CORE.sub("", text).rstrip("\r\n") + newline * 2 + block.replace("\n", newline)).encode("utf-8")


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
    portable = portable.replace(
        "](skills/selfworkflow/references/public/releases/", "](references/public/releases/",
    )
    return raw, portable.encode("utf-8")


def _source_files(source: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="selfworkflow-skill-source-") as folder:
        return _collect(source, Path(folder))


def _check_retained_releases(
    folder: Path, revision: str, previous: tuple[Path, dict[str, bytes]] | None = None,
) -> None:
    if not folder.exists():
        return
    for release in _safe(folder).iterdir():
        if release.name == revision or not re.fullmatch(r"[0-9a-f]{64}", release.name) or not release.is_dir():
            continue
        if previous and release == previous[0]:
            files = previous[1]
        else:
            files = _read_release(release)
            if _revision(files) != release.name:
                raise DocumentError("skill-retained-release-drift")
        _validate_links(files)


def check_skill(repository_root: str | Path, *, current_only: bool = False) -> dict:
    source = _safe(Path(repository_root).absolute())
    root_entry, portable = _entries(source)
    target = _safe(source / "skills/selfworkflow/SKILL.md")
    if not target.is_file() or target.read_bytes() != portable:
        raise DocumentError("skill-entry-drift")
    files = _source_files(source)
    expected = _revision(files)
    binding = document_binding(source / "skills/selfworkflow/references/public")
    if binding["revision"] != expected:
        raise DocumentError("skill-bundle-stale")
    if document_binding(source / "public")["revision"] != expected:
        raise DocumentError("skill-public-entry-stale")
    if _versioned_entry(root_entry, expected) != root_entry:
        raise DocumentError("skill-version-stale")
    if _core_entry(root_entry, expected, files["WORKFLOW.md"], "skills/selfworkflow/references/public") != root_entry:
        raise DocumentError("skill-core-stale")
    if not current_only:
        _check_retained_releases(Path(binding["documentRoot"]).parent, expected)
    return {"status": "verified", "revision": expected, "entry": str(source / "SKILL.md"), "documentRoot": binding["documentRoot"]}


def _switch_entries(source: Path, updates: list[tuple[Path, bytes | None, bytes]]) -> None:
    for path, before, _ in updates:
        if _entry_bytes(path) != before:
            raise DocumentError(f"skill-entry-drift:{path.relative_to(source)}")
    attempted = []
    try:
        for path, before, after in updates:
            if before != after:
                attempted.append((path, before, after))
            _atomic_write(path, after, expected_state=_entry_state(before))
    except (Exception, KeyboardInterrupt) as error:
        failed = []
        for path, before, after in reversed(attempted):
            try:
                current = _entry_bytes(path)
                if current == before:
                    continue
                if current != after:
                    raise DocumentError("skill-entry-drift")
                if before is None:
                    path.unlink()
                else:
                    _atomic_write(path, before, expected_state=_entry_state(after))
            except Exception:
                failed.append(path.relative_to(source).as_posix())
        if failed:
            raise DocumentError("skill-entry-rollback-failed:" + ",".join(failed)) from error
        raise


def sync_skill(repository_root: str | Path) -> dict:
    source = _safe(Path(repository_root).absolute())
    root_entry, portable = _entries(source)
    with _publication_lock(source / "selfworkflow-skill"), ExitStack() as locks:
        outputs = (source / "skills/selfworkflow/references/public", source / "public")
        # Refuse busy or damaged destinations before switching either entry.
        for output in outputs:
            locks.enter_context(_publication_lock(output))
        pointers = [output / "WORKFLOW.md" for output in outputs]
        pointer_bytes = [_entry_bytes(path) for path in pointers]
        previous = [
            _read_bound_release(output, content) if content is not None else None
            for output, content in zip(outputs, pointer_bytes, strict=True)
        ]
        target = _safe(source / "skills/selfworkflow/SKILL.md")
        before = _entry_bytes(target)
        authored = _source_files(source)
        files = _file_bytes(authored)
        revision = _revision(files)
        versioned = _core_entry(
            _versioned_entry(root_entry, revision), revision, authored["WORKFLOW.md"],
            "skills/selfworkflow/references/public",
        )
        portable = _core_entry(
            _versioned_entry(portable, revision), revision, authored["WORKFLOW.md"], "references/public",
        )
        _check_retained_releases(outputs[0] / "releases", revision, previous[0])
        # Prepare both immutable copies from the same verified candidate before
        # changing any entry. A failed switch can leave an unreferenced release.
        with tempfile.TemporaryDirectory(prefix="selfworkflow-skill-release-") as folder:
            staged = Path(folder) / "release"
            _stage_release(staged, files)
            releases = [
                _prepare_release(output, staged, revision, files, active)
                for output, active in zip(outputs, previous, strict=True)
            ]
        pointer = _entry(revision).encode("utf-8")
        _switch_entries(source, [
            *[(path, content, pointer) for path, content in zip(pointers, pointer_bytes, strict=True)],
            (source / "SKILL.md", root_entry, versioned),
            (target, before, portable),
        ])
    return {
        "status": "synchronized", "revision": revision, "documentRoot": str(releases[0]),
        "entry": str(pointers[0]), "documentCount": len(files), "skillEntry": str(source / "SKILL.md"),
    }
