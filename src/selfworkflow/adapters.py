"""Compile vendor-thin adapters and standalone runtime snapshots."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from jsonschema import Draft202012Validator
import yaml

from selfworkflow.catalog import compile_catalog


class AdapterError(RuntimeError):
    pass


_RUNTIME_PROFILES = {"core", "knowledge", "maintainer"}
_CORE_CATALOG_IDS = {
    "workflow-core",
    "workflow-quality",
    "code-quality",
    "grill-me",
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
    "skills/code-quality",
    "skills/workflow-quality",
    "capabilities/code-quality",
    "capabilities/workflow-quality",
    "overlays/superpowers",
    "dependencies/superpowers.lock.yaml",
    "adapters",
)


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


def _profile_catalog(
    source: Path, profile: str, *, include_grill_me: bool
) -> bytes:
    compiled = compile_catalog(source / "catalog")
    if profile == "maintainer" and include_grill_me:
        return compiled.content
    envelope = json.loads(compiled.content)
    catalog = envelope["catalog"]
    if profile == "maintainer":
        catalog["entries"] = [
            entry for entry in catalog["entries"] if entry["id"] != "grill-me"
        ]
    else:
        allowed = set(_CORE_CATALOG_IDS)
        if not include_grill_me:
            allowed.remove("grill-me")
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
            if not include_grill_me:
                shutil.rmtree(temporary / "skills/grill-me")
        else:
            shutil.copyfile(source / "workflow/core.md", temporary / "WORKFLOW.md")
            for relative in _CORE_PATHS:
                _copy_runtime_path(source, temporary, relative)
            if include_grill_me:
                _copy_runtime_path(source, temporary, "skills/grill-me")
            if profile == "knowledge":
                _copy_runtime_path(source, temporary, "extensions/knowledge/contract.yaml")
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
