"""Fail-closed boundary for the optional SelfOpenWiki knowledge backend.

This module deliberately contains only the contract supplied by the
SelfOpenWiki adapter.  It does not start ``Setup.bat``/``Install.bat``, write a
Wiki, inspect credentials, or infer undocumented MCP fields.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


EXTERNAL_CAPABILITIES = frozenset({
    "update.external-agent.begin",
    "update.external-agent.reviewed-finalize",
})
PERSONAL_PROTOCOL = "selfopenwiki:personal-openwiki-v1"
PERSONAL_TOOL_NAMES = (
    "openwiki_begin",
    "openwiki_submit_plan",
    "openwiki_next_page",
    "openwiki_inspect_page_claims",
    "openwiki_submit_page",
    "openwiki_finish",
)
PERSONAL_CAPABILITIES = frozenset({
    "personal.lifecycle.begin",
    "personal.wiki-root.explicit",
    "personal.skill-adaptation.bound",
    "personal.lifecycle.plan",
    "personal.page-job.queue",
    "personal.lifecycle.next-page",
    "personal.candidate.write-package",
    "personal.claims.inspect",
    "personal.claims.binding",
    "personal.page.validate-assigned",
    "personal.claims.sparse-decisions",
    "personal.lifecycle.finish",
    "personal.c7-review-cas-publish",
})
_PERSONAL_STATUSES = {
    "openwiki_begin": {"planning", "resuming", "noop"},
    "openwiki_submit_plan": {"plan_accepted"},
    "openwiki_next_page": {"page_pending", "queue_complete"},
    "openwiki_inspect_page_claims": {"claims_inspected"},
    "openwiki_submit_page": {"page_accepted"},
    "openwiki_finish": {
        "review_required",
        "publish_pending",
        "repair_ready",
        "needs_clarification",
        "complete",
    },
}
MCP_ENTRY = Path("self-openwiki") / "mcp-server" / "dist" / "index.js"
VISUALIZER_ID = "selfopenwiki.zxh_wiki_viewer"
VISUALIZER_CONTRACT_SCHEMA = 1
VISUALIZER_URL_TEMPLATE = "http://127.0.0.1:{port}/wiki/local"


class SelfOpenWikiError(RuntimeError):
    """A contract or local preflight check failed closed."""


class SelfOpenWikiClient(Protocol):
    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]: ...


def _existing_absolute(path: str | Path, *, label: str, directory: bool) -> Path:
    if not isinstance(path, (str, Path)):
        raise SelfOpenWikiError(f"{label}-invalid")
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.is_symlink():
        raise SelfOpenWikiError(f"{label}-invalid")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise SelfOpenWikiError(f"{label}-missing") from None
    if directory and not resolved.is_dir():
        raise SelfOpenWikiError(f"{label}-not-directory")
    if not directory and not resolved.is_file():
        raise SelfOpenWikiError(f"{label}-not-file")
    return resolved


def _require_wiki_root(
    wiki_root: str | Path,
    *,
    confirmed_data_safety: bool,
    confirmed_git_authorization: bool,
) -> Path:
    if confirmed_data_safety is not True:
        raise SelfOpenWikiError("confirm-data-safety-required")
    root = _existing_absolute(wiki_root, label="wiki-root", directory=True)
    git_marker = root / ".git"
    if git_marker.is_symlink():
        raise SelfOpenWikiError("wiki-git-marker-invalid")
    is_git = git_marker.is_dir() or git_marker.is_file()
    if is_git and confirmed_git_authorization is not True:
        raise SelfOpenWikiError("confirm-git-authorization-required")
    return root


def _paths_equal(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def validate_external_status(value: object) -> dict[str, object]:
    """Validate only the frozen external-agent status fields.

    The current frozen status places ``contractSchema`` under ``version``.
    Legacy provider information may be present for display, but it is never
    used to establish external readiness.
    """

    if not isinstance(value, dict):
        raise SelfOpenWikiError("external-status-invalid")
    version = value.get("version")
    external = value.get("externalAgent")
    capabilities = value.get("capabilities")
    if (
        value.get("ok") is not True
        or value.get("executionMode") != "external_agent"
        or value.get("authRequired") is not False
        or not isinstance(version, dict)
        or version.get("contractSchema") != 2
        or not isinstance(external, dict)
        or set(external) != {"ready", "activeTransaction"}
        or not isinstance(external.get("ready"), bool)
        or not isinstance(capabilities, list)
    ):
        raise SelfOpenWikiError("external-status-invalid")

    capability_ids: list[str] = []
    for item in capabilities:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise SelfOpenWikiError("external-status-invalid")
        capability_ids.append(item["id"])
    if not EXTERNAL_CAPABILITIES <= set(capability_ids):
        raise SelfOpenWikiError("external-capability-missing")

    active = external["activeTransaction"]
    if active is not None:
        if (
            not isinstance(active, dict)
            or set(active) != {"transactionId", "generation", "state", "nextAction"}
            or not isinstance(active.get("transactionId"), str)
            or not active["transactionId"]
            or not isinstance(active.get("generation"), int)
            or isinstance(active["generation"], bool)
            or active["generation"] < 1
            or not isinstance(active.get("state"), str)
            or not active["state"]
            or not isinstance(active.get("nextAction"), str)
            or not active["nextAction"]
        ):
            raise SelfOpenWikiError("external-status-invalid")
    if external["ready"] is not True:
        raise SelfOpenWikiError("external-agent-not-ready")
    paths = value.get("paths")
    if (
        not isinstance(paths, dict)
        or set(paths) != {"openWikiRoot", "runtimeRoot", "wikiRoot"}
        or not all(isinstance(paths[key], str) and paths[key] for key in paths)
        or any(not Path(paths[key]).is_absolute() for key in paths)
    ):
        raise SelfOpenWikiError("external-status-paths-invalid")
    return dict(value)


def validate_personal_status(value: object) -> dict[str, object]:
    """Require the verified v2 personal lifecycle in addition to external mode."""

    result = validate_external_status(value)
    capabilities = result["capabilities"]
    capability_ids = {
        item["id"]
        for item in capabilities
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if not PERSONAL_CAPABILITIES <= capability_ids:
        raise SelfOpenWikiError("personal-capability-missing")
    return result


def validate_visualizer_status(value: object) -> dict[str, object]:
    """Require the live SelfOpenWiki-owned Viewer contract."""

    result = validate_personal_status(value)
    visualizer = result.get("visualizer")
    if not isinstance(visualizer, dict) or set(visualizer) != {
        "id",
        "contractSchema",
        "launcherPath",
        "loopbackOnly",
        "autoOpen",
        "wikiRootInput",
        "urlTemplate",
    }:
        raise SelfOpenWikiError("visualizer-contract-missing")
    if (
        visualizer.get("id") != VISUALIZER_ID
        or visualizer.get("contractSchema") != VISUALIZER_CONTRACT_SCHEMA
        or not isinstance(visualizer.get("launcherPath"), str)
        or not Path(visualizer["launcherPath"]).is_absolute()
        or visualizer.get("loopbackOnly") is not True
        or visualizer.get("autoOpen") is not False
        or not isinstance(visualizer.get("wikiRootInput"), dict)
        or set(visualizer["wikiRootInput"]) != {"kind", "flag"}
        or visualizer["wikiRootInput"].get("kind") != "argument"
        or visualizer["wikiRootInput"].get("flag") != "--wiki-root"
        or visualizer.get("urlTemplate") != VISUALIZER_URL_TEMPLATE
    ):
        raise SelfOpenWikiError("visualizer-contract-invalid")
    return result


def validate_personal_result(tool_name: object, value: object) -> dict[str, object]:
    """Validate the stable protocol/status envelope without inventing fields."""

    if tool_name not in PERSONAL_TOOL_NAMES:
        raise SelfOpenWikiError("personal-tool-invalid")
    if not isinstance(value, dict):
        raise SelfOpenWikiError("personal-result-invalid")
    if value.get("ok") is False:
        error = value.get("error")
        recovery = value.get("recovery")
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
            raise SelfOpenWikiError("personal-result-invalid")
        return dict(value)
    if (
        value.get("ok") is not True
        or value.get("protocol") != PERSONAL_PROTOCOL
        or value.get("status") not in _PERSONAL_STATUSES[tool_name]
    ):
        raise SelfOpenWikiError("personal-result-invalid")
    return dict(value)


class SelfOpenWikiAdapter:
    """Host-side preflight and strict MCP contract adapter."""

    def __init__(self, client: SelfOpenWikiClient):
        self._client = client

    def status(self) -> dict[str, object]:
        """Call ``openwiki_status`` first and require external readiness."""

        try:
            value = self._client.call_tool("openwiki_status", {})
        except Exception:
            raise SelfOpenWikiError("backend-unavailable") from None
        return validate_external_status(value)

    def personal_status(self) -> dict[str, object]:
        """Call ``openwiki_status`` first and require the v2 personal lifecycle."""

        try:
            value = self._client.call_tool("openwiki_status", {})
        except Exception:
            raise SelfOpenWikiError("backend-unavailable") from None
        return validate_personal_status(value)

    def override_wiki_root(self) -> str:
        """Return the module-owned Wiki root from the live MCP status."""

        status = self.personal_status()
        paths = status["paths"]
        assert isinstance(paths, dict)
        wiki_root = paths["wikiRoot"]
        assert isinstance(wiki_root, str)
        return wiki_root

    def personal_call(
        self, tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        """Route one v2 call through the bound Wiki module."""

        if tool_name not in PERSONAL_TOOL_NAMES:
            raise SelfOpenWikiError("personal-tool-invalid")
        status = self.personal_status()
        routed_arguments = dict(arguments)
        if tool_name == "openwiki_begin":
            paths = status["paths"]
            assert isinstance(paths, dict)
            wiki_root = paths["wikiRoot"]
            assert isinstance(wiki_root, str)
            requested = routed_arguments.get("wikiRoot")
            if requested is not None and requested != wiki_root:
                raise SelfOpenWikiError("personal-wiki-root-mismatch")
            routed_arguments["wikiRoot"] = wiki_root
        try:
            value = self._client.call_tool(tool_name, routed_arguments)
        except Exception:
            raise SelfOpenWikiError("backend-unavailable") from None
        return validate_personal_result(tool_name, value)

    @staticmethod
    def setup_command(repository_root: str | Path, *, with_mcp: bool = False) -> list[str]:
        root = _existing_absolute(repository_root, label="selfopenwiki-root", directory=True)
        installer = _existing_absolute(root / "Setup.bat", label="setup", directory=False)
        command = [str(installer)]
        if with_mcp:
            command.append("--with-mcp")
        return command

    @staticmethod
    def install_command(
        repository_root: str | Path,
        wiki_root: str | Path,
        *,
        confirmed_data_safety: bool,
        confirmed_git_authorization: bool = False,
    ) -> list[str]:
        root = _existing_absolute(repository_root, label="selfopenwiki-root", directory=True)
        installer = _existing_absolute(root / "Install.bat", label="install", directory=False)
        wiki = _require_wiki_root(
            wiki_root,
            confirmed_data_safety=confirmed_data_safety,
            confirmed_git_authorization=confirmed_git_authorization,
        )
        command = [
            str(installer),
            "--wiki-root",
            str(wiki),
            "--confirm-data-safety",
        ]
        if (wiki / ".git").is_dir() or (wiki / ".git").is_file():
            command.append("--confirm-git-authorization")
        return command

    def visualizer_spec(
        self,
        *,
        port: int = 3000,
        wiki_root: str | Path | None = None,
    ) -> dict[str, object]:
        status = validate_visualizer_status(self.personal_status())
        paths = status["paths"]
        assert isinstance(paths, dict)
        live_wiki = _existing_absolute(
            paths["wikiRoot"],
            label="wiki-root",
            directory=True,
        )
        if wiki_root is not None:
            requested_wiki = _existing_absolute(
                wiki_root,
                label="wiki-root",
                directory=True,
            )
            if not _paths_equal(requested_wiki, live_wiki):
                raise SelfOpenWikiError("personal-wiki-root-mismatch")
        visualizer = status["visualizer"]
        assert isinstance(visualizer, dict)
        launcher = _existing_absolute(
            visualizer["launcherPath"],
            label="visualizer",
            directory=False,
        )
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise SelfOpenWikiError("visualizer-port-invalid")
        command_line = (
            f'"{launcher}" --wiki-root "{live_wiki}" --port {port}'
        )
        return {
            "command": "cmd.exe",
            "args": ["/d", "/s", "/c", command_line],
            "url": visualizer["urlTemplate"].replace("{port}", str(port)),
            "wikiRoot": str(live_wiki),
        }

    def visualizer_command(
        self,
        repository_root: str | Path | None = None,
        wiki_root: str | Path | None = None,
        *,
        port: int = 3000,
    ) -> list[str]:
        """Return the live SelfOpenWiki launcher command.

        ``repository_root`` is retained only for call-site compatibility; the
        command never derives a launcher from it.
        """

        del repository_root
        spec = self.visualizer_spec(port=port, wiki_root=wiki_root)
        command = spec["command"]
        args = spec["args"]
        assert isinstance(command, str)
        assert isinstance(args, list)
        return [command, *args]
