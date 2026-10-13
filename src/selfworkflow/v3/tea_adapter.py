"""Fail-closed TEA source verification, bounded routing, and JIT reads."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any, Mapping

from selfworkflow.v3.catalog import CatalogError, _load_yaml_file
from selfworkflow.v3.hashing import content_hash, hash_bytes


_SOURCE = "dependencies/upstream/tea"
_LOCK = "dependencies/locks/tea.lock.yaml"
_ADAPTER = "overlays/tea/adapter.yaml"
_ROUTING = "overlays/tea/routing.yaml"
_URL = "https://github.com/bmad-code-org/bmad-method-test-architecture-enterprise.git"
_LEVELS = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}
_STAGES = {"plan", "implementation", "review", "verify", "release"}
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_UNRESOLVED_TEMPLATE = re.compile(
    r"\{\{|\$\{|(?<!\{)\{[A-Za-z][A-Za-z0-9_.-]*\}(?!\})"
)
_PACKAGED_WORKFLOWS = {
    "framework": {
        "directory": "bmad-testarch-framework", "output": "framework.md",
        "fields": ("projectManifest", "testInventory", "projectRules", "acceptanceCriteria"),
        "headings": ("Framework", "Conventions", "Commands", "Gaps"),
    },
    "ci": {
        "directory": "bmad-testarch-ci", "output": "ci.md",
        "fields": ("pipelineFiles", "verificationPlan", "projectRules", "runEvidence"),
        "headings": ("Pipeline", "Quality Gates", "Artifacts", "Run Evidence", "Gaps"),
    },
    "test-design": {
        "directory": "bmad-testarch-test-design", "output": "test-design.md",
        "fields": ("requirements", "acceptanceCriteria", "design", "risk"),
        "headings": ("Scope", "Risks", "Coverage", "Cases"),
        "knowledge": (
            "risk-governance.md", "probability-impact.md", "test-levels-framework.md",
            "test-priorities-matrix.md", "adr-quality-readiness-checklist.md",
            "nfr-criteria.md", "test-quality.md", "contract-testing.md",
        ),
    },
    "atdd": {
        "directory": "bmad-testarch-atdd", "output": "atdd.md",
        "fields": ("requirements", "acceptanceCriteria", "implementationPlan", "testDesign"),
        "headings": ("Red Evidence", "Acceptance Tests", "Fixtures"),
        "knowledge": (
            "data-factories.md", "component-tdd.md", "test-quality.md",
            "test-healing-patterns.md", "selector-resilience.md", "timing-debugging.md",
            "fixture-architecture.md", "network-first.md", "test-levels-framework.md",
            "test-priorities-matrix.md", "ci-burn-in.md", "contract-testing.md",
        ),
    },
    "test-review": {
        "directory": "bmad-testarch-test-review", "output": "test-review.md",
        "fields": ("acceptanceCriteria", "implementationDelta", "testDesign", "verificationEvidence"),
        "headings": ("Coverage Review", "Failure Paths", "Findings"),
        "knowledge": (
            "test-quality.md", "data-factories.md", "test-levels-framework.md",
            "selective-testing.md", "test-healing-patterns.md", "selector-resilience.md",
            "timing-debugging.md", "maestro-flows.md", "mobile-test-strategy.md",
            "fixture-architecture.md", "network-first.md", "playwright-config.md",
            "component-tdd.md", "ci-burn-in.md", "contract-testing.md",
        ),
    },
    "trace": {
        "directory": "bmad-testarch-trace", "output": "trace.md",
        "fields": ("acceptanceCriteria", "testInventory", "verificationEvidence"),
        "headings": ("Trace Matrix", "Gaps"),
        "knowledge": (
            "test-priorities-matrix.md", "risk-governance.md", "probability-impact.md",
            "test-quality.md", "selective-testing.md",
        ),
    },
    "nfr": {
        "directory": "bmad-testarch-nfr", "output": "nfr.md",
        "fields": ("design", "nfrRequirements", "verificationEvidence"),
        "headings": ("Performance", "Security", "Reliability"),
        "knowledge": (
            "adr-quality-readiness-checklist.md", "ci-burn-in.md", "test-quality.md",
            "playwright-config.md", "error-handling.md",
        ),
    },
}

# A packaged TEA workflow is only a completion artifact when its output is
# bound to the exact V3 stage slot and selected module that consumed it.
_TEA_BINDINGS = {
    "framework": {"stageId": "planned", "slotId": "plan.assessment", "moduleId": "tea-framework"},
    "ci": {"stageId": "verified", "slotId": "verify.ci", "moduleId": "tea-ci"},
    "test-design": {
        "stageId": "planned",
        "slotId": "test.quality.plan",
        "moduleId": "tea-test-design",
    },
    "atdd": {
        "stageId": "implemented",
        "slotId": "test.quality.implementation",
        "moduleId": "tea-atdd",
    },
    "test-review": {
        "stageId": "reviewed",
        "slotId": "test.quality.review",
        "moduleId": "tea-test-review",
    },
    "trace": {
        "stageId": "verified",
        "slotId": "test.quality.verify",
        "moduleId": "tea-trace",
    },
    "nfr": {
        "stageId": "verified",
        "slotId": "test.quality.verify",
        "moduleId": "tea-nfr",
    },
}
TEA_MODULE_IDS = frozenset(item["moduleId"] for item in _TEA_BINDINGS.values())
_TEA_RECEIPT_FIELDS = {
    "schemaVersion", "planHash", "attemptRef", "stageId", "slotId", "moduleId",
    "workflowId", "referenceHash", "inputHash", "outputRelative", "outputHash",
    "status", "receiptHash",
}
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class TeaAdapterError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & 0x400)


def _assert_no_reparse(path: Path, boundary: Path) -> None:
    current = path
    while True:
        if _is_reparse_point(current):
            raise ValueError
        if current == boundary:
            return
        if current.parent == current:
            raise ValueError
        current = current.parent


def _contains_unresolved_template(value: str) -> bool:
    return _UNRESOLVED_TEMPLATE.search(value) is not None


def _run(command: list[str], cwd: Path, *, allow_missing: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="strict", check=False,
        )
    except (OSError, UnicodeError, ValueError):
        raise TeaAdapterError("tea-source-identity-invalid") from None
    if result.returncode != 0 and not allow_missing:
        raise TeaAdapterError("tea-source-identity-invalid")
    return result


def _mapping(path: Path, root: Path, fields: set[str]) -> dict[str, Any]:
    try:
        value = _load_yaml_file(path, _MAX_CONFIG_BYTES, root)
    except (CatalogError, OSError, ValueError):
        raise TeaAdapterError("tea-source-identity-invalid") from None
    if not isinstance(value, dict) or set(value) != fields:
        raise TeaAdapterError("tea-source-identity-invalid")
    return value


def _file_hash(path: Path) -> str:
    try:
        if not path.is_file() or path.is_symlink():
            raise OSError
        return hash_bytes(path.read_bytes())
    except (OSError, ValueError):
        raise TeaAdapterError("tea-source-identity-invalid") from None


def verify_tea_source(repository: str | Path) -> dict[str, str]:
    """Recompute every pinned identity dimension; any drift has one stable error."""

    root = Path(repository).resolve()
    tea = root / _SOURCE
    lock = _mapping(
        root / _LOCK,
        root,
        {
            "schemaVersion", "sourceId", "canonicalUrl", "path", "gitlinkCommit",
            "gitTree", "inventoryHash", "license", "adapterFiles", "adapterHash", "status",
        },
    )
    if (
        lock["schemaVersion"] != 3
        or lock["sourceId"] != "tea"
        or lock["canonicalUrl"] != _URL
        or lock["path"] != _SOURCE
        or not tea.is_dir()
    ):
        raise TeaAdapterError("tea-source-identity-invalid")

    url = _run(
        ["git", "config", "--file", ".gitmodules", "--get", "submodule.dependencies/upstream/tea.url"],
        root,
    ).stdout.strip()
    branch = _run(
        ["git", "config", "--file", ".gitmodules", "--get", "submodule.dependencies/upstream/tea.branch"],
        root,
        allow_missing=True,
    )
    if url != _URL or branch.returncode == 0 or branch.stdout.strip():
        raise TeaAdapterError("tea-source-identity-invalid")

    listing = _run(["git", "ls-files", "--stage", "--", _SOURCE], root).stdout.strip().split()
    if len(listing) < 2 or listing[0] != "160000":
        raise TeaAdapterError("tea-source-identity-invalid")
    commit = _run(["git", "rev-parse", "HEAD"], tea).stdout.strip()
    tree = _run(["git", "rev-parse", "HEAD^{tree}"], tea).stdout.strip()
    dirty = _run(["git", "status", "--porcelain=v1", "--untracked-files=all"], tea).stdout
    inventory = _run(["git", "ls-tree", "-r", "--full-tree", "HEAD"], tea).stdout.encode("utf-8")
    if dirty or any(value != lock["gitlinkCommit"] for value in (listing[1], commit)):
        raise TeaAdapterError("tea-source-identity-invalid")
    if tree != lock["gitTree"] or hash_bytes(inventory) != lock["inventoryHash"]:
        raise TeaAdapterError("tea-source-identity-invalid")

    license_info = lock["license"]
    if not isinstance(license_info, dict) or set(license_info) != {"path", "spdx", "hash"}:
        raise TeaAdapterError("tea-source-identity-invalid")
    if license_info["path"] != "LICENSE" or license_info["spdx"] != "MIT":
        raise TeaAdapterError("tea-source-identity-invalid")
    if _file_hash(tea / "LICENSE") != license_info["hash"]:
        raise TeaAdapterError("tea-source-identity-invalid")

    adapter_files = lock["adapterFiles"]
    if not isinstance(adapter_files, list) or len(adapter_files) != 2:
        raise TeaAdapterError("tea-source-identity-invalid")
    identities = []
    seen: set[str] = set()
    for item in adapter_files:
        if not isinstance(item, dict) or set(item) != {"path", "hash"}:
            raise TeaAdapterError("tea-source-identity-invalid")
        path = item["path"]
        if path in seen or path not in {_ADAPTER, _ROUTING} or not _HASH.fullmatch(item["hash"]):
            raise TeaAdapterError("tea-source-identity-invalid")
        seen.add(path)
        actual = _file_hash(root / path)
        if actual != item["hash"]:
            raise TeaAdapterError("tea-source-identity-invalid")
        identities.append({"path": path, "hash": actual})
    if content_hash(identities) != lock["adapterHash"]:
        raise TeaAdapterError("tea-source-identity-invalid")
    status = lock["status"]
    if not isinstance(status, dict) or status.get("sourceIntegrity") != "supported":
        raise TeaAdapterError("tea-source-identity-invalid")
    return {"commit": commit, "tree": tree, "status": "supported"}


def load_workflow_candidates(repository: str | Path) -> tuple[dict[str, Any], ...]:
    root = Path(repository).resolve()
    verify_tea_source(root)
    adapter = _mapping(
        root / _ADAPTER,
        root,
        {"schemaVersion", "sourceId", "sourcePath", "artifactRoot", "workflows"},
    )
    workflows = adapter["workflows"]
    if adapter["schemaVersion"] != 3 or not isinstance(workflows, list) or len(workflows) != 9:
        raise TeaAdapterError("tea-adapter-invalid")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in workflows:
        if not isinstance(item, dict) or set(item) != {"id", "upstreamId", "root", "support"}:
            raise TeaAdapterError("tea-adapter-invalid")
        if item["id"] in ids:
            raise TeaAdapterError("tea-adapter-invalid")
        ids.add(item["id"])
        support = item["support"]
        if not isinstance(support, dict) or set(support) != {
            "sourceIntegrity", "adapterSupport", "runtimeCapability", "behaviorEvidence"
        }:
            raise TeaAdapterError("tea-adapter-invalid")
        result.append(json.loads(json.dumps(item)))
    return tuple(result)


def eligible_workflows(
    *, stage: str, test_level: str, grill_me_used: bool = False,
    acceptance_red: bool = False,
    framework_assessment: bool = False, ci_validation: bool = False,
) -> tuple[str, ...]:
    if stage not in _STAGES or test_level not in _LEVELS or type(grill_me_used) is not bool or type(acceptance_red) is not bool:
        raise TeaAdapterError("tea-route-invalid")
    if (
        type(framework_assessment) is not bool or type(ci_validation) is not bool
        or (framework_assessment and stage != "plan")
        or (ci_validation and stage not in {"verify", "release"})
    ):
        raise TeaAdapterError("tea-route-invalid")
    optional = ("framework",) if framework_assessment else ("ci",) if ci_validation else ()
    effective = max(_LEVELS[test_level], 2 if grill_me_used else 0)
    if effective < 2:
        return optional
    if stage == "plan":
        return ("test-design",) + optional
    if stage == "review":
        return ("test-review",)
    if stage == "implementation":
        return ("atdd",) if acceptance_red else ()
    if effective >= 3 and stage in {"verify", "release"}:
        return ("trace", "nfr") + optional
    return optional


def load_jit_artifact(
    repository: str | Path, *, workflow_id: str, kind: str, relative_path: str,
) -> dict[str, Any]:
    root = Path(repository).resolve()
    candidates = {item["id"]: item for item in load_workflow_candidates(root)}
    candidate = candidates.get(workflow_id)
    if candidate is None or candidate["support"]["adapterSupport"] != "supported":
        raise TeaAdapterError("tea-jit-workflow-unavailable")
    if workflow_id in {"framework", "ci"}:
        # These are local assessment adapters, never upstream scaffold entry points.
        if kind != "skill" or relative_path != "SKILL.md":
            raise TeaAdapterError("tea-jit-path-invalid")
        target = root / "skills/tea-quality/assessments" / workflow_id / "SKILL.md"
        try:
            _assert_no_reparse(target, root)
            if not target.is_file() or target.stat().st_size > _MAX_ARTIFACT_BYTES:
                raise ValueError
            content = target.read_bytes()
            text = content.decode("utf-8")
        except (OSError, ValueError, UnicodeError):
            raise TeaAdapterError("tea-jit-path-invalid") from None
        return {"workflowId": workflow_id, "kind": kind, "path": target.relative_to(root).as_posix(), "content": text, "contentHash": hash_bytes(content)}
    if kind not in {"skill", "workflow", "step", "resource"} or not isinstance(relative_path, str):
        raise TeaAdapterError("tea-jit-path-invalid")
    try:
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError
        if kind == "skill" and relative.as_posix() != "SKILL.md":
            raise ValueError
        if kind == "workflow" and relative.as_posix() != "workflow.yaml":
            raise ValueError
        if kind == "step" and (not relative.parts or relative.parts[0] != "steps-c"):
            raise ValueError
        if kind == "resource" and (not relative.parts or relative.parts[0] != "resources"):
            raise ValueError
        workflow_root = (root / _SOURCE / candidate["root"]).resolve(strict=True)
        target = (workflow_root / Path(*relative.parts)).resolve(strict=True)
        target.relative_to(workflow_root)
        if not target.is_file() or target.is_symlink() or target.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise ValueError
        content = target.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        raise TeaAdapterError("tea-jit-path-invalid") from None
    return {
        "workflowId": workflow_id,
        "kind": kind,
        "path": f"{candidate['root']}/{relative.as_posix()}",
        "content": text,
        "contentHash": hash_bytes(content),
    }


def _knowledge_entries(skill_root: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    """Validate the packaged index before any workflow can consume its fragments."""
    try:
        knowledge = skill_root / "references/bmod-tea/knowledge"
        index = knowledge / "tea-index.csv"
        _assert_no_reparse(index, skill_root)
        rows = list(csv.DictReader(io.StringIO(index.read_text(encoding="utf-8-sig")), strict=True))
        if not rows:
            raise ValueError
        fragments: set[str] = set()
        for row in rows:
            name = row.get("fragment_file")
            if not name or "\\" in name or ":" in name:
                raise ValueError
            relative = PurePosixPath(name)
            if (
                relative.is_absolute() or name != relative.as_posix()
                or any(part in {".", ".."} for part in relative.parts)
                or relative.suffix != ".md" or name in fragments
            ):
                raise ValueError
            target = knowledge.joinpath(*relative.parts)
            _assert_no_reparse(target, skill_root)
            target.resolve(strict=True).relative_to(knowledge.resolve(strict=True))
            if not target.is_file():
                raise ValueError
            fragments.add(name)
        # The package must support every possible stack branch under the fixed
        # headless defaults; runtime selection still reads only relevant fragments.
        if not set(required) <= fragments:
            raise ValueError
        entries = []
        for path in sorted(knowledge.rglob("*")):
            if _is_reparse_point(path):
                raise ValueError
            if path.is_file():
                entries.append({"path": path.relative_to(skill_root).as_posix(), "hash": hash_bytes(path.read_bytes())})
        return entries
    except (OSError, ValueError, UnicodeError, csv.Error):
        raise TeaAdapterError("tea-runtime-knowledge-invalid") from None


def _runtime_reference(runtime_root: str | Path, workflow_id: str) -> tuple[Path, dict[str, Any], str]:
    spec = _PACKAGED_WORKFLOWS.get(workflow_id)
    if spec is None:
        raise TeaAdapterError("tea-runtime-workflow-invalid")
    try:
        raw_root = Path(runtime_root)
        if _is_reparse_point(raw_root):
            raise ValueError
        root = raw_root.resolve(strict=True)
        skill_root = root / "skills" / "tea-quality"
        raw_reference = skill_root / "references" / spec["directory"]
        _assert_no_reparse(raw_reference, root)
        reference = raw_reference.resolve(strict=True)
        reference.relative_to(skill_root)
        if not reference.is_dir() or _is_reparse_point(reference):
            raise ValueError
        entries: list[dict[str, str]] = []
        for path in sorted(reference.rglob("*")):
            if _is_reparse_point(path):
                raise ValueError
            if path.is_file():
                relative = path.relative_to(skill_root).as_posix()
                entries.append({"path": relative, "hash": hash_bytes(path.read_bytes())})
        if not entries or not (reference / "SKILL.md").is_file():
            raise ValueError
        for relative in ("SKILL.md", "references/headless-contract.md"):
            path = skill_root / relative
            _assert_no_reparse(path, root)
            entries.append({"path": relative, "hash": hash_bytes(path.read_bytes())})
    except (OSError, ValueError):
        raise TeaAdapterError("tea-runtime-reference-invalid") from None
    if workflow_id not in {"framework", "ci"}:
        entries.extend(_knowledge_entries(skill_root, spec["knowledge"]))
    return reference, spec, content_hash(entries)


def validate_packaged_runtime(runtime_root: str | Path) -> dict[str, str]:
    """Preflight all shipped workflows without executing them or reading a project."""
    return {workflow: _runtime_reference(runtime_root, workflow)[2] for workflow in _PACKAGED_WORKFLOWS}


def _output_relative(value: object, expected_name: str) -> str:
    if not isinstance(value, str):
        raise TeaAdapterError("tea-runtime-output-invalid")
    try:
        path = PurePosixPath(value.replace("\\", "/"))
        if (
            path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.name != expected_name
        ):
            raise ValueError
    except ValueError:
        raise TeaAdapterError("tea-runtime-output-invalid") from None
    return path.as_posix()


def build_packaged_invocation(
    runtime_root: str | Path,
    workflow_id: str,
    context: Mapping[str, str],
    output_relative: str,
) -> dict[str, Any]:
    """Build one deterministic, project-config-independent TEA invocation."""

    _reference, spec, reference_hash = _runtime_reference(runtime_root, workflow_id)
    if not isinstance(context, Mapping) or set(context) != set(spec["fields"]):
        raise TeaAdapterError("tea-runtime-context-invalid")
    normalized: dict[str, str] = {}
    for field in spec["fields"]:
        value = context.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.encode("utf-8")) > _MAX_ARTIFACT_BYTES
            or _contains_unresolved_template(value)
        ):
            raise TeaAdapterError("tea-runtime-context-invalid")
        normalized[field] = value
    relative = _output_relative(output_relative, str(spec["output"]))
    material = {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "referenceHash": reference_hash,
        "context": normalized,
        "outputRelative": relative,
    }
    return {**material, "inputHash": content_hash(material)}


def validate_packaged_output(
    runtime_root: str | Path,
    project_root: str | Path,
    invocation: Mapping[str, Any],
    *,
    binding: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate one Agent-produced TEA Markdown artifact and issue a receipt."""

    if not isinstance(invocation, Mapping) or set(invocation) != {
        "schemaVersion", "workflowId", "referenceHash", "context",
        "outputRelative", "inputHash",
    }:
        raise TeaAdapterError("tea-runtime-invocation-invalid")
    workflow_id = invocation.get("workflowId")
    _reference, spec, reference_hash = _runtime_reference(runtime_root, str(workflow_id))
    material = {key: invocation[key] for key in (
        "schemaVersion", "workflowId", "referenceHash", "context", "outputRelative",
    )}
    if (
        invocation.get("schemaVersion") != 1
        or invocation.get("referenceHash") != reference_hash
        or invocation.get("inputHash") != content_hash(material)
    ):
        raise TeaAdapterError("tea-runtime-invocation-invalid")
    build_packaged_invocation(
        runtime_root, str(workflow_id), invocation.get("context"),
        str(invocation.get("outputRelative")),
    )
    relative = _output_relative(invocation.get("outputRelative"), str(spec["output"]))
    try:
        raw_root = Path(project_root)
        if _is_reparse_point(raw_root):
            raise ValueError
        root = raw_root.resolve(strict=True)
        if not root.is_dir() or _is_reparse_point(root):
            raise ValueError
        target = root.joinpath(*PurePosixPath(relative).parts)
        _assert_no_reparse(target, root)
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
        current = target
        while current != root:
            if _is_reparse_point(current):
                raise ValueError
            current = current.parent
        if not resolved.is_file() or resolved.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise ValueError
        data = resolved.read_bytes()
        text = data.decode("utf-8", errors="strict")
    except (OSError, UnicodeError, ValueError):
        raise TeaAdapterError("tea-runtime-output-invalid") from None
    heading_set = {
        line.lstrip("#").strip() for line in text.splitlines()
        if line.startswith("#")
    }
    if (
        not set(spec["headings"]) <= heading_set
        or _contains_unresolved_template(text)
    ):
        raise TeaAdapterError("tea-runtime-output-invalid")
    receipt = {
        "workflowId": workflow_id,
        "referenceHash": invocation["referenceHash"],
        "inputHash": invocation["inputHash"],
        "outputRelative": relative,
        "outputHash": hash_bytes(data),
        "status": "validated",
    }
    if binding is None:
        return receipt
    return _issue_tea_receipt(receipt, binding=binding)


