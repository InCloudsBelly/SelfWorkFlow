"""Maintainer-side publication of a self-contained, read-only document tree."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import tempfile
from urllib.parse import unquote
from uuid import uuid4

import yaml


class DocumentError(RuntimeError):
    pass


_MARKER = "<!-- selfworkflow:documents -->"
_LINK = re.compile(r"\[[^\]\n]*\]\(([^)\n]+)\)")
_ENTRY = re.compile(r"\[读取本任务规则\]\((releases/[0-9a-f]{64}/WORKFLOW\.md)\)")
_AGENT_METHODS = frozenset(
    f"references/anthropic-skills/skill-creator/agents/{role}.md"
    for role in ("grader", "comparator", "analyzer")
)


def _safe(path: Path) -> Path:
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400):
            raise DocumentError("document-link-rejected")
    return path.resolve()


def _entry(revision: str) -> str:
    return f"{_MARKER}\n[读取本任务规则](releases/{revision}/WORKFLOW.md)\n"


def _legacy_entry(revision: str) -> str:
    return (
        f"{_MARKER}\n# SelfWorkflow 公共入口\n\n"
        "用户顶层任务实际读取本入口一次，选择下方版本；子任务、独立 Reviewer、阶段切换和上下文续接"
        "继承主任务的 documentRoot 与 revision，不另选 latest。缺失或不一致的绑定应报告委派者。\n\n"
        f"[读取本任务规则](releases/{revision}/WORKFLOW.md)\n\n"
        f"revision: `{revision}`\n\n"
        "链接所在目录即本任务 documentRoot。相对链接从声明它的文件解析；逻辑规则路径以 documentRoot 为根。"
        "只按需读取文档，不运行安装器、构造账本或注册原生 Skill。版本目录不可原地修改；旧任务继续使用原版。\n"
    )


def _revision(files: dict) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode() + b"\0" + (content if isinstance(content, bytes) else content.encode("utf-8")) + b"\0")
    return digest.hexdigest()


def _read_release(root: Path) -> dict:
    root = _safe(root)
    files: dict[str, bytes] = {}
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as directory:
            for item in directory:
                metadata = item.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                    raise DocumentError("document-link-rejected")
                path = Path(item.path)
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(metadata.st_mode):
                    files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _entry_bytes(path: Path) -> bytes | None:
    path = _safe(path)
    return path.read_bytes() if path.exists() else None


def _entry_state(content: bytes | None) -> tuple[bool, str | None]:
    if content is None:
        return False, None
    return True, "sha256:" + hashlib.sha256(content).hexdigest()


def _read_bound_release(root: Path, content: bytes) -> tuple[Path, dict[str, bytes]]:
    try:
        text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        match = _ENTRY.search(text)
        if match is None or text not in (_entry(match[1].split("/")[1]), _legacy_entry(match[1].split("/")[1])):
            raise DocumentError("document-entry-invalid")
        release = _safe(root / match[1]).parent
        if not (release / "WORKFLOW.md").is_file():
            raise DocumentError("document-release-missing")
        files = _read_release(release)
        if _revision(files) != release.name:
            raise DocumentError("document-release-drift")
    except UnicodeError:
        raise DocumentError("document-entry-invalid") from None
    except OSError:
        raise DocumentError("document-entry-missing") from None
    return release, files


def document_binding(public_root: str | Path) -> dict:
    root = _safe(Path(public_root).absolute())
    entry = root / "WORKFLOW.md"
    try:
        content = _entry_bytes(entry)
    except OSError:
        raise DocumentError("document-entry-missing") from None
    if content is None:
        raise DocumentError("document-entry-missing")
    release, files = _read_bound_release(root, content)
    _validate_links(files)
    return {"revision": release.name, "documentRoot": str(release), "entry": str(entry)}


def render_document_instruction(public_root: str | Path) -> str:
    root = _safe(Path(public_root).absolute())
    return (
        "## SelfWorkflow 文档入口\n\n"
        f"工程开发、修复、代码审查或显式工作流任务，首次读取并遵循 `{(root / 'WORKFLOW.md').as_posix()}`。\n"
        "子任务、独立 Reviewer 和上下文续接继承主任务的文档 revision 与 documentRoot，不重新选择 latest。\n"
        "普通问答、概念讨论和精确本地查询不启动流程；兼容指针在工具内解析，仅返回 revision、documentRoot 与正文。只读命中规则，不读历史安装副本；本入口不内嵌版本化规则。\n"
        "入口或必要能力不可用时报告对应缺口，不虚构执行或验证结果。\n"
    )


def _prose(text: str) -> str:
    return re.sub(r"`+[^`\n]*`+", "", re.sub(r"(?ms)^(```|~~~).*?^\1[^\n]*(?:\n|$)", "", text))


def _relative_reference(path: Path, target: str) -> Path | None:
    reference = Path(unquote(target.split("#", 1)[0]))
    if reference.anchor:
        return None
    parts = list(path.parent.parts)
    for part in reference.parts:
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return Path(*parts)


def _validate_links(files: dict[str, bytes]) -> None:
    # Check the same bytes that were hashed. _read_release rejects all links in
    # the tree, so these portable references can be resolved without filesystem I/O.
    paths = {Path(name): content for name, content in files.items()}
    for path, content in paths.items():
        if not path.match("*.md"):
            continue
        text = content.decode("utf-8")
        if path == Path("WORKFLOW.md"):
            for target in re.findall(r"`((?:workflow/)?(?:modules|modes)/[a-zA-Z0-9_-]+\.md)`", text):
                if Path(target) not in paths:
                    raise DocumentError(f"document-route-missing:{target}")
        for match in _LINK.finditer(_prose(text)):
            target = match[1].strip().strip("<>").split(' "', 1)[0]
            if not target or target.startswith(("#", "http:", "https:", "mailto:", "data:")):
                continue
            if _relative_reference(path, target) not in paths:
                raise DocumentError(f"document-reference-missing:{path}:{target}")


def _method_index(files: dict[str, str]) -> str:
    entries = {}
    for name, text in sorted(files.items(), key=lambda item: (item[0].count("/"), item[0])):
        if not name.startswith("methods/") or not name.endswith("/METHOD.md"):
            continue
        if {"references", "assessments"}.intersection(name.split("/")[1:-1]):
            continue
        front = re.match(r"\A---\n(.*?)\n---", text, re.S)
        meta = yaml.safe_load(front[1]) if front else {}
        if isinstance(meta, dict) and isinstance(meta.get("name"), str):
            entries.setdefault(meta["name"], (name.removeprefix("methods/"), str(meta.get("description", ""))))
    lines = ["# 方法索引", "", "按用户意图和排除条件选择方法；仅读取本任务需要的内容。方法是普通文档，无需原生 Skill 发现。", ""]
    for name, (path, description) in sorted(entries.items()):
        lines.append(f"- [{name}]({path})：{description.replace(chr(10), ' ')}")
    return "\n".join(lines) + "\n"


def _document_name(name: str) -> str:
    target = name.replace("skills/", "methods/", 1) if name.startswith("skills/") else name
    if target.endswith("SKILL.md"):
        target = target.removesuffix("SKILL.md") + "METHOD.md"
    return target if target.endswith(".md") else target + ".md"


def _collect(source: Path, staging: Path) -> dict[str, str | bytes]:
    from selfworkflow.adapters import (
        _copy_tree, _copy_matt_skills, _copy_tea_quality, _copy_ponytail,
        _copy_anthropic_skill_creator, _copy_community_sources,
    )

    shutil.copyfile(source / "WORKFLOW.md", staging / "WORKFLOW.md")
    for relative in ("workflow", "skills", "capabilities", "schemas", "overlays"):
        if (source / relative).is_dir():
            _copy_tree(
                source / relative, staging / relative,
                excluded_roots=(source / "skills/selfworkflow",),
            )
    locks = source / "dependencies/locks"
    for lock, copier in (
        ("matt-pocock-skills", lambda: _copy_matt_skills(source, staging, include_grill_me=True)),
        ("tea", lambda: _copy_tea_quality(source, staging)),
        ("ponytail", lambda: _copy_ponytail(source, staging)),
        ("anthropic-skills", lambda: _copy_anthropic_skill_creator(source, staging)),
        ("ui-ux-pro-max", lambda: _copy_community_sources(source, staging)),
    ):
        if (locks / f"{lock}.lock.yaml").is_file():
            copier()
    wiki = source / "extensions/knowledge/selfopenwiki"
    if wiki.is_dir():
        for path in (wiki / "WIKI_LAYOUT.md",):
            if not path.is_file():
                continue
            target = staging / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)

    # Only documents are public; linked data/templates become fenced, read-only reference text.
    paths = {p.relative_to(staging).as_posix(): p for p in staging.rglob("*") if p.is_file()}
    mapping = {}
    for name in paths:
        if name.startswith("workflow/skills/"):
            continue  # Local entries were already published by the curated importer.
        if "/agents/" in name and name not in _AGENT_METHODS:
            continue
        if name.startswith("references/community-skills/ui-ux-pro-max/") and Path(name).suffix.lower() in {".py", ".csv", ".json", ".yaml", ".yml", ".txt"}:
            mapping[name] = name  # The UI search tool consumes the pinned original files.
        elif Path(name).suffix.lower() in {".md", ".csv", ".json", ".yaml", ".yml", ".txt", ".xml", ".toml"} or Path(name).name.startswith("LICENSE"):
            mapping[name] = _document_name(name)
    files = {}
    pending = list(mapping)
    while pending:
        name = pending.pop()
        path = paths[name]
        if mapping[name] == name and name.startswith("references/community-skills/ui-ux-pro-max/"):
            # The source locks compare canonical LF text; publish the same bytes
            # regardless of the maintainer's submodule checkout configuration.
            files[mapping[name]] = path.read_bytes().replace(b"\r\n", b"\n")
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
            content = path.read_bytes()
            files[mapping[name]] = content.replace(b"\r\n", b"\n") if path.suffix.lower() == ".svg" else content
            continue
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        destination = mapping[name]
        if not name.endswith(".md"):
            files[destination] = f"# 只读参考：{Path(name).name}\n\n此处为资料或模板，不提供可执行程序；实际工具须独立配置。\n\n````text\n{text}\n````\n"
            continue
        if name.startswith("skills/"):
            text = text.replace("bootstrap snapshot 绝对根目录", "documentRoot").replace("当前 snapshot 的", "当前绑定文档版本的")
            text = text.replace("复用 artifact manifest 并核对所需文件 hash", "复用当前文档版本并核对引用完整性")
            text = text.replace("复用 artifact manifest 并核对 hash", "复用当前文档版本并核对引用完整性")
            text = text.replace("复用 artifact-manifest.json，核对所需文件 hash", "复用当前文档版本，核对引用完整性")
            text = text.replace("从 bootstrap 的 snapshot 根按需完整读取", "从 documentRoot 按需完整读取")
            text = text.replace("先用 `artifact-manifest.json` 核对身份与所需 SHA256", "沿用本任务绑定的文档版本并核对引用完整性")
        if name.startswith("skills/tea-quality/"):
            text = re.sub(r"(?m)^If `\{tea-knowledge\}/tea-index\.csv` does not exist,.*$", "If `{tea-knowledge}/tea-index.csv` is missing, report the document dependency as unverified and stop this method; do not install or search another version.", text)
            if name.endswith("/bmad-testarch-atdd/SKILL.md"):
                text = re.sub(r" If any are missing, explain[^\n]+", " If any are missing, report the canonical document dependency as unverified and stop; do not install or search another version. The local headless contract overrides upstream activation, hooks, menus and command execution.", text)
        if name == "references/community-skills/composio-skills/README.md":
            files[destination] = "# 固定来源的许可声明\n\n以下为上游 README 原文，仓库导航不属于本包的操作依赖。\n\n````markdown\n" + text + "\n````\n"
            continue

        def link(match):
            target = match[1].strip().strip("<>")
            if target.startswith(("#", "http:", "https:", "mailto:", "data:")):
                return match[0]
            raw, separator, fragment = target.partition("#")
            if raw.startswith("{project-root}"):
                return match[0].split("](", 1)[0] + f"]（任务项目位置：`{target}`）"
            if raw.startswith("{tea-knowledge}"):
                resolved = raw.replace("{tea-knowledge}", "skills/tea-quality/references/bmod-tea/knowledge", 1)
            elif raw.startswith("{skill-root}"):
                selected = re.match(r"(skills/tea-quality/references/[^/]+)/", name)
                if selected is None:
                    raise DocumentError(f"document-variable-unresolved:{name}:{raw}")
                resolved = raw.replace("{skill-root}", selected[1], 1)
            else:
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(raw)))
            if resolved not in paths:
                for candidate in (resolved + "/SKILL.md", resolved + "/README.md", resolved + "/index.md"):
                    if candidate in paths:
                        resolved = candidate
                        break
            if resolved not in mapping:
                if resolved not in paths:
                    raise DocumentError(f"document-reference-missing:{name}:{target}")
                mapping[resolved] = resolved if paths[resolved].suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"} else _document_name(resolved)
                pending.append(resolved)
            result = posixpath.relpath(mapping[resolved], posixpath.dirname(destination) or ".")
            return match[0].replace(match[1], result + (separator + fragment if separator else ""))

        def code_path(match):
            raw = match[1]
            if raw == "SKILL.md" and not name.startswith("skills/tea-quality/"):
                return match[0]  # Creation guides still create native Skills when explicitly requested.
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), raw))
            if raw.startswith("{tea-knowledge}/"):
                resolved = raw.replace("{tea-knowledge}", "skills/tea-quality/references/bmod-tea/knowledge", 1)
                if resolved in mapping:
                    return "`{tea-knowledge}/" + posixpath.basename(mapping[resolved]) + "`"
            if raw.startswith("{skill-root}/"):
                selected = re.match(r"(skills/tea-quality/references/[^/]+)/", name)
                if selected:
                    canonical = selected[1]
                    resolved = posixpath.normpath(raw.replace("{skill-root}", canonical, 1))
                    if resolved in mapping:
                        target_root = canonical.replace("skills/", "methods/", 1)
                        return "`{skill-root}/" + posixpath.relpath(mapping[resolved], target_root) + "`"
            if raw in mapping:
                return "`" + mapping[raw] + "`"
            if resolved in mapping:
                return "`" + posixpath.relpath(mapping[resolved], posixpath.dirname(destination) or ".") + "`"
            if name.startswith("skills/tea-quality/") and raw == "tea-index.csv":
                return "`tea-index.csv.md`"
            return match[0]

        # Fenced examples and inline example links are not operational references.
        sections = re.split(r"(?ms)(^```.*?^```[^\n]*(?:\n|$)|^~~~.*?^~~~[^\n]*(?:\n|$))", text)
        def rewrite(section):
            inline = re.split(r"(`+[^`\n]*`+)", section)
            result = "".join(re.sub(r"`([^`\n]+)`", code_path, part) if i % 2 else _LINK.sub(link, part) for i, part in enumerate(inline))
            if name.startswith("skills/tea-quality/"):
                result = re.sub(r"(\{tea-knowledge\}/tea-index\.csv)(?!\.md)", r"\1.md", result)
                result = result.replace("{skill-root}/SKILL.md", "{skill-root}/METHOD.md")
            return result
        text = "".join(section if i % 2 else rewrite(section) for i, section in enumerate(sections))
        files[destination] = text
    files["methods/INDEX.md"] = _method_index(files)
    files["DOCUMENTS.md"] = (
        "# 文档使用约定\n\n本目录是完整规则版本，documentRoot 为其根。相对链接从声明文件解析。"
        "方法路由见 [方法索引](methods/INDEX.md)，不依赖原生 Skill。\n\n"
        "通用流程、授权和 Review 调度由 WORKFLOW.md 及其模块管理；来源方法只补充专业方法，"
        "不另起访谈、确认或审查团队，不执行来源中的宿主安装、hooks 或菜单。\n\n"
        "来源方法里的厂商工具、脚本和配置不自动成为当前能力；只使用实际可用且获授权的工具。"
        "UI 检索脚本与其原始数据随包提供，按对应方法核验 Python 和执行授权；本包不部署 MCP、Viewer 或其他外部服务。"
        "不从文档路径猜测未随包的工具；无法执行的必要步骤报告 unverified。"
        "严格 Host 仍须独立提供并验证 runtime/package/receipt，不能以读到文档作为通过。\n"
    )
    files["WORKFLOW.md"] = (
        "documentRoot 为本文件目录，revision 为目录名。\n\n"
        + files["WORKFLOW.md"]
    )
    return files


@contextmanager
def _publication_lock(output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = _safe(output.parent / f".{output.name}.selfworkflow-document-publish.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise DocumentError("document-publisher-locked") from None
    identity = os.fstat(descriptor)
    try:
        yield
    finally:
        os.close(descriptor)
        if lock.exists() and os.path.samestat(identity, lock.stat()):
            lock.unlink()


def _file_bytes(files: dict[str, str | bytes]) -> dict[str, bytes]:
    return {name: content.encode("utf-8") if isinstance(content, str) else content for name, content in files.items()}


def _stage_release(staged: Path, files: dict[str, bytes]) -> None:
    _validate_links(files)
    for name, content in files.items():
        target = staged / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _prepare_release(
    output: Path, staged: Path, revision: str, files: dict[str, bytes],
    previous: tuple[Path, dict[str, bytes]] | None,
) -> Path:
    release = _safe(output / "releases" / revision)
    release.parent.mkdir(parents=True, exist_ok=True)
    if release.exists():
        actual = previous[1] if previous and previous[0] == release else _read_release(release)
        if actual != files:
            raise DocumentError("document-release-drift")
        return release

    # Creating staging at the destination inherits its public Windows ACLs.
    public_staged = release.parent / f".publishing-{uuid4().hex}"
    public_staged.mkdir()
    try:
        shutil.copytree(staged, public_staged, dirs_exist_ok=True, copy_function=shutil.copyfile)
        if _read_release(public_staged) != files:
            raise DocumentError("document-release-drift")
        os.replace(public_staged, release)
    finally:
        if public_staged.exists():
            cleanup = _safe(public_staged)
            if not cleanup.is_relative_to(release.parent):
                raise DocumentError("document-staging-path-invalid")
            shutil.rmtree(cleanup)
    return release


def publish_documents(repository_root: str | Path, output_root: str | Path) -> dict:
    source = _safe(Path(repository_root).absolute())
    output = _safe(Path(output_root).absolute())
    collected_roots = ("workflow", "skills", "capabilities", "schemas", "overlays", "dependencies", "extensions")
    bundled_output = source / "skills/selfworkflow/references/public"
    inside_collected = any(output.is_relative_to(source / relative) for relative in collected_roots)
    if source == output or source.is_relative_to(output) or (inside_collected and output != bundled_output):
        raise DocumentError("document-output-invalid")
    entry = output / "WORKFLOW.md"
    with _publication_lock(output), tempfile.TemporaryDirectory(prefix=".document-publish-", dir=output.parent) as temporary:
        before = _entry_bytes(entry)
        # A new release may repair old routes, but never old content drift.
        previous = _read_bound_release(output, before) if before is not None else None
        temporary_root = Path(temporary)
        source_copy = temporary_root / "source"
        source_copy.mkdir()
        files = _file_bytes(_collect(source, source_copy))
        revision = _revision(files)
        staged = temporary_root / "release"
        _stage_release(staged, files)
        release = _prepare_release(output, staged, revision, files, previous)
        if _entry_bytes(entry) != before:
            raise DocumentError("document-entry-drift")
        from selfworkflow.installer import _atomic_write
        _atomic_write(entry, _entry(revision).encode("utf-8"), expected_state=_entry_state(before))
    return {"status": "published", "revision": revision, "documentRoot": str(release), "entry": str(entry), "documentCount": len(files)}
