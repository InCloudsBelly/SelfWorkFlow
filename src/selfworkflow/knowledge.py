"""Vendor-independent protocol boundary for optional knowledge backends."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol


_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_UPDATE_STATES = {
    "published",
    "published-with-follow-up",
    "review-requires-attention",
    "needs-clarification",
    "conflict",
    "failed",
}
_FAILURE_STAGES = {
    "result_missing",
    "result_json_invalid",
    "result_schema_invalid",
    "result_binding_mismatch",
}


class KnowledgeContractError(ValueError):
    pass


@dataclass(frozen=True)
class KnowledgeRequest:
    action: str
    confirmed_by_user: bool = False
    expected_base: str | None = None
    payload: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.action not in {"read", "propose", "update"}:
            raise KnowledgeContractError("knowledge-action-invalid")
        if self.action == "update" and (
            self.confirmed_by_user is not True or not self.expected_base
        ):
            raise KnowledgeContractError("knowledge-update-guard-missing")


class KnowledgeBackend(Protocol):
    def execute(self, request: KnowledgeRequest) -> dict[str, object]: ...


def normalize_result(action: str, payload: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise KnowledgeContractError("knowledge-result-invalid")
    allowed = {
        "read": {"status", "knowledge"},
        "propose": {
            "status", "published", "expectedBase", "proposal", "contentHash",
            "runtimeSideEffects",
        },
        "update": {
            "status", "confirmedByUser", "expectedBase", "actualBase", "reviewStatus",
            "nativeResult",
        },
    }.get(action)
    if allowed is None or not set(payload) <= allowed:
        raise KnowledgeContractError("knowledge-result-invalid")
    if action == "read":
        if payload.get("status") != "ok" or not isinstance(payload.get("knowledge"), list):
            raise KnowledgeContractError("knowledge-read-invalid")
        for item in payload["knowledge"]:
            if not isinstance(item, dict) or set(item) != {
                "content", "sourceId", "revision", "contentHash", "verificationStatus"
            }:
                raise KnowledgeContractError("knowledge-evidence-missing")
            if (
                not all(isinstance(item[key], str) and item[key] for key in item)
                or _HASH.fullmatch(item["contentHash"]) is None
                or item["verificationStatus"] not in {"verified", "unverified", "conflicted"}
            ):
                raise KnowledgeContractError("knowledge-evidence-invalid")
    elif action == "propose":
        if (
            payload.get("status") not in {"proposed", "needs-clarification", "failed"}
            or payload.get("published") is not False
            or not isinstance(payload.get("expectedBase"), str)
            or not isinstance(payload.get("proposal"), str)
            or not payload["proposal"].strip()
            or _HASH.fullmatch(payload.get("contentHash", "")) is None
            or not isinstance(payload.get("runtimeSideEffects"), list)
            or any(
                item not in {"oauth-refresh", "temporary-transaction"}
                for item in payload["runtimeSideEffects"]
            )
        ):
            raise KnowledgeContractError("knowledge-proposal-invalid")
    else:
        if (
            payload.get("status") not in _UPDATE_STATES
            or payload.get("confirmedByUser") is not True
            or not isinstance(payload.get("expectedBase"), str)
            or (
                payload.get("actualBase") == payload.get("expectedBase")
                if payload.get("status") == "conflict"
                else payload.get("actualBase") != payload.get("expectedBase")
            )
            or payload.get("reviewStatus") not in {
                "passed", "follow-up", "requires-attention", "not-run"
            }
            or (
                "nativeResult" in payload
                and not isinstance(payload.get("nativeResult"), dict)
            )
        ):
            raise KnowledgeContractError("knowledge-update-invalid")
    return dict(payload)


def execute_knowledge(
    backend: KnowledgeBackend,
    request: KnowledgeRequest,
    *,
    code_task: bool,
) -> dict[str, object]:
    try:
        return normalize_result(request.action, backend.execute(request))
    except Exception as exception:
        result: dict[str, object] = {
            "status": "knowledge-sync-todo" if code_task else "failed",
            "reason": "backend-unavailable-or-invalid",
        }
        structured = _structured_failure(exception)
        if structured is not None:
            result.update(structured)
        return result


def _structured_failure(exception: Exception) -> dict[str, object] | None:
    try:
        error = exception.error
        recovery = exception.recovery
    except Exception:
        return None
    if (
        not isinstance(error, dict)
        or not {"code", "message", "retryable"} <= set(error)
        or not set(error) <= {"code", "details", "message", "retryable"}
        or not isinstance(error.get("code"), str)
        or not error["code"]
        or not isinstance(error.get("message"), str)
        or not error["message"]
        or not isinstance(error.get("retryable"), bool)
        or not isinstance(recovery, dict)
        or not set(recovery) <= {"action", "message"}
        or not isinstance(recovery.get("action"), str)
        or not recovery["action"]
        or (
            "message" in recovery
            and (
                not isinstance(recovery["message"], str)
                or not recovery["message"]
            )
        )
    ):
        return None
    copied_error = dict(error)
    if "details" in error:
        details = _safe_error_details(error["details"])
        if details is None:
            return None
        copied_error["details"] = details
    return {"error": copied_error, "recovery": dict(recovery)}


def _safe_error_details(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not set(value) <= {
        "attemptExpiresAt", "diagnostic", "failureStage", "limit", "lock", "paths",
    }:
        return None
    result = dict(value)
    if "attemptExpiresAt" in value and (
        not isinstance(value["attemptExpiresAt"], str)
        or not value["attemptExpiresAt"]
    ):
        return None
    if "limit" in value and (
        not isinstance(value["limit"], int)
        or isinstance(value["limit"], bool)
        or value["limit"] < 0
    ):
        return None
    if "diagnostic" in value and (
        not isinstance(value["diagnostic"], str)
        or not value["diagnostic"].strip()
        or len(value["diagnostic"]) > 4_096
    ):
        return None
    if "failureStage" in value and (
        not isinstance(value["failureStage"], str)
        or value["failureStage"] not in _FAILURE_STAGES
    ):
        return None
    if "lock" in value and value["lock"] not in {
        "operation", "credentials", "config", "wiki", "manifests",
    }:
        return None
    if "paths" in value:
        paths = value["paths"]
        if (
            not isinstance(paths, list)
            or len(paths) > 1_024
            or any(
                not isinstance(path, str) or len(path) > 32_768
                for path in paths
            )
        ):
            return None
        result["paths"] = list(paths)
    return result
