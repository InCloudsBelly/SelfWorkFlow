"""Fail-closed boundary for the optional SelfOpenWiki knowledge backend.

This module deliberately contains only the contract supplied by the
SelfOpenWiki adapter.  It does not start ``Setup.bat``/``Install.bat``, write a
Wiki, inspect credentials, or infer undocumented MCP fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


EXTERNAL_CAPABILITIES = frozenset({
    "update.external-agent.begin",
    "update.external-agent.reviewed-finalize",
})
MCP_ENTRY = Path("self-openwiki") / "mcp-server" / "dist" / "index.js"
VISUALIZER_ENTRY = Path(".work") / "openwiki" / "dist" / "cli" / "cli.js"


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
    return dict(value)


class SelfOpenWikiAdapter:
    """Host-side preflight and status adapter; no side-effecting operations."""

    def __init__(self, client: SelfOpenWikiClient):
        self._client = client

    def status(self) -> dict[str, object]:
        """Call ``openwiki_status`` first and require external readiness."""

        try:
            value = self._client.call_tool("openwiki_status", {})
        except Exception:
            raise SelfOpenWikiError("backend-unavailable") from None
        return validate_external_status(value)

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

    @staticmethod
    def visualizer_command(
        repository_root: str | Path,
        wiki_root: str | Path,
        *,
        port: int = 4321,
    ) -> list[str]:
        root = _existing_absolute(repository_root, label="selfopenwiki-root", directory=True)
        wiki = _existing_absolute(
            wiki_root,
            label="wiki-root",
            directory=True,
        )
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise SelfOpenWikiError("visualizer-port-invalid")
        entry = _existing_absolute(
            root / VISUALIZER_ENTRY,
            label="visualizer",
            directory=False,
        )
        # The CLI contract supplies --no-open and a loopback-only deployment
        # requirement; no undocumented --host argument is invented here.
        return [
            "node",
            str(entry),
            "visualize",
            str(wiki),
            "--port",
            str(port),
            "--no-open",
        ]
