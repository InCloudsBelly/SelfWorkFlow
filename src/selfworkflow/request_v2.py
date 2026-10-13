"""Closed V2 request validation and explicit V1 migration."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator
import json

from selfworkflow.capability_snapshot import normalize_capability_snapshot
from selfworkflow.implement_spec import ImplementSpecEvidenceError, validate_implement_spec_evidence
from selfworkflow.pipeline import canonical_hash


class RequestV2Error(ValueError):
    pass


_WRITE_OPERATIONS = frozenset({
    "implement", "debug", "document", "install", "publish", "knowledge-write",
})


def migrate_v1_request(request: Mapping[str, object]) -> dict[str, object]:
    required = {"schemaVersion", "stage", "operationType", "complexity", "risk", "writeTask", "superpowersSourceStatus", "capabilityStates"}
    allowed = required | {"ambiguity", "explicitGrill", "fileExtensions", "semanticTerms", "explicitSkills", "contextBudget"}
    if type(request) is not dict or set(request) - allowed or not required <= set(request) or request.get("schemaVersion") != 1:
        raise RequestV2Error("resolve-input-invalid")
    operation = request["operationType"]
    if operation == "read-only":
        operation = "analyze"
    if operation not in {"analyze", "design", "plan", "implement", "debug", "review", "verify", "document", "install", "publish", "knowledge-read", "knowledge-write"}:
        raise RequestV2Error("resolve-input-invalid")
    states = request["capabilityStates"]
    if type(states) is not dict or len(states) > 64:
        raise RequestV2Error("resolve-input-invalid")
    evidence = []
    for name in sorted(states):
        if type(name) is not str or type(states[name]) is not str:
            raise RequestV2Error("resolve-input-invalid")
        evidence.append({
            "name": name, "provider": "legacy-declaration",
            "subject": {"kind": "legacy", "id": name, "version": None, "build": None, "sourceLock": None},
            "state": "unverified", "observedAt": "1970-01-01T00:00:00Z", "validUntil": "9999-12-31T23:59:59Z",
            "evidenceRef": "legacy-unverified", "evidenceHash": "sha256:" + "0" * 64,
        })
    explicit = list(request.get("explicitSkills", []))
    if request.get("explicitGrill") is True:
        explicit.append("design-grill-me")
    return {
        "schemaVersion": 2, "operationType": operation,
        "complexity": request["complexity"], "risk": request["risk"],
        "writeTask": request["writeTask"], "ambiguity": request.get("ambiguity", False),
        "explicitModuleIds": list(dict.fromkeys(explicit)), "projectDefaultModuleIds": [],
        "projectMinimums": {"strength": "Light"},
        "capabilityEvidenceSnapshot": {"schemaVersion": 1, "capturedAt": "1970-01-01T00:00:01Z", "evidence": evidence},
    }


def normalize_request(request: Mapping[str, object], repository_root: Path) -> tuple[dict[str, object], str, tuple[dict[str, str], ...], dict[str, str], str, bool]:
    diagnostics: list[dict[str, str]] = []
    if type(request) is not dict:
        raise RequestV2Error("resolve-input-invalid")
    value = deepcopy(request)
    if value.get("schemaVersion") == 1:
        value = migrate_v1_request(value)
        diagnostics.append({"code": "legacy-capability-evidence-unverified", "severity": "warning"})
    try:
        if (
            isinstance(value.get("explicitModuleIds"), list)
            and "implement-spec" in value["explicitModuleIds"]
        ):
            try:
                validate_implement_spec_evidence(value.get("implementSpecEvidence"))
            except (KeyError, ImplementSpecEvidenceError, TypeError):
                raise RequestV2Error("implement-spec-evidence-invalid") from None
        schema = json.loads((repository_root / "schemas/resolve-request.schema.json").read_text(encoding="utf-8"))
        if next(Draft202012Validator(schema).iter_errors(value), None) is not None:
            raise RequestV2Error("resolve-input-invalid")
        if value["writeTask"] is not (value["operationType"] in _WRITE_OPERATIONS):
            raise RequestV2Error("resolve-input-invalid")
        if "implement-spec" in value["explicitModuleIds"]:
            try:
                validate_implement_spec_evidence(value["implementSpecEvidence"])
            except (KeyError, ImplementSpecEvidenceError, TypeError):
                raise RequestV2Error("implement-spec-evidence-invalid") from None
        snapshot, snapshot_hash, states, stale = normalize_capability_snapshot(value["capabilityEvidenceSnapshot"])
    except RequestV2Error:
        raise
    except Exception:
        raise RequestV2Error("resolve-input-invalid") from None
    value["capabilityEvidenceSnapshot"] = snapshot
    request_hash = canonical_hash(value)
    return value, request_hash, tuple(diagnostics), states, snapshot_hash, stale
