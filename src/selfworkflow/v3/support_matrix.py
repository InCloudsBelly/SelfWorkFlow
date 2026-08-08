"""Closed support evidence rules for Provider capability/operation pairs."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from selfworkflow.v3.contracts import ContractError, load_contract


_REQUIRED_EVIDENCE = (
    "source", "adapter", "positive", "false", "conflict", "failure",
    "contextCost", "nativeValidation",
)


class SupportMatrixError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise SupportMatrixError("provider-support-canonical-invalid") from None


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _validate_entry(provider_id: str, entry: Mapping[str, Any]) -> None:
    if not isinstance(entry, Mapping):
        raise SupportMatrixError("provider-support-entry-invalid")
    state = entry.get("state")
    if state == "supported":
        evidence = entry.get("evidence")
        if not isinstance(evidence, Mapping) or any(
            not isinstance(evidence.get(key), str) or not evidence[key]
            for key in _REQUIRED_EVIDENCE
        ):
            raise SupportMatrixError("provider-support-evidence-incomplete")
        if provider_id == "fake" or provider_id.startswith(("fake.", "test.fake.")):
            raise SupportMatrixError("provider-fake-supported-production")
    if state == "candidate":
        raise SupportMatrixError("provider-support-state-invalid")


def build_support_matrix(provider_id: str, entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    try:
        normalized = [dict(entry) for entry in entries]
    except (TypeError, ValueError):
        raise SupportMatrixError("provider-support-entry-invalid") from None
    entry_ids = [entry.get("entryId") for entry in normalized]
    if len(entry_ids) != len(set(entry_ids)):
        raise SupportMatrixError("provider-support-entry-conflict")
    for entry in normalized:
        _validate_entry(provider_id, entry)
    normalized.sort(key=lambda entry: str(entry.get("entryId", "")))
    matrix = {"schemaVersion": 3, "providerId": provider_id, "entries": normalized}
    matrix["matrixHash"] = _hash(matrix)
    validate_support_matrix(matrix)
    return matrix


def validate_support_matrix(matrix: Mapping[str, Any]) -> None:
    if not isinstance(matrix, Mapping):
        raise SupportMatrixError("provider-support-matrix-invalid")
    value = dict(matrix)
    try:
        load_contract("provider-support-matrix.schema.json", json.dumps(value, separators=(",", ":")))
    except (ContractError, TypeError, ValueError):
        raise SupportMatrixError("provider-support-matrix-invalid") from None
    if value.get("matrixHash") != _hash({key: value[key] for key in value if key != "matrixHash"}):
        raise SupportMatrixError("provider-support-matrix-hash-invalid")
    for entry in value.get("entries", []):
        _validate_entry(str(value.get("providerId", "")), entry)


def is_selectable(entry: Mapping[str, Any]) -> bool:
    return entry.get("state") == "supported"
