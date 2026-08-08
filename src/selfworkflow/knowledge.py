"""Vendor-independent protocol boundary for optional knowledge backends."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol


_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_UPDATE_STATES = {
    "published",
    "review-requires-attention",
    "needs-clarification",
    "conflict",
    "failed",
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
        "propose": {"status", "published", "expectedBase", "runtimeSideEffects"},
        "update": {
            "status", "confirmedByUser", "expectedBase", "actualBase", "reviewStatus",
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
            or payload.get("actualBase") != payload.get("expectedBase")
            or payload.get("reviewStatus") not in {"passed", "requires-attention", "not-run"}
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
    except Exception:
        if code_task:
            return {
                "status": "knowledge-sync-todo",
                "reason": "backend-unavailable-or-invalid",
            }
        return {"status": "failed", "reason": "backend-unavailable-or-invalid"}
