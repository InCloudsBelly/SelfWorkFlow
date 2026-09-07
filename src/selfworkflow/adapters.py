"""Compile vendor-thin adapters and standalone runtime snapshots."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from jsonschema import Draft202012Validator
import yaml

from selfworkflow.catalog import compile_catalog
from selfworkflow.v3.tea_adapter import verify_tea_source


class AdapterError(RuntimeError):
    pass


_RUNTIME_PROFILES = {"core", "knowledge", "maintainer"}
_CORE_CATALOG_IDS = {
    "workflow-core",
    "workflow-quality",
    "testing-review-quality",
    "tea-quality-foundation",
    "code-quality",
    "matt-skills-foundation",
}
_CORE_PATHS = (
    "workflow/core.md",
    "workflow/pipeline.yaml",
    "workflow/git-policy.yaml",
    "workflow/resolve-request.example.json",
    "schemas/pipeline.schema.json",
    "schemas/plan-graph.schema.json",
    "schemas/stage-result.schema.json",
    "schemas/run-ledger.schema.json",
    "schemas/resolve-request.schema.json",
    "schemas/resolve-result.schema.json",
    "schemas/git-policy.schema.json",
    "schemas/project-review-profile.schema.json",
    "skills/code-quality",
    "skills/workflow-quality",
    "skills/testing-review-quality",
    "skills/caveman",
    "skills/tea-quality",
    "capabilities/code-quality",
    "capabilities/workflow-quality",
    "dependencies/locks/matt-pocock-skills.lock.yaml",
    "dependencies/locks/tea.lock.yaml",
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
_TEA_RUNTIME_WORKFLOWS = {
    "bmad-testarch-test-design": "src/workflows/testarch/bmad-testarch-test-design",
    "bmad-testarch-atdd": "src/workflows/testarch/bmad-testarch-atdd",
    "bmad-testarch-test-review": "src/workflows/testarch/bmad-testarch-test-review",
    "bmad-testarch-trace": "src/workflows/testarch/bmad-testarch-trace",
    "bmad-testarch-nfr": "src/workflows/testarch/bmad-testarch-nfr",
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


def _copy_tree(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
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
        actual_hash = "sha256:" + hashlib.sha256(entry.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise AdapterError("matt-skills-source-drift")
        _copy_tree(skill_root, destination / "skills" / "matt-pocock" / skill_id)

    license_path = upstream / "LICENSE"
    license_lock = lock["license"]
    if (
        set(license_lock) != {"path", "spdx", "hash"}
        or license_lock.get("path") != "LICENSE"
        or license_lock.get("spdx") != "MIT"
        or not isinstance(license_lock.get("hash"), str)
        or not license_path.is_file()
        or license_path.is_symlink()
        or "sha256:" + hashlib.sha256(license_path.read_bytes()).hexdigest()
        != license_lock["hash"]
    ):
        raise AdapterError("matt-skills-source-invalid")
    license_target = destination / "skills" / "matt-pocock" / "LICENSE"
    license_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_path, license_target)


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
    license_path = upstream / "LICENSE"
    if license_path.is_symlink() or not license_path.is_file():
        raise AdapterError("tea-source-invalid")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_path, target / "LICENSE")


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
                    _copy_tree(candidate, temporary / directory)
            copied_upstream = temporary / "dependencies/upstream/matt-pocock-skills"
            if copied_upstream.exists():
                shutil.rmtree(copied_upstream)
            copied_tea = temporary / "dependencies/upstream/tea"
            if copied_tea.exists():
                shutil.rmtree(copied_tea)
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
        catalog_output = temporary / "catalog.json"
        catalog_output.write_bytes(
            _profile_catalog(
                source, profile, include_grill_me=include_grill_me
            )
        )
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
