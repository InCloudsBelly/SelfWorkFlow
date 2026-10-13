"""Compile vendor-thin adapters and standalone runtime snapshots."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile

from jsonschema import Draft202012Validator
import yaml

from selfworkflow.catalog import compile_catalog
from selfworkflow.host_runtime import build_host_runtime
from selfworkflow.ponytail_source import (
    PonytailSourceError,
    copy_ponytail_skills,
)
from selfworkflow.v3.submodule_profiles import _native as _run_source_git
from selfworkflow.v3.tea_adapter import validate_packaged_runtime, verify_tea_source


class AdapterError(RuntimeError):
    pass


_RUNTIME_PROFILES = {"core", "knowledge", "maintainer"}
_RUNTIME_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")
_CORE_CATALOG_IDS = {
    "workflow-core",
    "workflow-quality",
    "testing-review-quality",
    "tea-quality-foundation",
    "tea-framework",
    "tea-ci",
    "code-quality",
    "matt-skills-foundation",
    "ponytail",
    "ponytail-review",
    "ponytail-audit",
    "ponytail-help",
    "ponytail-debt",
    "implement-spec",
}
_CORE_PATHS = (
    "workflow/core.md",
    "workflow/work-artifact-lifecycle.md",
    "workflow/modes/light.md",
    "workflow/modes/full.md",
    "workflow/modes/deep.md",
    "workflow/modules/code.md",
    "workflow/modules/optional-integrations.md",
    "workflow/modules/codegraph-read.md",
    "workflow/modules/codegraph-update.md",
    "workflow/modules/review.md",
    "workflow/modules/knowledge.md",
    "workflow/modules/artifacts.md",
    "workflow/pipeline.yaml",
    "workflow/git-policy.yaml",
    "workflow/resolve-request.example.json",
    "schemas/pipeline.schema.json",
    "schemas/plan-graph.schema.json",
    "schemas/stage-result.schema.json",
    "schemas/run-ledger.schema.json",
    "schemas/resolve-request.schema.json",
    "schemas/resolve-result.schema.json",
    "schemas/install-plan.schema.json",
    "schemas/install-manifest.schema.json",
    "schemas/rollback-plan.schema.json",
    "schemas/git-policy.schema.json",
    "schemas/project-review-profile.schema.json",
    "schemas/review-model-config.schema.json",
    "schemas/work-artifact-manifest.schema.json",
    "schemas/work-artifact-operation.schema.json",
    "schemas/work-artifact-publication-receipt.schema.json",
    "skills/code-quality",
    "skills/workflow-quality",
    "skills/testing-review-quality",
    "skills/tea-quality",
    "skills/implement-spec",
    "skills/workflow-skill-maintenance",
    "skills/ui-ux-pro-max",
    "skills/content-research-writer",
    "skills/obsidian-markdown",
    "skills/obsidian-bases",
    "skills/json-canvas",
    "capabilities/code-quality",
    "capabilities/workflow-quality",
    "dependencies/locks/matt-pocock-skills.lock.yaml",
    "dependencies/locks/tea.lock.yaml",
    "dependencies/locks/ponytail.lock.yaml",
    "dependencies/locks/codegraph.lock.yaml",
    "dependencies/locks/anthropic-skills.lock.yaml",
    "dependencies/locks/ui-ux-pro-max.lock.yaml",
    "dependencies/locks/composio-skills.lock.yaml",
    "dependencies/locks/obsidian-skills.lock.yaml",
    "overlays/tea",
    "adapters",
    # V3 is shipped as an explicit, self-contained extension. The lightweight
    # runtime still loads it only for schemaVersion=3 requests.
    "workflow/v3",
    "schemas/v3",
    "catalog/v3",
    "skills/cpp-core",
    "capabilities/cpp",
)

_MATT_LOCK_PATH = "dependencies/locks/matt-pocock-skills.lock.yaml"
_COMMUNITY_SOURCES = {
    "ui-ux-pro-max": ("https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git", (
        "LICENSE", "src/ui-ux-pro-max/data", "src/ui-ux-pro-max/scripts/core.py",
        "src/ui-ux-pro-max/scripts/search.py", "src/ui-ux-pro-max/scripts/design_system.py",
        "src/ui-ux-pro-max/scripts/reasoning_contract.py", "src/ui-ux-pro-max/templates/base/skill-content.md",
    ), "MIT", "verified"),
    "composio-skills": ("https://github.com/ComposioHQ/awesome-claude-skills.git", (
        "README.md", "content-research-writer",
    ), "Apache-2.0", "declared"),
    "obsidian-skills": ("https://github.com/kepano/obsidian-skills.git", (
        "LICENSE", "skills/obsidian-markdown", "skills/obsidian-bases", "skills/json-canvas",
    ), "MIT", "verified"),
}
_TEA_RUNTIME_WORKFLOWS = {
    "bmad-testarch-test-design": "skills/bmad-testarch-test-design",
    "bmad-testarch-atdd": "skills/bmad-testarch-atdd",
    "bmad-testarch-test-review": "skills/bmad-testarch-test-review",
    "bmad-testarch-trace": "skills/bmad-testarch-trace",
    "bmad-testarch-nfr": "skills/bmad-testarch-nfr",
}


def load_adapters(adapter_root: str | Path, schema_path: str | Path) -> list[dict[str, object]]:
    root = Path(adapter_root).resolve(strict=True)
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    result: list[dict[str, object]] = []
    for path in sorted(root.glob("*/adapter.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        validator.validate(value)
        entry = path.parent / value["entryFile"]
        if not entry.is_file() or entry.is_symlink():
            raise AdapterError("adapter-entry-invalid")
        result.append(value)
    if len(result) != 6 or len({item["id"] for item in result}) != 6:
        raise AdapterError("adapter-set-invalid")
    return sorted(result, key=lambda item: item["id"])


def _copy_tree(source: Path, destination: Path, *, excluded_roots: tuple[Path, ...] = ()) -> None:
    for path in sorted(source.rglob("*")):
        if any(path == root or root in path.parents for root in excluded_roots):
            continue
        if path.is_symlink():
            raise AdapterError("runtime-source-link-rejected")
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def _copy_runtime_path(source: Path, destination: Path, relative: str) -> None:
    candidate = source / relative
    target = destination / relative
    if candidate.is_symlink() or not candidate.exists():
        raise AdapterError("runtime-source-invalid")
    if candidate.is_dir():
        _copy_tree(candidate, target)
    elif candidate.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate, target)
    else:
        raise AdapterError("runtime-source-invalid")


def _copy_matt_skills(
    source: Path, destination: Path, *, include_grill_me: bool
) -> None:
    lock_path = source / _MATT_LOCK_PATH
    try:
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise AdapterError("matt-skills-lock-invalid") from None
    if (
        not isinstance(lock, dict)
        or lock.get("schemaVersion") != 1
        or lock.get("canonicalUrl") != "https://github.com/mattpocock/skills.git"
        or lock.get("path") != "dependencies/upstream/matt-pocock-skills"
        or not isinstance(lock.get("gitlinkCommit"), str)
        or len(lock["gitlinkCommit"]) != 40
        or not isinstance(lock.get("gitTree"), str)
        or len(lock["gitTree"]) != 40
        or not isinstance(lock.get("license"), dict)
        or not isinstance(lock.get("selectedSkills"), list)
    ):
        raise AdapterError("matt-skills-lock-invalid")

    upstream = source / lock["path"]
    if upstream.is_symlink() or not upstream.is_dir():
        raise AdapterError("matt-skills-source-invalid")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=upstream, check=True,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=upstream, check=True,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=upstream, check=True, capture_output=True, text=True,
            encoding="utf-8", timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise AdapterError("matt-skills-source-invalid") from None
    if commit != lock["gitlinkCommit"] or tree != lock["gitTree"] or dirty:
        raise AdapterError("matt-skills-source-drift")

    def locked_text_bytes(content: bytes, expected: str, reason: str) -> bytes:
        lf = content.replace(b"\r\n", b"\n")
        for candidate in (content, lf, lf.replace(b"\n", b"\r\n")):
            if "sha256:" + hashlib.sha256(candidate).hexdigest() == expected:
                return candidate
        raise AdapterError(reason)

    selected: set[str] = set()
    for item in lock["selectedSkills"]:
        if not isinstance(item, dict) or set(item) != {"id", "path", "hash"}:
            raise AdapterError("matt-skills-lock-invalid")
        skill_id = item["id"]
        relative = Path(item["path"])
        expected_hash = item["hash"]
        if (
            not isinstance(skill_id, str)
            or not skill_id
            or skill_id in selected
            or not isinstance(item["path"], str)
            or relative.is_absolute()
            or ".." in relative.parts
            or not isinstance(expected_hash, str)
            or not expected_hash.startswith("sha256:")
        ):
            raise AdapterError("matt-skills-lock-invalid")
        selected.add(skill_id)
        if skill_id == "grill-me" and not include_grill_me:
            continue
        skill_root = upstream / relative
        entry = skill_root / "SKILL.md"
        if skill_root.is_symlink() or not entry.is_file() or entry.is_symlink():
            raise AdapterError("matt-skills-source-invalid")
        locked_entry = locked_text_bytes(entry.read_bytes(), expected_hash, "matt-skills-source-drift")
        target = destination / "skills" / "matt-pocock" / skill_id
        _copy_tree(skill_root, target)
        for published in target.rglob("*"):
            if published.is_file() and published.suffix in {".md", ".sh", ".yaml"}:
                content = published.read_bytes()
                canonical = content.replace(b"\r\n", b"\n")
                if canonical != content:
                    published.write_bytes(canonical)
        (target / "SKILL.md").write_bytes(locked_entry)

    license_path = upstream / "LICENSE"
    license_lock = lock["license"]
    if (
        set(license_lock) != {"path", "spdx", "hash"}
        or license_lock.get("path") != "LICENSE"
        or license_lock.get("spdx") != "MIT"
        or not isinstance(license_lock.get("hash"), str)
        or not license_path.is_file()
        or license_path.is_symlink()
    ):
        raise AdapterError("matt-skills-source-invalid")
    license_target = destination / "skills" / "matt-pocock" / "LICENSE"
    license_target.parent.mkdir(parents=True, exist_ok=True)
    license_target.write_bytes(locked_text_bytes(license_path.read_bytes(), license_lock["hash"], "matt-skills-source-invalid"))


def _copy_anthropic_skill_creator(source: Path, destination: Path) -> None:
    """Package the pinned maintenance reference outside Skill discovery."""

    try:
        lock = yaml.safe_load(
            (source / "dependencies/locks/anthropic-skills.lock.yaml").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, yaml.YAMLError):
        raise AdapterError("anthropic-skills-lock-invalid") from None
    if (
        not isinstance(lock, dict)
        or lock.get("schemaVersion") != 1
        or lock.get("sourceId") != "anthropic-skills"
        or lock.get("canonicalUrl") != "https://github.com/anthropics/skills.git"
        or lock.get("path") != "dependencies/upstream/anthropic-skills"
        or any(not isinstance(lock.get(key), str) or re.fullmatch(r"[0-9a-f]{40}", lock[key]) is None for key in ("gitlinkCommit", "gitTree"))
        or not isinstance(lock.get("selectedSkill"), dict)
        or not isinstance(lock.get("license"), dict)
    ):
        raise AdapterError("anthropic-skills-lock-invalid")
    selected = lock["selectedSkill"]
    files = selected.get("files")
    if (
        selected.get("id") != "skill-creator"
        or selected.get("path") != "skills/skill-creator"
        or not isinstance(files, dict)
        or not {"SKILL.md", "LICENSE.txt"}.issubset(files)
        or lock["license"].get("path") != "skills/skill-creator/LICENSE.txt"
        or lock["license"].get("spdx") != "Apache-2.0"
        or lock["license"].get("hash") != files["LICENSE.txt"]
    ):
        raise AdapterError("anthropic-skills-lock-invalid")
    for relative, expected in files.items():
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative or ":" in relative
            or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts
            or not isinstance(expected, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is None
        ):
            raise AdapterError("anthropic-skills-lock-invalid")

    def hashes(root: Path) -> dict[str, str]:
        result = {}
        for path in (root, *sorted(root.rglob("*"))):
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise AdapterError("anthropic-skills-source-invalid")
            if path.is_file():
                # Git checkout line endings vary; the lock binds canonical LF bytes.
                result[path.relative_to(root).as_posix()] = "sha256:" + hashlib.sha256(
                    path.read_bytes().replace(b"\r\n", b"\n")
                ).hexdigest()
        return result

    upstream = source / lock["path"]
    skill = upstream / selected["path"]
    try:
        if not upstream.is_dir() or not skill.is_dir():
            raise AdapterError("anthropic-skills-source-invalid")
        for path in (upstream, upstream / "skills", skill):
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise AdapterError("anthropic-skills-source-invalid")
        gitlink_result = _run_source_git(
            ["git", "ls-files", "--stage", "--", lock["path"]], source,
        )
        if gitlink_result.returncode:
            raise AdapterError("anthropic-skills-source-invalid")
        gitlink = gitlink_result.stdout.strip()
        if gitlink != f"160000 {lock['gitlinkCommit']} 0\t{lock['path']}":
            raise AdapterError("anthropic-skills-source-drift")
        results = [_run_source_git(["git", *arguments], upstream) for arguments in (
            ("rev-parse", "HEAD"), ("rev-parse", "HEAD^{tree}"),
            ("status", "--porcelain=v1", "--untracked-files=all"),
        )]
        if any(result.returncode for result in results):
            raise AdapterError("anthropic-skills-source-invalid")
        values = [result.stdout.strip() for result in results]
        if values != [lock["gitlinkCommit"], lock["gitTree"], ""] or hashes(skill) != files:
            raise AdapterError("anthropic-skills-source-drift")
        target = destination / "references/anthropic-skills/skill-creator"
        _copy_tree(skill, target)
        if hashes(target) != files:
            raise AdapterError("anthropic-skills-source-drift")
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise AdapterError("anthropic-skills-source-invalid") from None


def _copy_community_sources(source: Path, destination: Path) -> None:
    """Copy only the locked resource closures behind the five local entries."""

    for source_id, (url, resources, spdx, license_status) in _COMMUNITY_SOURCES.items():
        try:
            lock = yaml.safe_load((source / f"dependencies/locks/{source_id}.lock.yaml").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            raise AdapterError("community-skills-lock-invalid") from None
        relative_root = f"dependencies/upstream/{source_id}"
        if (
            not isinstance(lock, dict) or type(lock.get("schemaVersion")) is not int
            or lock.get("schemaVersion") != 1 or lock.get("sourceId") != source_id
            or lock.get("canonicalUrl") != url or lock.get("path") != relative_root
            or lock.get("resources") != list(resources)
            or any(not isinstance(lock.get(key), str) or re.fullmatch(r"[0-9a-f]{40}", lock[key]) is None
                   for key in ("gitlinkCommit", "gitTree"))
            or not isinstance(lock.get("files"), dict) or not lock["files"]
        ):
            raise AdapterError("community-skills-lock-invalid")
        files = lock["files"]
        for relative, expected in files.items():
            if (
                not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative
                or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts
                or PurePosixPath(relative).as_posix() != relative
                or not isinstance(expected, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is None
            ):
                raise AdapterError("community-skills-lock-invalid")
        if lock.get("license") != {"path": resources[0], "spdx": spdx, "status": license_status,
                                  "hash": files.get(resources[0])}:
            raise AdapterError("community-skills-lock-invalid")

        def plain(path: Path) -> None:
            current = path
            while current != source:
                if current.is_symlink() or getattr(current.lstat(), "st_file_attributes", 0) & 0x400:
                    raise AdapterError("community-skills-source-invalid")
                current = current.parent

        def digest(path: Path) -> str:
            return "sha256:" + hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()

        upstream = source / relative_root
        try:
            plain(upstream)
            commands = [(["git", "ls-files", "--stage", "--", relative_root], source)] + [
                (["git", *arguments], upstream) for arguments in (
                    ("rev-parse", "HEAD"), ("rev-parse", "HEAD^{tree}"),
                    ("status", "--porcelain=v1", "--untracked-files=all"),
                )
            ]
            results = [_run_source_git(command, cwd) for command, cwd in commands]
            if any(result.returncode for result in results):
                raise AdapterError("community-skills-source-invalid")
            expected_git = [f"160000 {lock['gitlinkCommit']} 0\t{relative_root}",
                            lock["gitlinkCommit"], lock["gitTree"], ""]
            if [result.stdout.strip() for result in results] != expected_git:
                raise AdapterError("community-skills-source-drift")
            selected = {}
            for relative in resources:
                resource = upstream / relative
                plain(resource)
                if resource.is_file():
                    selected[relative] = resource
                elif resource.is_dir():
                    for path in sorted(resource.rglob("*")):
                        plain(path)
                        if path.is_file():
                            selected[path.relative_to(upstream).as_posix()] = path
                else:
                    raise AdapterError("community-skills-source-invalid")
            if set(selected) != set(files) or any(digest(path) != files[name] for name, path in selected.items()):
                raise AdapterError("community-skills-source-drift")
            target_root = destination / "references/community-skills" / source_id
            for name, path in selected.items():
                target = target_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                if digest(target) != files[name]:
                    raise AdapterError("community-skills-source-drift")
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise AdapterError("community-skills-source-invalid") from None


def _resolve_tea_checklist(upstream: Path, workflow_id: str) -> Path:
    """Resolve a pinned TEA checklist while accepting the TEA 2.x CI layout."""

    checklist = upstream / "skills" / f"bmad-testarch-{workflow_id}" / "checklist.md"
    if workflow_id == "ci" and not checklist.is_file():
        # TEA 2.x keeps the CI checklist beside the framework's CI setup
        # materials instead of at the former top-level skill path.
        checklist = upstream / "skills" / "bmad-testarch-framework" / "ci" / "checklist.md"
    if not checklist.is_file() or checklist.is_symlink():
        raise AdapterError("tea-source-invalid")
    return checklist


def _copy_tea_quality(source: Path, destination: Path) -> None:
    """Copy only the pinned TEA workflow closures used by the local adapter."""

    try:
        verify_tea_source(source)
    except ValueError:
        raise AdapterError("tea-source-invalid") from None
    upstream = source / "dependencies/upstream/tea"
    target = destination / "skills/tea-quality/references"
    if not (destination / "skills/tea-quality/SKILL.md").is_file():
        raise AdapterError("tea-adapter-missing")
    for workflow_id, relative in sorted(_TEA_RUNTIME_WORKFLOWS.items()):
        workflow = upstream / relative
        if workflow.is_symlink() or not (workflow / "SKILL.md").is_file():
            raise AdapterError("tea-source-invalid")
        _copy_tree(workflow, target / workflow_id)
    for workflow_id in ("framework", "ci"):
        reference = target / f"bmad-testarch-{workflow_id}"
        reference.mkdir(parents=True, exist_ok=True)
        # Package only the bounded entry and reference checklist. Upstream
        # creation steps and project-local BMAD bootstrap are not executable here.
        shutil.copyfile(source / "skills/tea-quality/assessments" / workflow_id / "SKILL.md", reference / "SKILL.md")
        checklist = _resolve_tea_checklist(upstream, workflow_id)
        shutil.copyfile(checklist, reference / "checklist.md")
        # The source adapter remains in the repository; publish one discoverable entry.
        duplicate = destination / "skills/tea-quality/assessments" / workflow_id / "SKILL.md"
        duplicate.unlink(missing_ok=True)
    knowledge = upstream / "skills/bmod-tea/knowledge"
    if not (knowledge / "tea-index.csv").is_file():
        raise AdapterError("tea-knowledge-missing")
    _copy_tree(knowledge, target / "bmod-tea/knowledge")
    for entry in target.glob("*/SKILL.md"):
        metadata = entry.parent / "agents/openai.yaml"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(
            "policy:\n  allow_implicit_invocation: false\n", encoding="utf-8"
        )
    license_path = upstream / "LICENSE"
    if license_path.is_symlink() or not license_path.is_file():
        raise AdapterError("tea-source-invalid")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_path, target / "LICENSE")

    try:
        validate_packaged_runtime(destination)
    except ValueError as error:
        raise AdapterError(str(error)) from None


def _copy_ponytail(source: Path, destination: Path) -> None:
    """Copy only the four hash-bound Ponytail Skills, never host files."""

    try:
        copy_ponytail_skills(source, destination)
    except PonytailSourceError:
        raise AdapterError("ponytail-source-invalid") from None


def _exclude_c7_v3_catalog(runtime_root: Path) -> None:
    index_path = runtime_root / "catalog/v3/index.yaml"
    document = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    document["domains"] = [
        item for item in document["domains"] if item["id"] != "knowledge"
    ]
    document["modules"] = [
        item
        for item in document["modules"]
        if not item["id"].startswith("knowledge-")
    ]
    index_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    for relative in (
        "catalog/v3/domains/knowledge.yaml",
        "catalog/v3/modules/knowledge-read.yaml",
        "catalog/v3/modules/knowledge-propose.yaml",
        "catalog/v3/modules/knowledge-update.yaml",
    ):
        (runtime_root / relative).unlink()


def _profile_catalog(
    source: Path, profile: str, *, include_grill_me: bool
) -> bytes:
    compiled = compile_catalog(source / "catalog")
    if profile == "maintainer":
        return compiled.content
    envelope = json.loads(compiled.content)
    catalog = envelope["catalog"]
    allowed = set(_CORE_CATALOG_IDS)
    if profile == "knowledge":
        allowed.add("knowledge-on-demand-loading")
    catalog["entries"] = [
        entry for entry in catalog["entries"] if entry["id"] in allowed
    ]
    selected_ids = {entry["id"] for entry in catalog["entries"]}
    modules = [
        module
        for module in catalog.get("modules", [])
        if module["sourceEntryId"] in selected_ids
        and (include_grill_me or module["id"] != "design-grill-me")
    ]
    selected_module_ids = {module["id"] for module in modules}
    catalog["modules"] = [
        module
        for module in modules
        if set(module["dependencies"]) <= selected_module_ids
    ]
    if any(
        dependency not in selected_ids
        for entry in catalog["entries"]
        for dependency in entry["dependencies"]
    ):
        raise AdapterError("runtime-profile-dependency-invalid")
    catalog["domains"] = sorted({entry["domain"] for entry in catalog["entries"]})
    payload = json.dumps(
        catalog,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    filtered = {
        "schemaVersion": envelope["schemaVersion"],
        "catalog": catalog,
        "catalogHash": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }
    return (
        json.dumps(filtered, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _runtime_manifest(root: Path) -> list[dict[str, str]]:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "artifact-manifest.json":
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return entries


def build_runtime(
    repository_root: str | Path,
    output_root: str | Path,
    version: str,
    *,
    profile: str = "core",
    include_grill_me: bool = True,
) -> dict[str, object]:
    if profile not in _RUNTIME_PROFILES:
        raise AdapterError("runtime-profile-invalid")
    if not isinstance(version, str) or _RUNTIME_VERSION.fullmatch(version) is None:
        raise AdapterError("runtime-version-invalid")
    source = Path(repository_root).resolve(strict=True)
    output = Path(output_root).resolve(strict=False)
    if output.exists() or output == source:
        raise AdapterError("runtime-output-invalid")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".selfworkflow-runtime-", dir=output.parent))
    try:
        if profile == "maintainer":
            shutil.copyfile(source / "WORKFLOW.md", temporary / "WORKFLOW.md")
            for directory in (
                "workflow", "schemas", "skills", "capabilities", "overlays",
                "dependencies", "adapters", "extensions",
            ):
                candidate = source / directory
                if candidate.is_dir():
                    excluded = tuple(
                        candidate / "upstream" / source_id
                        for source_id in ("matt-pocock-skills", "tea", "ponytail", "anthropic-skills", *_COMMUNITY_SOURCES)
                    ) if directory == "dependencies" else ()
                    _copy_tree(candidate, temporary / directory, excluded_roots=excluded)
            _copy_runtime_path(source, temporary, "catalog/v3")
            for legacy in (
                temporary / "skills/grill-me",
                temporary / "overlays/superpowers",
                temporary / "dependencies/superpowers.lock.yaml",
            ):
                if legacy.is_dir():
                    shutil.rmtree(legacy)
                elif legacy.exists():
                    legacy.unlink()
        else:
            shutil.copyfile(source / "WORKFLOW.md", temporary / "WORKFLOW.md")
            for relative in _CORE_PATHS:
                _copy_runtime_path(source, temporary, relative)
            if profile != "knowledge":
                _exclude_c7_v3_catalog(temporary)
            if profile == "knowledge":
                _copy_runtime_path(source, temporary, "extensions/knowledge/contract.yaml")
                _copy_runtime_path(source, temporary, "extensions/knowledge/selfopenwiki")
                generic_skill = temporary / "skills" / "knowledge-backend" / "SKILL.md"
                generic_skill.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(
                    source / "skills/knowledge-backend/SKILL.md",
                    generic_skill,
                )
                selfopenwiki_skill = temporary / "skills" / "kg-selfopenwiki" / "SKILL.md"
                selfopenwiki_skill.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(
                    source / "skills/kg-selfopenwiki/SKILL.md",
                    selfopenwiki_skill,
                )
        _copy_matt_skills(
            source, temporary, include_grill_me=include_grill_me
        )
        _copy_tea_quality(source, temporary)
        _copy_ponytail(source, temporary)
        _copy_anthropic_skill_creator(source, temporary)
        _copy_community_sources(source, temporary)
        catalog_output = temporary / "catalog.json"
        catalog_output.write_bytes(
            _profile_catalog(
                source, profile, include_grill_me=include_grill_me
            )
        )
        build_host_runtime(source, temporary)
        files = _runtime_manifest(temporary)
        runtime_hash = "sha256:" + hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        manifest = {
            "schemaVersion": 1,
            "version": version,
            "profile": profile,
            "features": {"grillMe": include_grill_me},
            "runtimeHash": runtime_hash,
            "files": files,
        }
        (temporary / "artifact-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    return manifest