def _issue_tea_receipt(
    validated_output: Mapping[str, Any],
    *,
    binding: Mapping[str, str],
) -> dict[str, Any]:
    """Bind one adapter-validated output to a V3 plan attempt and TEA slot."""

    if type(validated_output) is not dict or set(validated_output) != {
        "workflowId", "referenceHash", "inputHash", "outputRelative",
        "outputHash", "status",
    }:
        raise TeaAdapterError("tea-receipt-output-invalid")
    if type(binding) is not dict or set(binding) != {
        "planHash", "attemptRef", "stageId", "slotId", "moduleId",
    }:
        raise TeaAdapterError("tea-receipt-binding-invalid")
    workflow_id = validated_output["workflowId"]
    if type(workflow_id) is not str:
        raise TeaAdapterError("tea-receipt-output-invalid")
    expected = _TEA_BINDINGS.get(workflow_id)
    if expected is None or any(binding[key] != expected[key] for key in expected):
        raise TeaAdapterError("tea-receipt-binding-invalid")
    if (
        type(binding["planHash"]) is not str or _HASH.fullmatch(binding["planHash"]) is None
        or type(binding["attemptRef"]) is not str or _ID.fullmatch(binding["attemptRef"]) is None
    ):
        raise TeaAdapterError("tea-receipt-binding-invalid")
    for key in ("referenceHash", "inputHash", "outputHash"):
        if type(validated_output[key]) is not str or _HASH.fullmatch(validated_output[key]) is None:
            raise TeaAdapterError("tea-receipt-output-invalid")
    if validated_output["status"] != "validated":
        raise TeaAdapterError("tea-receipt-output-invalid")
    try:
        if _output_relative(
            validated_output["outputRelative"],
            str(_PACKAGED_WORKFLOWS[workflow_id]["output"]),
        ) != validated_output["outputRelative"]:
            raise ValueError
    except (KeyError, TeaAdapterError, ValueError):
        raise TeaAdapterError("tea-receipt-output-invalid") from None
    material = {
        "schemaVersion": 1,
        **binding,
        **validated_output,
    }
    return {**material, "receiptHash": content_hash(material)}


