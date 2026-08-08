"""Optional mapping from the generic knowledge lifecycle to C7OpenWiki MCP."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol


TOOL_NAMES = (
    "openwiki_status",
    "openwiki_setup",
    "openwiki_prepare_sources",
    "openwiki_list_skills",
    "openwiki_query",
    "openwiki_update",
    "openwiki_set_default_model",
)
UPDATE_TERMINAL_STATES = {
    "published",
    "published_with_follow_up",
    "needs_clarification",
    "review_requires_attention",
    "failed",
}


class C7OpenWikiError(RuntimeError):
    pass


class MCPClient(Protocol):
    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]: ...


def load_tool_contract(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or set(value) != {"schemaVersion", "tools"}
        or value["schemaVersion"] != 1
        or not isinstance(value["tools"], list)
        or tuple(item.get("name") for item in value["tools"] if isinstance(item, dict))
        != TOOL_NAMES
        or any(item.get("strict") is not True for item in value["tools"])
    ):
        raise C7OpenWikiError("tool-contract-invalid")
    return value


def check_contract_drift(path: str | Path, expected_hash: str) -> str:
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        return "contract-unavailable"
    actual = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    return "current" if actual == expected_hash else "contract-drift"


def classify_follow_up(result: dict[str, object]) -> str:
    status = result.get("status")
    if status in {"published", "published_with_follow_up"}:
        return "report-or-autonomous-follow-up"
    if status == "review_requires_attention":
        return "attempt-bounded-autonomous-closure"
    if status == "needs_clarification":
        return "resume-grill-me-for-blocking-gap"
    return "report-failure"


class C7OpenWikiAdapter:
    def __init__(self, client: MCPClient):
        self._client = client

    def _call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        try:
            value = self._client.call_tool(name, arguments)
        except Exception:
            raise C7OpenWikiError("backend-unavailable") from None
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise C7OpenWikiError("backend-call-failed")
        return value

    def _status(self) -> dict[str, object]:
        status = self._call("openwiki_status", {})
        if status.get("status") != "status":
            raise C7OpenWikiError("status-invalid")
        return status

    @staticmethod
    def _bound_sources(
        source_manifest_id: str | None,
        source_confirmation: str | None,
    ) -> dict[str, str]:
        if (source_manifest_id is None) != (source_confirmation is None):
            raise C7OpenWikiError("source-binding-incomplete")
        if source_manifest_id is None:
            return {}
        if not source_manifest_id or not source_confirmation:
            raise C7OpenWikiError("source-binding-invalid")
        return {
            "sourceManifestId": source_manifest_id,
            "sourceConfirmation": source_confirmation,
        }

    def prepare_sources(self, paths: list[str]) -> dict[str, object]:
        self._status()
        if not paths or any(not isinstance(path, str) or not Path(path).is_absolute() for path in paths):
            raise C7OpenWikiError("absolute-source-path-required")
        return self._call("openwiki_prepare_sources", {"paths": paths})

    def query(
        self,
        instruction: str,
        *,
        source_manifest_id: str | None = None,
        source_confirmation: str | None = None,
        skills: list[str] | None = None,
        model_override: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self._status()
        arguments: dict[str, object] = {"instruction": instruction}
        arguments.update(self._bound_sources(source_manifest_id, source_confirmation))
        if skills is not None:
            if len(skills) != len(set(skills)):
                raise C7OpenWikiError("duplicate-skill")
            arguments["skills"] = skills
        if model_override is not None:
            arguments["modelOverride"] = model_override
        result = self._call("openwiki_query", arguments)
        if result.get("status") != "answered":
            raise C7OpenWikiError("query-status-invalid")
        return result

    def propose(self, instruction: str, **kwargs: object) -> dict[str, object]:
        query = self.query(instruction, **kwargs)
        return {
            "status": "proposed",
            "published": False,
            "answer": query.get("answer", ""),
            "runtimeSideEffects": ["oauth-refresh", "temporary-transaction"],
            "casStatus": "unverified-contract-gap",
        }

    def update(
        self,
        instruction: str,
        *,
        confirmed_by_user: bool,
        source_manifest_id: str | None = None,
        source_confirmation: str | None = None,
        skills: list[str] | None = None,
        model_override: dict[str, str] | None = None,
    ) -> dict[str, object]:
        if confirmed_by_user is not True:
            raise C7OpenWikiError("confirmation-required")
        self._status()
        arguments: dict[str, object] = {
            "instruction": instruction,
            "confirmedByUser": True,
        }
        arguments.update(self._bound_sources(source_manifest_id, source_confirmation))
        if skills is not None:
            if len(skills) != len(set(skills)):
                raise C7OpenWikiError("duplicate-skill")
            arguments["skills"] = skills
        if model_override is not None:
            arguments["modelOverride"] = model_override
        result = self._call("openwiki_update", arguments)
        if result.get("status") not in UPDATE_TERMINAL_STATES:
            raise C7OpenWikiError("update-status-invalid")
        return {**result, "followUpAction": classify_follow_up(result)}
