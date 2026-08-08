"""Trusted artifact value types and collector implementation details."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from types import MappingProxyType

from ._evidence_values import (
    MAX_ARTIFACT_OUTPUT_BYTES,
    MAX_ARTIFACT_RECORDS,
    WorkflowEvidenceError,
    canonical_content_hash,
    fail,
    freeze_json,
)
from .model import CapabilityState


_MAX_INVOCATION_ARGUMENTS = 256
_MAX_INVOCATION_ENVIRONMENT_KEYS = 128
_MAX_INVOCATION_FIELD_BYTES = 8192
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_TRUSTED_STORE_TOKEN = object()
_ARTIFACT_STATUSES = {"passed", "failed", "not-run", "partial", "not-applicable"}
_ARTIFACT_ATTRIBUTE_KEYS = MappingProxyType(
    {
        "capability": ("name", "state", "policyHash", "provider", "receiptId"),
        "review": (
            "provider", "receiptId", "inputHash", "outputHash", "decision",
            "level", "implementationActor", "implementationContext",
        ),
        "verification": (
            "provider", "receiptId", "inputHash", "outputHash", "invocationHash",
            "checkType", "exitCode", "verificationId", "validForSeconds",
        ),
        "owner-confirmation": (
            "provider", "receiptId", "inputHash", "outputHash", "decision", "scope",
        ),
        "owner-review": (
            "provider", "receiptId", "inputHash", "outputHash", "decision",
            "level", "implementationActor", "implementationContext",
        ),
        "behavioral-test": (
            "provider", "receiptId", "inputHash", "outputHash", "invocationHash",
            "checkType", "exitCode", "suite",
        ),
    }
)


def _bounded_text(value: object, *, optional: bool = False) -> bool:
    if type(value) is not str or (not optional and not value):
        return False
    try:
        return len(value.encode("utf-8")) <= _MAX_INVOCATION_FIELD_BYTES
    except Exception:
        return False


@dataclass(frozen=True, init=False)
class ExecutionInvocation:
    """Frozen canonical identity for one externally executed check."""

    executable: str
    module: str | None
    argv: tuple[str, ...]
    cwd: str
    environment_keys: tuple[str, ...]
    environment_hash: str
    input_hash: str
    invocation_hash: str

    def __init__(
        self,
        *,
        executable: str,
        module: str | None,
        argv: tuple[str, ...],
        cwd: str,
        environment: dict[str, str],
        input_content: object,
    ) -> None:
        try:
            valid_module = module is None or _bounded_text(module)
            valid_argv = (
                type(argv) is tuple
                and len(argv) <= _MAX_INVOCATION_ARGUMENTS
                and all(_bounded_text(item, optional=True) for item in argv)
            )
            valid_environment = (
                type(environment) is dict
                and len(environment) <= _MAX_INVOCATION_ENVIRONMENT_KEYS
                and all(
                    _bounded_text(key)
                    and _bounded_text(value, optional=True)
                    for key, value in environment.items()
                )
            )
            if (
                not _bounded_text(executable)
                or not valid_module
                or not valid_argv
                or not _bounded_text(cwd)
                or not valid_environment
            ):
                fail("artifact-collector-invalid")
            environment_keys = tuple(sorted(environment))
            environment_hash = canonical_content_hash(
                {key: environment[key] for key in environment_keys}
            )
            input_hash = canonical_content_hash(input_content)
            payload = {
                "executable": executable,
                "module": module,
                "argv": argv,
                "cwd": cwd,
                "environmentKeys": environment_keys,
                "environmentHash": environment_hash,
                "inputHash": input_hash,
            }
            invocation_hash = canonical_content_hash(payload)
        except WorkflowEvidenceError:
            fail("artifact-collector-invalid")
        except Exception:
            fail("artifact-collector-invalid")
        object.__setattr__(self, "executable", executable)
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "environment_keys", environment_keys)
        object.__setattr__(self, "environment_hash", environment_hash)
        object.__setattr__(self, "input_hash", input_hash)
        object.__setattr__(self, "invocation_hash", invocation_hash)


def output_content_hash(content: object) -> str:
    """Hash actual bounded receipt output, with bytes preserved exactly."""

    try:
        if type(content) is bytes:
            if len(content) > MAX_ARTIFACT_OUTPUT_BYTES:
                fail("artifact-collector-invalid")
            return "sha256:" + hashlib.sha256(content).hexdigest()
        if type(content) is str:
            encoded = content.encode("utf-8")
            if len(encoded) > MAX_ARTIFACT_OUTPUT_BYTES:
                fail("artifact-collector-invalid")
            return "sha256:" + hashlib.sha256(encoded).hexdigest()
        return canonical_content_hash(content)
    except WorkflowEvidenceError:
        fail("artifact-collector-invalid")
    except Exception:
        fail("artifact-collector-invalid")


def _mapping_entries(value: object, code: str) -> tuple[tuple[str, object], ...]:
    if type(value) not in (dict, _MAPPING_PROXY_TYPE):
        fail(code)
    try:
        entries = tuple(value.items())
    except Exception:
        fail(code)
    if any(type(key) is not str for key, _ in entries):
        fail(code)
    return entries


def _closed_mapping(value: object, keys: tuple[str, ...], code: str) -> dict[str, object]:
    entries = _mapping_entries(value, code)
    if len(entries) != len(keys) or {key for key, _ in entries} != set(keys):
        fail(code)
    return {key: item for key, item in entries}


def _ordered_sequence(value: object, code: str) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        fail(code)
    return tuple(value)


def _is_sha256(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _parse_timestamp(value: object, code: str) -> datetime:
    if type(value) is not str or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value
    ) is None:
        fail(code)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        fail(code)


@dataclass(frozen=True, init=False)
class TrustedArtifactStore:
    """Immutable resolver output produced only by ArtifactCollector.seal()."""

    _records: MappingProxyType
    _seal: object

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        fail("trusted-artifact-store-construction-denied")


def _new_trusted_store(records: dict[str, object]) -> TrustedArtifactStore:
    store = object.__new__(TrustedArtifactStore)
    object.__setattr__(store, "_records", MappingProxyType(dict(records)))
    object.__setattr__(store, "_seal", _TRUSTED_STORE_TOKEN)
    return store


class ArtifactCollector:
    """Explicit in-process trust boundary for externally verified receipts."""

    __slots__ = ("_records", "_identities", "_receipts", "_sealed")

    def __init__(self) -> None:
        self._records: dict[str, object] = {}
        self._identities: set[tuple[str, str]] = set()
        self._receipts: set[tuple[str, str]] = set()
        self._sealed = False

    def _record(self, artifact: dict[str, object]) -> str:
        if self._sealed or len(self._records) >= MAX_ARTIFACT_RECORDS:
            fail("artifact-collector-invalid")
        try:
            parsed = _parse_artifact(artifact, "artifact-collector-invalid")
            artifact_hash = canonical_content_hash(artifact)
            frozen = freeze_json(artifact)
        except WorkflowEvidenceError:
            fail("artifact-collector-invalid")
        except Exception:
            fail("artifact-collector-invalid")
        identity = (parsed["kind"], parsed["subjectId"])
        receipt = (
            parsed["attributes"]["provider"],
            parsed["attributes"]["receiptId"],
        )
        if identity in self._identities or receipt in self._receipts:
            fail("artifact-collector-invalid")
        self._identities.add(identity)
        self._receipts.add(receipt)
        self._records[artifact_hash] = frozen
        return artifact_hash

    def record_capability(
        self,
        *,
        name: str,
        state: CapabilityState,
        policy_hash: str,
        actor_id: str,
        context_id: str,
        recorded_at: str,
        provider: str,
        receipt_id: str,
    ) -> str:
        try:
            if type(state) is not CapabilityState:
                fail("artifact-collector-invalid")
            return self._record(
                {
                    "kind": "capability",
                    "status": "passed",
                    "subjectId": name,
                    "subjectHash": policy_hash,
                    "actorId": actor_id,
                    "contextId": context_id,
                    "relatedIds": [],
                    "recordedAt": recorded_at,
                    "attributes": {
                        "name": name,
                        "state": state.value,
                        "policyHash": policy_hash,
                        "provider": provider,
                        "receiptId": receipt_id,
                    },
                }
            )
        except WorkflowEvidenceError:
            fail("artifact-collector-invalid")
        except Exception:
            fail("artifact-collector-invalid")

    def record_attestation(
        self,
        *,
        kind: str,
        subject_id: str,
        subject_hash: str,
        actor_id: str,
        context_id: str,
        recorded_at: str,
        provider: str,
        receipt_id: str,
        output_content: object,
        decision: str,
        level: str = "",
        implementation_actor: str = "",
        implementation_context: str = "",
        scope: str = "",
    ) -> str:
        try:
            if kind in {"review", "owner-review"}:
                expected_output = {"decision": decision, "level": level}
            elif kind == "owner-confirmation":
                expected_output = {"decision": decision, "scope": scope}
            else:
                fail("artifact-collector-invalid")
            if (
                type(output_content) is not dict
                or set(output_content) != set(expected_output)
                or any(type(item) is not str for item in output_content.values())
                or output_content != expected_output
            ):
                fail("artifact-collector-invalid")
            common = {
                "provider": provider,
                "receiptId": receipt_id,
                "inputHash": subject_hash,
                "outputHash": output_content_hash(output_content),
                "decision": decision,
            }
            if kind in {"review", "owner-review"}:
                attributes = common | {
                    "level": level,
                    "implementationActor": implementation_actor,
                    "implementationContext": implementation_context,
                }
            else:
                attributes = common | {"scope": scope}
            return self._record(
                {
                    "kind": kind,
                    "status": "passed",
                    "subjectId": subject_id,
                    "subjectHash": subject_hash,
                    "actorId": actor_id,
                    "contextId": context_id,
                    "relatedIds": [],
                    "recordedAt": recorded_at,
                    "attributes": attributes,
                }
            )
        except WorkflowEvidenceError:
            fail("artifact-collector-invalid")
        except Exception:
            fail("artifact-collector-invalid")

    def record_execution(
        self,
        *,
        kind: str,
        status: str,
        subject_id: str,
        subject_hash: str,
        actor_id: str,
        context_id: str,
        related_ids: tuple[str, ...],
        recorded_at: str,
        provider: str,
        receipt_id: str,
        invocation: ExecutionInvocation,
        output_content: object,
        check_type: str,
        exit_code: int | None,
        verification_id: str = "",
        valid_for_seconds: int = 0,
        suite: str = "",
    ) -> str:
        try:
            if (
                type(related_ids) is not tuple
                or any(type(item) is not str or not item for item in related_ids)
                or len(set(related_ids)) != len(related_ids)
                or type(invocation) is not ExecutionInvocation
            ):
                fail("artifact-collector-invalid")
            common = {
                "provider": provider,
                "receiptId": receipt_id,
                "inputHash": subject_hash,
                "outputHash": output_content_hash(output_content),
                "invocationHash": invocation.invocation_hash,
                "checkType": check_type,
                "exitCode": exit_code,
            }
            if kind == "verification":
                attributes = common | {
                    "verificationId": verification_id,
                    "validForSeconds": valid_for_seconds,
                }
            elif kind == "behavioral-test":
                attributes = common | {"suite": suite}
            else:
                fail("artifact-collector-invalid")
            return self._record(
                {
                    "kind": kind,
                    "status": status,
                    "subjectId": subject_id,
                    "subjectHash": subject_hash,
                    "actorId": actor_id,
                    "contextId": context_id,
                    "relatedIds": list(related_ids),
                    "recordedAt": recorded_at,
                    "attributes": attributes,
                }
            )
        except WorkflowEvidenceError:
            fail("artifact-collector-invalid")
        except Exception:
            fail("artifact-collector-invalid")

    def seal(self) -> TrustedArtifactStore:
        if self._sealed:
            fail("artifact-collector-invalid")
        self._sealed = True
        return _new_trusted_store(self._records)


def _parse_artifact(value: object, code: str) -> dict[str, object]:
    record = _closed_mapping(
        value,
        (
            "kind", "status", "subjectId", "subjectHash", "actorId", "contextId",
            "relatedIds", "recordedAt", "attributes",
        ),
        code,
    )
    kind = record["kind"]
    if type(kind) is not str or kind not in _ARTIFACT_ATTRIBUTE_KEYS:
        fail(code)
    attributes = _closed_mapping(record["attributes"], _ARTIFACT_ATTRIBUTE_KEYS[kind], code)
    related = _ordered_sequence(record["relatedIds"], code)
    if (
        type(record["status"]) is not str
        or record["status"] not in _ARTIFACT_STATUSES
        or any(
            type(record[field]) is not str or not record[field]
            for field in ("subjectId", "actorId", "contextId")
        )
        or not _is_sha256(record["subjectHash"])
        or any(type(item) is not str or not item for item in related)
        or len(set(related)) != len(related)
    ):
        fail(code)
    _parse_timestamp(record["recordedAt"], code)
    if any(
        type(attributes[field]) is not str or not attributes[field]
        for field in ("provider", "receiptId")
    ):
        fail(code)
    if kind == "capability":
        if (
            any(
                type(attributes[field]) is not str or not attributes[field]
                for field in ("name", "state", "policyHash")
            )
            or attributes["state"] not in {"supported", "unsupported", "unverified"}
            or not _is_sha256(attributes["policyHash"])
        ):
            fail(code)
    elif (
        not _is_sha256(attributes["inputHash"])
        or not _is_sha256(attributes["outputHash"])
        or attributes["inputHash"] != record["subjectHash"]
    ):
        fail(code)
    if kind in {"review", "owner-review"}:
        if (
            type(attributes["decision"]) is not str
            or attributes["decision"] != "passed"
            or type(attributes["level"]) is not str
            or attributes["level"] not in {"L0", "L1", "L2", "L3"}
            or any(
                type(attributes[field]) is not str or not attributes[field]
                for field in ("implementationActor", "implementationContext")
            )
        ):
            fail(code)
    elif kind == "owner-confirmation":
        if (
            type(attributes["decision"]) is not str
            or attributes["decision"] != "authorized"
            or type(attributes["scope"]) is not str
            or attributes["scope"] != "replace-protected-rules"
        ):
            fail(code)
    elif kind in {"verification", "behavioral-test"}:
        exit_code = attributes["exitCode"]
        if (
            not _is_sha256(attributes["invocationHash"])
            or type(attributes["checkType"]) is not str
            or attributes["checkType"]
            not in {
                "unit-test",
                "integration-test",
                "static-analysis",
                "behavioral-test",
                "manual-check",
            }
            or (record["status"] == "passed" and (type(exit_code) is not int or exit_code != 0))
            or (record["status"] == "failed" and (type(exit_code) is not int or exit_code == 0))
            or (
                record["status"] in {"not-run", "partial", "not-applicable"}
                and exit_code is not None
            )
        ):
            fail(code)
    if kind == "verification":
        if (
            type(attributes["verificationId"]) is not str
            or not attributes["verificationId"]
            or type(attributes["validForSeconds"]) is not int
            or not 1 <= attributes["validForSeconds"] <= 86400
        ):
            fail(code)
    elif kind == "behavioral-test" and (
        type(attributes["suite"]) is not str or not attributes["suite"]
    ):
        fail(code)
    record["relatedIds"] = related
    record["attributes"] = attributes
    return record


def prepare_artifacts(store: object) -> tuple[dict[str, dict[str, object]], str | None]:
    """Validate and recompute every collector-sealed artifact in a store."""

    if (
        type(store) is not TrustedArtifactStore
        or getattr(store, "_seal", None) is not _TRUSTED_STORE_TOKEN
        or type(getattr(store, "_records", None)) is not _MAPPING_PROXY_TYPE
    ):
        fail("trusted-artifact-store-required")
    entries = _mapping_entries(store._records, "artifact-store-invalid")
    if len(entries) > MAX_ARTIFACT_RECORDS:
        fail("artifact-store-invalid")
    parsed: dict[str, dict[str, object]] = {}
    identities: set[tuple[object, object]] = set()
    receipts: set[tuple[object, object]] = set()
    for artifact_hash, value in entries:
        if not _is_sha256(artifact_hash):
            fail("artifact-store-invalid")
        artifact = _parse_artifact(value, "artifact-store-invalid")
        if canonical_content_hash(value) != artifact_hash:
            return {}, "artifact-hash-mismatch"
        identity = (artifact["kind"], artifact["subjectId"])
        receipt = (artifact["attributes"]["provider"], artifact["attributes"]["receiptId"])
        if identity in identities:
            return {}, "artifact-identity-duplicate"
        if receipt in receipts:
            return {}, "artifact-receipt-duplicate"
        identities.add(identity)
        receipts.add(receipt)
        parsed[artifact_hash] = artifact
    return parsed, None