def validate_tea_receipt(
    receipt: Mapping[str, Any],
    *,
    plan_hash: str,
    stage_id: str,
    attempt_ref: str,
    slot_id: str,
    module_id: str,
    output_hash: str,
    runtime_root: str | Path | None = None,
) -> dict[str, Any]:
    """Fail closed on forged, stale, or misrouted TEA execution evidence."""

    if type(receipt) is not dict or set(receipt) != _TEA_RECEIPT_FIELDS:
        raise TeaAdapterError("tea-receipt-invalid")
    if receipt["schemaVersion"] != 1 or receipt["status"] != "validated":
        raise TeaAdapterError("tea-receipt-invalid")
    expected = {
        "planHash": plan_hash,
        "stageId": stage_id,
        "attemptRef": attempt_ref,
        "slotId": slot_id,
        "moduleId": module_id,
        "outputHash": output_hash,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise TeaAdapterError("tea-receipt-binding-invalid")
    workflow_id = receipt["workflowId"]
    if type(workflow_id) is not str:
        raise TeaAdapterError("tea-receipt-invalid")
    mapping = _TEA_BINDINGS.get(workflow_id)
    if mapping is None or any(receipt.get(key) != value for key, value in mapping.items()):
        raise TeaAdapterError("tea-receipt-binding-invalid")
    if runtime_root is not None:
        _reference, _spec, reference_hash = _runtime_reference(runtime_root, workflow_id)
        if receipt["referenceHash"] != reference_hash:
            raise TeaAdapterError("tea-runtime-reference-stale")
    for key in ("planHash", "referenceHash", "inputHash", "outputHash", "receiptHash"):
        if type(receipt[key]) is not str or _HASH.fullmatch(receipt[key]) is None:
            raise TeaAdapterError("tea-receipt-invalid")
    if type(receipt["attemptRef"]) is not str or _ID.fullmatch(receipt["attemptRef"]) is None:
        raise TeaAdapterError("tea-receipt-invalid")
    if _output_relative(receipt["outputRelative"], str(_PACKAGED_WORKFLOWS[workflow_id]["output"])) != receipt["outputRelative"]:
        raise TeaAdapterError("tea-receipt-invalid")
    material = {key: receipt[key] for key in _TEA_RECEIPT_FIELDS if key != "receiptHash"}
    if content_hash(material) != receipt["receiptHash"]:
        raise TeaAdapterError("tea-receipt-hash-invalid")
    return json.loads(json.dumps(receipt))


def is_tea_module_id(module_id: object) -> bool:
    """Return whether a selected module is one of the pinned TEA modules."""

    return type(module_id) is str and module_id in TEA_MODULE_IDS
