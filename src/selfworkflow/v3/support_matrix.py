"""Closed, content-addressed support evidence for Provider operations."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from selfworkflow.v3.contracts import ContractError, load_contract


_REQUIRED_EVIDENCE = (
    "source", "adapter", "positive", "false", "conflict", "failure",
    "contextCost", "nativeValidation",
)
_EVIDENCE_REF = re.compile(
    r"(?:sha256:[0-9a-f]{64}|ref:[a-z0-9][a-z0-9._/-]{0,255})"
)
_SUPPORT_SEAL = object()
_TEST_EVIDENCE_PREFIXES = (
    "ref:test/",
    "ref:tests/",
    "ref:fixture/",
    "ref:fixtures/",
    "ref:test-fixture/",
    "ref:test-fixtures/",
)


class SupportMatrixError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ValidatedSupportEntry:
    """Entry issued only by ``validate_support_matrix``."""

    __slots__ = ("_document", "_provider_id", "_matrix_hash", "__seal")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ValidatedSupportEntry is issued by validate_support_matrix")

    @property
    def document(self) -> dict[str, Any]:
        return _copy(self._document)

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def matrix_hash(self) -> str:
        return self._matrix_hash

    @property
    def entry_hash(self) -> str:
        return self._document["entryHash"]

    def _is_valid(self) -> bool:
        return getattr(self, "_ValidatedSupportEntry__seal", None) is _SUPPORT_SEAL


class ValidatedSupportMatrix:
    """Immutable validated matrix and its sealed entries."""

    __slots__ = ("_document", "_entries", "__seal")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ValidatedSupportMatrix is issued by validate_support_matrix")

    @property
    def document(self) -> dict[str, Any]:
        return _copy(self._document)

    @property
    def matrix_hash(self) -> str:
        return self._document["matrixHash"]

    @property
    def provider_id(self) -> str:
        return self._document["providerId"]

    def entry(self, entry_id: str) -> ValidatedSupportEntry:
        try:
            return self._entries[entry_id]
        except KeyError:
            raise SupportMatrixError("provider-support-entry-unknown") from None

    def _is_valid(self) -> bool:
        return getattr(self, "_ValidatedSupportMatrix__seal", None) is _SUPPORT_SEAL


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise SupportMatrixError("provider-support-canonical-invalid") from None


def _copy(value: Any) -> Any:
    return json.loads(_canonical(value))


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _entry_hash(entry: Mapping[str, Any]) -> str:
    return _hash({key: entry[key] for key in entry if key != "entryHash"})


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SupportMatrixError("provider-support-time-invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise SupportMatrixError("provider-support-time-invalid") from None


def _validate_entry(provider_id: str, entry: Mapping[str, Any]) -> None:
    if not isinstance(entry, Mapping):
        raise SupportMatrixError("provider-support-entry-invalid")
    if entry.get("entryHash") != _entry_hash(entry):
        raise SupportMatrixError("provider-support-entry-hash-invalid")
    observed = _parse_utc(entry.get("observedAt"))
    valid_until = entry.get("validUntil")
    if valid_until is not None and observed > _parse_utc(valid_until):
        raise SupportMatrixError("provider-support-time-invalid")
    state = entry.get("state")
    if state == "supported":
        evidence = entry.get("evidence")
        if not isinstance(evidence, Mapping) or any(
            not isinstance(evidence.get(key), str)
            or _EVIDENCE_REF.fullmatch(evidence[key]) is None
            for key in _REQUIRED_EVIDENCE
        ):
            reason = (
                "provider-support-evidence-incomplete"
                if not isinstance(evidence, Mapping)
                or any(key not in evidence for key in _REQUIRED_EVIDENCE)
                else "provider-support-evidence-invalid"
            )
            raise SupportMatrixError(reason)
        if provider_id == "fake" or provider_id.startswith(("fake.", "test.fake.")):
            raise SupportMatrixError("provider-fake-supported-production")
        if any(
            value.startswith(_TEST_EVIDENCE_PREFIXES)
            for value in evidence.values()
        ):
            raise SupportMatrixError("provider-test-evidence-production")


def _issue_entry(
    provider_id: str, matrix_hash: str, document: dict[str, Any],
) -> ValidatedSupportEntry:
    artifact = object.__new__(ValidatedSupportEntry)
    object.__setattr__(artifact, "_document", _copy(document))
    object.__setattr__(artifact, "_provider_id", provider_id)
    object.__setattr__(artifact, "_matrix_hash", matrix_hash)
    object.__setattr__(artifact, "_ValidatedSupportEntry__seal", _SUPPORT_SEAL)
    return artifact


def _issue_matrix(document: dict[str, Any]) -> ValidatedSupportMatrix:
    artifact = object.__new__(ValidatedSupportMatrix)
    entries = {
        entry["entryId"]: _issue_entry(
            document["providerId"], document["matrixHash"], entry,
        )
        for entry in document["entries"]
    }
    object.__setattr__(artifact, "_document", _copy(document))
    object.__setattr__(artifact, "_entries", entries)
    object.__setattr__(artifact, "_ValidatedSupportMatrix__seal", _SUPPORT_SEAL)
    return artifact


def build_support_matrix(
    provider_id: str, entries: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        normalized = [dict(entry) for entry in entries]
    except (TypeError, ValueError):
        raise SupportMatrixError("provider-support-entry-invalid") from None
    for entry in normalized:
        supplied = entry.pop("entryHash", None)
        computed = _entry_hash(entry)
        if supplied is not None and supplied != computed:
            raise SupportMatrixError("provider-support-entry-hash-invalid")
        entry["entryHash"] = computed
        _validate_entry(provider_id, entry)
    normalized.sort(key=lambda entry: str(entry.get("entryId", "")))
    matrix = {"schemaVersion": 3, "providerId": provider_id, "entries": normalized}
    matrix["matrixHash"] = _hash(matrix)
    validate_support_matrix(matrix)
    return matrix


def validate_support_matrix(matrix: Mapping[str, Any]) -> ValidatedSupportMatrix:
    if not isinstance(matrix, Mapping):
        raise SupportMatrixError("provider-support-matrix-invalid")
    value = _copy(dict(matrix))
    try:
        load_contract(
            "provider-support-matrix.schema.json",
            json.dumps(value, separators=(",", ":")),
        )
    except (ContractError, TypeError, ValueError):
        raise SupportMatrixError("provider-support-matrix-invalid") from None
    if value["matrixHash"] != _hash({key: value[key] for key in value if key != "matrixHash"}):
        raise SupportMatrixError("provider-support-matrix-hash-invalid")
    entry_ids: set[str] = set()
    tuples: set[tuple[object, ...]] = set()
    for entry in value["entries"]:
        if entry["entryId"] in entry_ids:
            raise SupportMatrixError("provider-support-entry-conflict")
        entry_ids.add(entry["entryId"])
        support_tuple = tuple(entry[key] for key in (
            "capabilityId", "operationId", "platform", "adapterVersion",
            "adapterHash", "sourceIdentityHash",
        ))
        if support_tuple in tuples:
            raise SupportMatrixError("provider-support-entry-conflict")
        tuples.add(support_tuple)
        _validate_entry(value["providerId"], entry)
    return _issue_matrix(value)


def is_selectable(
    artifact: ValidatedSupportEntry | ValidatedSupportMatrix,
    entry_id: str | None = None,
) -> bool:
    if isinstance(artifact, ValidatedSupportMatrix) and artifact._is_valid():
        if entry_id is None:
            raise SupportMatrixError("provider-support-entry-id-required")
        entry = artifact.entry(entry_id)
    elif isinstance(artifact, ValidatedSupportEntry) and artifact._is_valid():
        if entry_id is not None:
            raise SupportMatrixError("provider-support-entry-id-unexpected")
        entry = artifact
    else:
        raise SupportMatrixError("provider-support-entry-not-validated")
    return entry.document["state"] == "supported"
