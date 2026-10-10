"""Project-local Graft binding and the SelfWorkFlow-owned update worker.

This module is deliberately smaller than a daemon or file watcher.  Hosts emit
one ``agent_write`` event after a code-changing turn; the worker coalesces that
event and performs one structural Graft build.  Query paths only inspect state
and never create the project cache.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import unicodedata

from selfworkflow.v3.providers.graft import graft_failure_details

from selfworkflow.v3.hashing import (
    HashingError, canonical_relative_path, content_hash, hash_file_content,
    project_root_hash,
)


_MAX_CHANGED_PATHS = 2048
_MAX_JSON_BYTES = 256 * 1024
_REPARSE = 0x400
_GRAPH_DIR = "graft"
_STATE_RELATIVE = (".cache", "selfworkflow")
_TOPIC_CONTEXT_RELATIVE = (".selfworkflow", "graft-deep")
_CONVERSATION_BINDINGS_DIR = ".conversation-bindings"
_CONVERSATION_DISABLED_SUFFIX = ".disabled.json"
_MAX_CONVERSATION_ID_BYTES = 256
_MAX_TOPIC_MANIFEST_BYTES = 256 * 1024
_MAX_TOPIC_SCOPE_FILES = 2048
_TOPIC_MANIFEST = "selfworkflow-topic.json"
_TOPIC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class GraftProjectError(ValueError):
    """Stable project binding/worker error without paths or command output."""

    def __init__(self, reason: str, *, diagnostics: dict[str, Any] | None = None) -> None:
        self.reason = reason
        self.diagnostics = diagnostics
        super().__init__(reason)


def _conversation_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _MAX_CONVERSATION_ID_BYTES
        or value != value.strip()
        or value != unicodedata.normalize("NFC", value)
        or any(ord(character) < 32 for character in value)
    ):
        raise GraftProjectError("graft-conversation-id-invalid")
    return value


def _topic_id(value: object) -> str:
    if not isinstance(value, str) or _TOPIC_ID.fullmatch(value) is None:
        raise GraftProjectError("graft-topic-id-invalid")
    return value


def _conversation_id_hash(value: str) -> str:
    return content_hash({
        "kind": "selfworkflow-graft-conversation-id",
        "conversationId": value,
    })


def _ensure_plain_directory(path: Path, reason: str) -> None:
    if path.exists():
        if _is_reparse(path) or not path.is_dir():
            raise GraftProjectError(reason)
        return
    try:
        path.mkdir()
    except OSError:
        raise GraftProjectError(reason) from None
    if _is_reparse(path) or not path.is_dir():
        raise GraftProjectError(reason)


def _conversation_binding_path(
    root: Path, conversation_id: str, *, create: bool,
) -> Path | None:
    state_root = root / ".selfworkflow"
    deep_root = state_root / "graft-deep"
    bindings_root = deep_root / _CONVERSATION_BINDINGS_DIR
    directories = (state_root, deep_root, bindings_root)
    for directory in directories:
        if create:
            _ensure_plain_directory(directory, "graft-conversation-bindings-invalid")
        elif not directory.exists():
            return None
        elif _is_reparse(directory) or not directory.is_dir():
            raise GraftProjectError("graft-conversation-bindings-invalid")
    path = bindings_root / (_conversation_id_hash(conversation_id)[7:] + ".json")
    if _is_reparse(path):
        raise GraftProjectError("graft-conversation-binding-invalid")
    if path.exists() and not path.is_file():
        raise GraftProjectError("graft-conversation-binding-invalid")
    return path


def _conversation_disabled_path(
    root: Path, conversation_id: str, *, create: bool,
) -> Path | None:
    path = _conversation_binding_path(root, conversation_id, create=create)
    if path is None:
        return None
    disabled = path.with_name(path.stem + _CONVERSATION_DISABLED_SUFFIX)
    if _is_reparse(disabled):
        raise GraftProjectError("graft-conversation-choice-invalid")
    if disabled.exists() and not disabled.is_file():
        raise GraftProjectError("graft-conversation-choice-invalid")
    return disabled


def _read_conversation_binding(path: Path | None) -> dict[str, str] | None:
    if path is None or not path.exists():
        return None
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise GraftProjectError("graft-conversation-binding-too-large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except GraftProjectError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        raise GraftProjectError("graft-conversation-binding-invalid") from None
    fields = {
        "kind", "version", "conversationIdHash", "topicId",
        "projectRootHash", "bindingHash",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise GraftProjectError("graft-conversation-binding-invalid")
    try:
        topic_id = _topic_id(value["topicId"])
        conversation_hash = value["conversationIdHash"]
        root_hash = value["projectRootHash"]
        binding_hash = value["bindingHash"]
        if (
            value["kind"] != "selfworkflow-graft-conversation-topic"
            or value["version"] != 1
            or not isinstance(conversation_hash, str)
            or not isinstance(root_hash, str)
            or not isinstance(binding_hash, str)
        ):
            raise ValueError
        material = {
            "kind": value["kind"], "version": value["version"],
            "conversationIdHash": conversation_hash, "topicId": topic_id,
            "projectRootHash": root_hash,
        }
        if binding_hash != content_hash(material):
            raise ValueError
    except (GraftProjectError, TypeError, ValueError):
        raise GraftProjectError("graft-conversation-binding-invalid") from None
    return {
        "topicId": topic_id,
        "conversationIdHash": conversation_hash,
        "projectRootHash": root_hash,
        "bindingHash": binding_hash,
    }


def resolve_conversation_topic(
    project_root: str | Path, conversation_id: str,
) -> dict[str, str] | None:
    """Load a project-local conversation-to-topic binding without side effects."""

    root = _safe_root(project_root)
    conversation = _conversation_id(conversation_id)
    path = _conversation_binding_path(root, conversation, create=False)
    binding = _read_conversation_binding(path)
    if binding is None:
        return None
    if (
        binding["conversationIdHash"] != _conversation_id_hash(conversation)
        or binding["projectRootHash"] != project_root_hash(root)
    ):
        raise GraftProjectError("graft-conversation-binding-invalid")
    return binding


def resolve_conversation_disabled(
    project_root: str | Path, conversation_id: str,
) -> dict[str, str] | None:
    """Load the explicit per-conversation no-Deep choice without side effects."""

    root = _safe_root(project_root)
    conversation = _conversation_id(conversation_id)
    path = _conversation_disabled_path(root, conversation, create=False)
    if path is None or not path.exists():
        return None
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise GraftProjectError("graft-conversation-choice-too-large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except GraftProjectError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        raise GraftProjectError("graft-conversation-choice-invalid") from None
    fields = {
        "kind", "version", "conversationIdHash", "choice",
        "projectRootHash", "bindingHash",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise GraftProjectError("graft-conversation-choice-invalid")
    material = {
        "kind": value.get("kind"), "version": value.get("version"),
        "conversationIdHash": value.get("conversationIdHash"),
        "choice": value.get("choice"),
        "projectRootHash": value.get("projectRootHash"),
    }
    if (
        material["kind"] != "selfworkflow-graft-conversation-choice"
        or material["version"] != 1
        or material["choice"] not in {"no-deep-topic", "global-only"}
        or not all(isinstance(material[key], str) for key in (
            "conversationIdHash", "projectRootHash",
        ))
        or not isinstance(value["bindingHash"], str)
        or value["bindingHash"] != content_hash(material)
        or value["conversationIdHash"] != _conversation_id_hash(conversation)
        or value["projectRootHash"] != project_root_hash(root)
    ):
        raise GraftProjectError("graft-conversation-choice-invalid")
    return {
        "choice": material["choice"],
        "conversationIdHash": value["conversationIdHash"],
        "projectRootHash": value["projectRootHash"],
        "bindingHash": value["bindingHash"],
    }


def resolve_conversation_choice(
    project_root: str | Path, conversation_id: str,
) -> dict[str, str] | None:
    """Return the durable topic/no-topic choice for one conversation."""

    topic = resolve_conversation_topic(project_root, conversation_id)
    disabled = resolve_conversation_disabled(project_root, conversation_id)
    if topic is not None and disabled is not None:
        raise GraftProjectError("graft-conversation-choice-conflict")
    if topic is not None:
        return {"decision": "topic", **topic}
    if disabled is not None:
        return {
            "decision": "disabled" if disabled["choice"] == "no-deep-topic" else "global",
            **disabled,
        }
    return None


def require_conversation_topic(
    project_root: str | Path, conversation_id: str,
) -> dict[str, str]:
    """Require an explicit Deep Topic before any conversation Graft use."""

    root = _safe_root(project_root)
    conversation = _conversation_id(conversation_id)
    choice = resolve_conversation_choice(root, conversation)
    if choice is None:
        raise GraftProjectError("graft-conversation-topic-unbound")
    if choice["decision"] != "topic":
        raise GraftProjectError("graft-disabled-for-conversation")
    return choice


def _write_conversation_binding(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if len(payload) > _MAX_JSON_BYTES:
        raise GraftProjectError("graft-conversation-binding-too-large")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, TypeError, ValueError):
        raise GraftProjectError("graft-conversation-binding-write-failed") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def bind_conversation_topic(
    project_root: str | Path, conversation_id: str, topic_id: str,
) -> dict[str, str]:
    """Persist one stable conversation-to-topic binding after a successful Deep run."""

    root = _safe_root(project_root)
    conversation = _conversation_id(conversation_id)
    topic = _topic_id(topic_id)
    if resolve_conversation_disabled(root, conversation) is not None:
        raise GraftProjectError("graft-conversation-choice-locked")
    existing = resolve_conversation_topic(root, conversation)
    if existing is not None:
        if existing["topicId"] != topic:
            raise GraftProjectError("graft-conversation-topic-mismatch")
        return {"status": "loaded", **existing}
    path = _conversation_binding_path(root, conversation, create=True)
    if path is None:
        raise GraftProjectError("graft-conversation-binding-invalid")
    material = {
        "kind": "selfworkflow-graft-conversation-topic",
        "version": 1,
        "conversationIdHash": _conversation_id_hash(conversation),
        "topicId": topic,
        "projectRootHash": project_root_hash(root),
    }
    value = {**material, "bindingHash": content_hash(material)}
    _write_conversation_binding(path, value)
    return {"status": "created", **value}


def disable_conversation_graft(
    project_root: str | Path, conversation_id: str,
) -> dict[str, str]:
    """Persist the explicit user choice to skip Deep/Graft in this conversation."""

    root = _safe_root(project_root)
    conversation = _conversation_id(conversation_id)
    if resolve_conversation_topic(root, conversation) is not None:
        raise GraftProjectError("graft-conversation-choice-locked")
    existing = resolve_conversation_disabled(root, conversation)
    if existing is not None:
        if existing["choice"] != "no-deep-topic":
            raise GraftProjectError("graft-conversation-choice-locked")
        return {"status": "loaded", **existing}
    path = _conversation_disabled_path(root, conversation, create=True)
    if path is None:
        raise GraftProjectError("graft-conversation-choice-invalid")
    material = {
        "kind": "selfworkflow-graft-conversation-choice",
        "version": 1,
        "conversationIdHash": _conversation_id_hash(conversation),
        "choice": "no-deep-topic",
        "projectRootHash": project_root_hash(root),
    }
    value = {**material, "bindingHash": content_hash(material)}
    _write_conversation_binding(path, value)
    return {"status": "disabled", **value}


def enable_conversation_global(
    project_root: str | Path, conversation_id: str,
) -> dict[str, str]:
    """Persist the explicit choice to use only the global non-Deep Map."""

    root = _safe_root(project_root)
    conversation = _conversation_id(conversation_id)
    if resolve_conversation_topic(root, conversation) is not None:
        raise GraftProjectError("graft-conversation-choice-locked")
    existing = resolve_conversation_disabled(root, conversation)
    if existing is not None:
        if existing["choice"] != "global-only":
            raise GraftProjectError("graft-conversation-choice-locked")
        return {"status": "loaded", **existing}
    path = _conversation_disabled_path(root, conversation, create=True)
    if path is None:
        raise GraftProjectError("graft-conversation-choice-invalid")
    material = {
        "kind": "selfworkflow-graft-conversation-choice",
        "version": 1,
        "conversationIdHash": _conversation_id_hash(conversation),
        "choice": "global-only",
        "projectRootHash": project_root_hash(root),
    }
    value = {**material, "bindingHash": content_hash(material)}
    _write_conversation_binding(path, value)
    return {"status": "global-only", **value}



def _is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE
    )


def _safe_root(value: object) -> Path:
    if not isinstance(value, (str, Path)):
        raise GraftProjectError("graft-project-root-invalid")
    raw = Path(value)
    if not raw.is_absolute() or not raw.exists() or not raw.is_dir():
        raise GraftProjectError("graft-project-root-invalid")
    try:
        resolved = raw.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise GraftProjectError("graft-project-root-invalid") from None
    current = Path(raw.anchor)
    try:
        for part in raw.parts[1:]:
            current /= part
            if current.exists() and _is_reparse(current):
                raise GraftProjectError("graft-cache-boundary-invalid")
    except GraftProjectError:
        raise
    except OSError:
        raise GraftProjectError("graft-project-root-invalid") from None
    if resolved != raw.resolve(strict=True):
        raise GraftProjectError("graft-project-root-invalid")
    if not ((raw / ".git").is_dir() or (raw / ".git").is_file()):
        raise GraftProjectError("graft-project-root-invalid")
    return resolved


def _binding(root: Path) -> tuple[Path, Path]:
    graph = root / _GRAPH_DIR
    if graph.exists() and (not graph.is_dir() or _is_reparse(graph)):
        raise GraftProjectError("graft-cache-boundary-invalid")
    state = graph.joinpath(*_STATE_RELATIVE)
    for candidate in (graph, graph / ".cache", state):
        if candidate.exists() and _is_reparse(candidate):
            raise GraftProjectError("graft-cache-boundary-invalid")
    try:
        graph.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        raise GraftProjectError("graft-cache-boundary-invalid") from None
    return graph, state


def _topic_context(root: Path, value: object) -> Path | None:
    """Validate an existing topic graph context bound below one project."""

    if value is None:
        return None
    if not isinstance(value, (str, Path)):
        raise GraftProjectError("graft-topic-context-invalid")
    raw = Path(value)
    if not raw.is_absolute() or not raw.exists() or not raw.is_dir():
        raise GraftProjectError("graft-topic-context-invalid")
    try:
        relative = raw.relative_to(root)
    except (ValueError, OSError):
        raise GraftProjectError("graft-topic-context-invalid") from None
    parts = relative.parts
    if (
        len(parts) != 4
        or tuple(part.casefold() for part in parts[:2])
        != _TOPIC_CONTEXT_RELATIVE
        or not parts[2]
        or parts[3].casefold() != "graft"
    ):
        raise GraftProjectError("graft-topic-context-invalid")
    current = root
    try:
        for part in parts:
            current /= part
            if not current.exists() or _is_reparse(current):
                raise GraftProjectError("graft-topic-context-invalid")
        context = raw.resolve(strict=True)
        context.relative_to(root)
    except GraftProjectError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise GraftProjectError("graft-topic-context-invalid") from None
    return context


def _conversation_topic_context(
    root: Path, conversation_id: str, explicit_context: str | None,
) -> tuple[Path, dict[str, str]]:
    binding = require_conversation_topic(root, conversation_id)
    bound_context = _topic_context(
        root,
        root / ".selfworkflow" / "graft-deep" / binding["topicId"] / "graft",
    )
    if bound_context is None:
        raise GraftProjectError("graft-topic-context-invalid")
    if explicit_context is not None:
        supplied_context = _topic_context(root, explicit_context)
        if supplied_context != bound_context:
            raise GraftProjectError("graft-conversation-topic-mismatch")
    return bound_context, binding


def _topic_scope_status(root: Path, context: Path, topic_id: str) -> dict[str, Any]:
    """Compare the persisted Topic scope with current source bytes, read-only."""

    manifest_path = context.parent / _TOPIC_MANIFEST
    if not manifest_path.exists():
        return {"topicFreshness": "missing", "topicStaleFiles": []}
    if _is_reparse(manifest_path) or not manifest_path.is_file():
        raise GraftProjectError("graft-topic-manifest-invalid")
    try:
        if manifest_path.stat().st_size > _MAX_TOPIC_MANIFEST_BYTES:
            raise GraftProjectError("graft-topic-manifest-too-large")
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except GraftProjectError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        raise GraftProjectError("graft-topic-manifest-invalid") from None
    if (
        not isinstance(value, dict)
        or value.get("kind") != "selfworkflow-graft-topic"
        or value.get("version") != 1
        or value.get("topicId") != topic_id
        or value.get("projectRootHash") != project_root_hash(root)
        or not isinstance(value.get("scopeFiles"), list)
        or not 0 < len(value["scopeFiles"]) <= _MAX_TOPIC_SCOPE_FILES
        or not isinstance(value.get("scopeHash"), str)
        or value.get("freshness") != "fresh"
    ):
        raise GraftProjectError("graft-topic-manifest-invalid")
    stale: list[str] = []
    for entry in value["scopeFiles"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "size", "sha256"}
            or not isinstance(entry.get("path"), str)
            or type(entry.get("size")) is not int
            or entry["size"] < 0
            or not isinstance(entry.get("sha256"), str)
        ):
            raise GraftProjectError("graft-topic-manifest-invalid")
        try:
            relative = canonical_relative_path(entry["path"])
        except (HashingError, TypeError, ValueError):
            raise GraftProjectError("graft-topic-manifest-invalid") from None
        if (
            relative == _GRAPH_DIR
            or relative.startswith(f"{_GRAPH_DIR}/")
            or relative == ".selfworkflow"
            or relative.startswith(".selfworkflow/")
        ):
            raise GraftProjectError("graft-topic-manifest-invalid")
        candidate = root.joinpath(*relative.split("/"))
        if _is_reparse(candidate):
            raise GraftProjectError("graft-topic-scope-boundary-invalid")
        try:
            size, digest = hash_file_content(candidate, max_bytes=256 * 1024 * 1024)
        except (HashingError, OSError):
            stale.append(relative)
            continue
        current = {"path": relative, "size": size, "sha256": digest}
        if current != entry:
            stale.append(relative)
    if content_hash(value["scopeFiles"]) != value["scopeHash"]:
        raise GraftProjectError("graft-topic-manifest-invalid")
    return {
        "topicFreshness": "stale" if stale else "fresh",
        "topicStaleFiles": stale,
    }


def list_graft_topics(project_root: str | Path) -> dict[str, Any]:
    """List selectable project-local Deep Topics without invoking Graft."""

    root = _safe_root(project_root)
    state_root = root / ".selfworkflow"
    deep_root = state_root / "graft-deep"
    if not state_root.exists():
        return {"topics": []}
    if _is_reparse(state_root) or not state_root.is_dir():
        raise GraftProjectError("graft-topic-catalog-invalid")
    if not deep_root.exists():
        return {"topics": []}
    if _is_reparse(deep_root) or not deep_root.is_dir():
        raise GraftProjectError("graft-topic-catalog-invalid")
    topics: list[dict[str, Any]] = []
    try:
        candidates = sorted(deep_root.iterdir(), key=lambda item: item.name)
    except OSError:
        raise GraftProjectError("graft-topic-catalog-invalid") from None
    for candidate in candidates:
        if candidate.name == _CONVERSATION_BINDINGS_DIR:
            continue
        if _is_reparse(candidate):
            raise GraftProjectError("graft-topic-catalog-invalid")
        if not candidate.is_dir():
            continue
        try:
            topic_id = _topic_id(candidate.name)
        except GraftProjectError:
            continue
        relative_context = f".selfworkflow/graft-deep/{topic_id}/graft"
        context = candidate / "graft"
        item: dict[str, Any] = {
            "topicId": topic_id,
            "contextDir": relative_context,
            "selectable": False,
        }
        try:
            valid_context = _topic_context(root, context)
            status = _topic_scope_status(root, valid_context, topic_id)
            item.update(status)
            item["selectable"] = status["topicFreshness"] in {"fresh", "stale"}
        except GraftProjectError as error:
            item.update({
                "topicFreshness": "invalid",
                "topicStaleFiles": [],
                "reason": error.reason,
            })
        topics.append(item)
    return {"topics": topics}


def choose_conversation_topic(
    project_root: str | Path, conversation_id: str, topic_id: str,
) -> dict[str, str]:
    """Bind a user-selected existing Topic without running a Deep build."""

    root = _safe_root(project_root)
    conversation = _conversation_id(conversation_id)
    if resolve_conversation_disabled(root, conversation) is not None:
        raise GraftProjectError("graft-conversation-choice-locked")
    topic = _topic_id(topic_id)
    catalog = list_graft_topics(root)
    selected = next(
        (item for item in catalog["topics"] if item["topicId"] == topic), None,
    )
    if selected is None or selected.get("selectable") is not True:
        raise GraftProjectError("graft-topic-not-selectable")
    return bind_conversation_topic(project_root, conversation_id, topic)


def conversation_topic_options(
    project_root: str | Path, conversation_id: str,
) -> dict[str, Any]:
    """Return Topic choices and the durable choice for a new conversation."""

    root = _safe_root(project_root)
    conversation = _conversation_id(conversation_id)
    choice = resolve_conversation_choice(root, conversation)
    result = {
        "conversationId": conversation,
        "topics": list_graft_topics(root)["topics"],
    }
    if choice is None:
        result["conversationChoice"] = {
            "conversationId": conversation,
            "choice": "unbound",
            "status": "unbound",
        }
    elif choice["decision"] == "topic":
        result["conversationBinding"] = {
            "conversationId": conversation,
            "topicId": choice["topicId"],
            "bindingHash": choice["bindingHash"],
            "status": "loaded",
        }
    else:
        result["conversationChoice"] = {
            "conversationId": conversation,
            "choice": choice["choice"],
            "bindingHash": choice["bindingHash"],
            "status": "disabled" if choice["decision"] == "disabled" else "global-only",
        }
    return result


def _topic_refresh_status(
    root: Path, conversation_id: str | None,
) -> dict[str, Any] | None:
    """Return the next main-Agent action after a global structural update."""

    if conversation_id is None:
        return None
    try:
        choice = resolve_conversation_choice(root, conversation_id)
    except GraftProjectError as error:
        return {
            "status": "unverified", "action": "stop",
            "conversationId": conversation_id, "reason": error.reason,
        }
    if choice is None:
        return {
            "status": "unbound", "action": "topic-selection-required",
            "conversationId": conversation_id,
        }
    if choice["decision"] in {"disabled", "global"}:
        return {
            "status": "disabled", "action": "none",
            "conversationId": conversation_id,
        }
    try:
        context = _topic_context(
            root,
            root / ".selfworkflow" / "graft-deep" / choice["topicId"] / "graft",
        )
    except GraftProjectError as error:
        return {
            "status": "unverified", "action": "stop",
            "conversationId": conversation_id, "reason": error.reason,
        }
    if context is None:
        return {
            "status": "unverified", "action": "stop",
            "conversationId": conversation_id,
        }
    try:
        status = _topic_scope_status(root, context, choice["topicId"])
    except GraftProjectError as error:
        return {
            "status": "unverified", "action": "stop",
            "conversationId": conversation_id, "reason": error.reason,
        }
    freshness = status["topicFreshness"]
    if freshness == "fresh":
        return {
            "status": "fresh", "action": "none", "topicId": choice["topicId"],
            "staleFiles": [], "conversationId": conversation_id,
        }
    if freshness == "stale":
        return {
            "status": "refresh-required", "action": "run-graft-deep",
            "topicId": choice["topicId"],
            "staleFiles": status["topicStaleFiles"],
            "conversationId": conversation_id,
        }
    return {
        "status": "unverified", "action": "stop",
        "topicId": choice["topicId"], "staleFiles": [],
        "conversationId": conversation_id,
    }


def _ignore_has(root: Path) -> bool:
    ignore = root / ".gitignore"
    if not ignore.exists():
        return False
    if ignore.is_symlink() or _is_reparse(ignore) or not ignore.is_file():
        raise GraftProjectError("graft-cache-boundary-invalid")
    try:
        return any(
            line.strip() in {"/graft/", "graft/", "graft"}
            for line in ignore.read_text(encoding="utf-8").splitlines()
        )
    except (OSError, UnicodeError):
        raise GraftProjectError("graft-cache-boundary-invalid") from None


def _ensure_ignore(root: Path) -> None:
    if _ignore_has(root):
        return
    target = root / ".gitignore"
    previous = target.read_bytes() if target.exists() else b""
    suffix = b"" if not previous or previous.endswith(b"\n") else b"\n"
    payload = previous + suffix + b"# SelfWorkFlow local Graft cache\n/graft/\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".selfworkflow-gitignore-", suffix=".tmp",
            dir=root, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    except (OSError, ValueError):
        raise GraftProjectError("graft-cache-ignore-write-failed") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if len(payload) > _MAX_JSON_BYTES:
        raise GraftProjectError("graft-worker-state-too-large")
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, TypeError, ValueError):
        raise GraftProjectError("graft-worker-state-write-failed") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _read_json(path: Path, default: Mapping[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    if path.is_symlink() or _is_reparse(path) or not path.is_file():
        raise GraftProjectError("graft-worker-state-invalid")
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise GraftProjectError("graft-worker-state-too-large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except GraftProjectError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        raise GraftProjectError("graft-worker-state-invalid") from None
    if not isinstance(value, dict):
        raise GraftProjectError("graft-worker-state-invalid")
    return value


def _lock_path(state: Path) -> Path:
    return state / "worker.lock"


class _WorkerLock:
    def __init__(self, state: Path) -> None:
        self.path = _lock_path(state)
        self.handle: Any = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = self.path.open("xb")
            self.handle.write(str(os.getpid()).encode("ascii"))
            self.handle.flush()
        except OSError:
            if self.handle is not None:
                self.handle.close()
            raise GraftProjectError("graft-worker-locked") from None
        return self

    def __exit__(self, *_args: object) -> None:
        try:
            if self.handle is not None:
                self.handle.close()
        finally:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


def _relative_changed_paths(root: Path, values: Sequence[str]) -> list[str]:
    if not isinstance(values, (list, tuple)) or not values or len(values) > _MAX_CHANGED_PATHS:
        raise GraftProjectError("graft-event-invalid")
    result: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise GraftProjectError("graft-event-invalid")
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve(strict=False).relative_to(root)
            except (OSError, ValueError):
                raise GraftProjectError("graft-event-path-outside-project") from None
        parts = candidate.parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise GraftProjectError("graft-event-invalid")
        relative = "/".join(parts)
        if relative == _GRAPH_DIR or relative.startswith(f"{_GRAPH_DIR}/"):
            raise GraftProjectError("graft-event-path-invalid")
        result.add(relative)
    return sorted(result)


class GraftProjectLifecycle:
    """Bind one project and run the one-owner structural update worker."""

    def __init__(self, provider: object) -> None:
        if (
            not callable(getattr(provider, "provider_preflight", None))
            or not callable(getattr(provider, "status", None))
            or not callable(getattr(provider, "build_structural", None))
        ):
            raise GraftProjectError("graft-provider-invalid")
        self._provider = provider

    def _provider_preflight(self) -> dict[str, Any]:
        try:
            result = self._provider.provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-unavailable")
            raise GraftProjectError(reason, **graft_failure_details(error)) from None
        if (
            not isinstance(result, Mapping)
            or result.get("providerStatus") != "verified"
        ):
            raise GraftProjectError("graft-provider-unavailable")
        return dict(result)

    def _status(
        self, root: Path, provider_report: Mapping[str, Any],
        *, context_dir: Path | None = None,
    ) -> dict[str, Any]:
        try:
            if context_dir is None:
                result = self._provider.status(str(root))
            else:
                result = self._provider.status(
                    str(root), context_dir=str(context_dir),
                )
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            raise GraftProjectError(reason, **graft_failure_details(error)) from None
        if not isinstance(result, Mapping):
            raise GraftProjectError("graft-status-invalid")
        freshness = result.get("freshness")
        if freshness not in {"fresh", "stale", "missing"}:
            raise GraftProjectError("graft-status-invalid")
        enriched = dict(result)
        enriched["providerStatus"] = "verified"
        enriched["graphStatus"] = freshness
        if isinstance(provider_report.get("version"), str):
            enriched["providerVersion"] = provider_report["version"]
        if isinstance(provider_report.get("queryCapabilities"), list):
            enriched["queryCapabilities"] = list(provider_report["queryCapabilities"])
        return enriched

    def query_status(
        self, project_root: str, *, context_dir: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        root = _safe_root(project_root)
        binding = None
        choice = None
        if conversation_id is not None:
            choice = resolve_conversation_choice(root, conversation_id)
            if choice is not None and choice["decision"] == "disabled":
                return {
                    "providerId": "graft", "status": "disabled",
                    "providerStatus": "not-used", "graphStatus": "disabled",
                    "freshness": "disabled", "reason": "graft-disabled-for-conversation",
                    "conversationChoice": {
                        "conversationId": conversation_id,
                        "choice": choice["choice"],
                        "bindingHash": choice["bindingHash"],
                        "status": "disabled",
                    },
                }
            if choice is not None and choice["decision"] == "global":
                context = None
            else:
                context, binding = _conversation_topic_context(
                    root, conversation_id, context_dir,
                )
        else:
            context = _topic_context(root, context_dir)
        if context_dir is None and conversation_id is None:
            _binding(root)
        topic_status: dict[str, Any] = {}
        if binding is not None:
            try:
                topic_status = _topic_scope_status(
                    root, context, binding["topicId"],
                )
            except Exception as error:
                reason = getattr(error, "reason", "graft-topic-manifest-invalid")
                return {
                    "providerId": "graft", "status": "unverified",
                    "providerStatus": "verified", "graphStatus": "unknown",
                    "reason": reason,
                }
        try:
            provider_report = self._provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "unavailable",
                "graphStatus": "unknown", "reason": reason,
                **graft_failure_details(error),
            }
        try:
            result = self._status(root, provider_report, context_dir=context)
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "verified",
                "graphStatus": "unknown", "reason": reason,
                **graft_failure_details(error),
            }
        if not isinstance(result, Mapping):
            raise GraftProjectError("graft-status-invalid")
        enriched = dict(result)
        if topic_status and topic_status.get("topicFreshness") != "fresh":
            enriched["freshness"] = "stale"
            enriched["graphStatus"] = "stale"
        enriched.update(topic_status)
        if binding is not None:
            enriched["conversationBinding"] = {
                "conversationId": conversation_id,
                "topicId": binding["topicId"],
                "bindingHash": binding["bindingHash"],
                "contextDir": str(context),
                "status": "loaded",
            }
        if choice is not None and choice["decision"] == "global":
            enriched["conversationChoice"] = {
                "conversationId": conversation_id,
                "choice": choice["choice"],
                "bindingHash": choice["bindingHash"],
                "status": "global-only",
            }
        return enriched

    def check_freshness(
        self, project_root: str, *, conversation_id: str,
    ) -> dict[str, Any]:
        """Check the bound Topic and the independent global structural map."""

        root = _safe_root(project_root)
        conversation = _conversation_id(conversation_id)
        provider_report = self._provider_preflight()
        global_status = self._status(root, provider_report)
        topic = _topic_refresh_status(root, conversation)
        if topic is None:
            raise GraftProjectError("graft-topic-refresh-result-missing")
        topic_fresh = topic.get("status") in {"fresh", "disabled"}
        global_fresh = global_status.get("freshness") == "fresh"
        next_action = "none"
        if topic.get("action") not in {"none", None}:
            next_action = str(topic["action"])
        elif not global_fresh:
            next_action = "refresh-global-map"
        return {
            "providerId": "graft",
            "status": "fresh" if topic_fresh and global_fresh else "stale",
            "conversationId": conversation,
            "topic": topic,
            "globalMap": {
                "root": str(root / _GRAPH_DIR),
                "deep": False,
                "status": "fresh" if global_fresh else "stale",
                "freshness": global_status.get("freshness"),
            },
            "updated": False,
            "nextAction": next_action,
        }

    def check_global_freshness(self, project_root: str) -> dict[str, Any]:
        """Check only the global non-Deep Code Map.

        Normal Graft routing must not inspect a Deep Topic.  Topic freshness
        is an explicit, user-requested operation and is intentionally kept out
        of this automatic maintenance path.
        """

        root = _safe_root(project_root)
        provider_report = self._provider_preflight()
        global_status = self._status(root, provider_report)
        fresh = global_status.get("freshness") == "fresh"
        return {
            "providerId": "graft",
            "status": "fresh" if fresh else "stale",
            "globalMap": {
                "root": str(root / _GRAPH_DIR),
                "deep": False,
                "status": "fresh" if fresh else "stale",
                "freshness": global_status.get("freshness"),
            },
            "updated": False,
            "nextAction": "none" if fresh else "refresh-global-map",
        }


    def refresh_global_map(self, project_root: str) -> dict[str, Any]:
        """Build and verify only the global non-Deep structural map."""

        root = _safe_root(project_root)
        provider_report = self._provider_preflight()
        _ensure_ignore(root)
        try:
            build = self._provider.build_structural(str(root))
            verified = self._status(root, provider_report)
        except Exception as error:
            reason = getattr(error, "reason", "graft-update-failed")
            raise GraftProjectError(reason, **graft_failure_details(error)) from None
        if verified.get("freshness") != "fresh":
            raise GraftProjectError("graft-global-map-not-fresh")
        return {
            "root": str(root / _GRAPH_DIR),
            "deep": False,
            "status": "fresh",
            "freshness": "fresh",
            "build": dict(build) if isinstance(build, Mapping) else build,
        }

    def complete_pending(self, project_root: str) -> dict[str, Any]:
        """Acknowledge one successfully completed deferred write event."""

        root = _safe_root(project_root)
        _graph, state = _binding(root)
        with _WorkerLock(state):
            queue_path = state / "queue.json"
            queue = _read_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
            paths = queue.get("changedPaths", [])
            if not isinstance(paths, list) or any(not isinstance(item, str) for item in paths):
                raise GraftProjectError("graft-worker-state-invalid")
            _write_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
            _write_json(state / "state.json", {
                "schemaVersion": 1, "status": "succeeded", "retryable": False,
                "lastChangedPaths": sorted(set(paths)),
            })
        return {"pending": False, "changedPathCount": len(paths)}

    def query(
        self, project_root: str, query: str, *, query_kind: str,
        context_dir: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate the project boundary before a read-only Provider query."""

        root = _safe_root(project_root)
        binding = None
        if conversation_id is not None:
            choice = resolve_conversation_choice(root, conversation_id)
            if choice is not None and choice["decision"] == "disabled":
                raise GraftProjectError("graft-disabled-for-conversation")
            context, binding = _conversation_topic_context(
                root, conversation_id, context_dir,
            )
        else:
            context = _topic_context(root, context_dir)
        if context_dir is None and conversation_id is None:
            _binding(root)
        topic_status: dict[str, Any] = {}
        if binding is not None:
            topic_status = _topic_scope_status(
                root, context, binding["topicId"],
            )
        try:
            self._provider_preflight()
            if context is None:
                result = self._provider.query(
                    str(root), query, query_kind=query_kind,
                )
            else:
                result = self._provider.query(
                    str(root), query, query_kind=query_kind,
                    context_dir=str(context),
                )
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            raise GraftProjectError(reason, **graft_failure_details(error)) from None
        if not isinstance(result, Mapping):
            raise GraftProjectError("graft-query-invalid")
        enriched = dict(result)
        if topic_status and topic_status.get("topicFreshness") != "fresh":
            enriched["freshness"] = "stale"
        enriched.update(topic_status)
        if binding is not None:
            enriched["conversationBinding"] = {
                "conversationId": conversation_id,
                "topicId": binding["topicId"],
                "bindingHash": binding["bindingHash"],
                "contextDir": str(context),
                "status": "loaded",
            }
        return enriched

    def preflight(self, project_root: str) -> dict[str, Any]:
        root = _safe_root(project_root)
        _binding(root)
        try:
            provider_report = self._provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-update-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "unavailable",
                "graphStatus": "unknown", "reason": reason,
                **graft_failure_details(error),
            }
        try:
            status = self._status(root, provider_report)
        except Exception as error:
            reason = getattr(error, "reason", "graft-update-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "verified",
                "graphStatus": "unknown", "reason": reason,
                **graft_failure_details(error),
            }
        if status["freshness"] != "missing":
            return {"status": "ready", **status}
        try:
            _ensure_ignore(root)
            build = self._provider.build_structural(str(root))
            final = self._status(root, provider_report)
        except Exception as error:
            reason = getattr(error, "reason", "graft-update-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "verified",
                "graphStatus": "unknown", "reason": reason,
                **graft_failure_details(error),
            }
        return {"status": "initialized", "build": dict(build), **final}

    def enqueue(self, project_root: str, changed_paths: Sequence[str]) -> dict[str, Any]:
        root = _safe_root(project_root)
        graph, state = _binding(root)
        paths = _relative_changed_paths(root, changed_paths)
        try:
            self._provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "unavailable", "graphStatus": "unknown",
                "pending": False, "reason": reason,
                **graft_failure_details(error),
            }
        _ensure_ignore(root)
        with _WorkerLock(state):
            queue_path = state / "queue.json"
            queue = _read_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
            old = queue.get("changedPaths", [])
            if not isinstance(old, list) or any(not isinstance(item, str) for item in old):
                raise GraftProjectError("graft-worker-state-invalid")
            merged = sorted(set(old).union(paths))
            if len(merged) > _MAX_CHANGED_PATHS:
                raise GraftProjectError("graft-event-too-large")
            _write_json(queue_path, {"schemaVersion": 1, "changedPaths": merged})
        return {
            "providerId": "graft", "status": "queued" if not old else "coalesced",
            "pending": True, "changedPathCount": len(merged),
            "graphRoot": str(graph),
        }

    def run_once(
        self, project_root: str, *, conversation_id: str,
        include_topic: bool = True,
    ) -> dict[str, Any]:
        root = _safe_root(project_root)
        conversation_id = _conversation_id(conversation_id)
        graph, state = _binding(root)
        try:
            provider_report = self._provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "unavailable", "graphStatus": "unknown",
                "pending": True, "retryable": True, "reason": reason,
                **graft_failure_details(error),
                "conversationId": conversation_id,
            }
        with _WorkerLock(state):
            queue_path = state / "queue.json"
            queue = _read_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
            paths = queue.get("changedPaths", [])
            if not isinstance(paths, list) or any(not isinstance(item, str) for item in paths):
                raise GraftProjectError("graft-worker-state-invalid")
            if not paths:
                return {
                    "providerId": "graft", "status": "idle", "pending": False,
                    "conversationId": conversation_id,
                    "globalMapUpdated": False, "nextAction": "none",
                }
            _write_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
            active = list(paths)
        if include_topic:
            topic_refresh = _topic_refresh_status(root, conversation_id)
            if topic_refresh is None:
                raise GraftProjectError("graft-topic-refresh-result-missing")
        else:
            topic_refresh = {
                "status": "skipped",
                "action": "none",
                "reason": "deep-not-requested",
                "conversationId": conversation_id,
            }
        if topic_refresh["action"] == "run-graft-deep":
            # Topic freshness is the task-critical path. Keep the write event
            # durable and let ProviderManager refresh the Topic before the
            # independent global map, which may scan a large repository.
            with _WorkerLock(state):
                queue_path = state / "queue.json"
                queue = _read_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
                pending = queue.get("changedPaths", [])
                if not isinstance(pending, list) or any(
                    not isinstance(item, str) for item in pending
                ):
                    raise GraftProjectError("graft-worker-state-invalid")
                merged = sorted(set(active).union(pending))
                if len(merged) > _MAX_CHANGED_PATHS:
                    raise GraftProjectError("graft-event-too-large")
                _write_json(queue_path, {"schemaVersion": 1, "changedPaths": merged})
                _write_json(state / "state.json", {
                    "schemaVersion": 1, "status": "deferred", "retryable": True,
                    "lastChangedPaths": active, "reason": "topic-refresh-priority",
                })
            return {
                "providerId": "graft", "status": "partial", "retryable": True,
                "pending": True, "changedPathCount": len(active),
                "graphRoot": str(graph), "globalMapUpdated": False,
                "globalMap": {
                    "root": str(graph), "deep": False, "status": "deferred",
                    "reason": "topic-refresh-priority",
                },
                "conversationId": conversation_id,
                "topicRefresh": topic_refresh,
                "nextAction": "run-graft-deep",
                "reason": "global-map-deferred-for-topic-refresh",
            }
        if topic_refresh["action"] == "stop":
            with _WorkerLock(state):
                queue_path = state / "queue.json"
                queue = _read_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
                pending = queue.get("changedPaths", [])
                if not isinstance(pending, list) or any(
                    not isinstance(item, str) for item in pending
                ):
                    raise GraftProjectError("graft-worker-state-invalid")
                merged = sorted(set(active).union(pending))
                if len(merged) > _MAX_CHANGED_PATHS:
                    raise GraftProjectError("graft-event-too-large")
                _write_json(queue_path, {"schemaVersion": 1, "changedPaths": merged})
                _write_json(state / "state.json", {
                    "schemaVersion": 1, "status": "blocked", "retryable": False,
                    "lastChangedPaths": active, "reason": topic_refresh.get("reason"),
                })
            return {
                "providerId": "graft", "status": "unverified", "retryable": False,
                "pending": True, "changedPathCount": len(active),
                "graphRoot": str(graph), "globalMapUpdated": False,
                "globalMap": {"root": str(graph), "deep": False, "status": "deferred"},
                "conversationId": conversation_id,
                "topicRefresh": topic_refresh, "nextAction": "stop",
                "reason": topic_refresh.get("reason", "graft-topic-refresh-unverified"),
            }
        global_failure: str | None = None
        global_failure_details: dict[str, Any] = {}
        build: Mapping[str, Any] | None = None
        global_freshness: str | None = None
        try:
            # The global map is a separate, non-Deep acceleration layer.  Its
            # failure must not prevent the conversation-bound Topic from
            # being checked and refreshed below.
            build = self._provider.build_structural(str(root))
            verified = self._status(root, provider_report)
            global_freshness = verified.get("freshness")
            if global_freshness != "fresh":
                raise GraftProjectError("graft-global-map-not-fresh")
        except Exception as error:
            reason = getattr(error, "reason", "graft-update-failed")
            global_failure = reason
            global_failure_details = graft_failure_details(error)
            with _WorkerLock(state):
                queue_path = state / "queue.json"
                queue = _read_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
                pending = queue.get("changedPaths", [])
                if not isinstance(pending, list):
                    raise GraftProjectError("graft-worker-state-invalid") from None
                merged = sorted(set(active).union(item for item in pending if isinstance(item, str)))
                _write_json(queue_path, {"schemaVersion": 1, "changedPaths": merged})
                _write_json(state / "state.json", {
                    "schemaVersion": 1, "status": "failed", "retryable": True,
                    "lastChangedPaths": active, "reason": reason,
                })
        if global_failure is None:
            with _WorkerLock(state):
                queue = _read_json(state / "queue.json", {"schemaVersion": 1, "changedPaths": []})
                pending = queue.get("changedPaths", [])
                if not isinstance(pending, list):
                    raise GraftProjectError("graft-worker-state-invalid")
                _write_json(state / "state.json", {
                    "schemaVersion": 1, "status": "succeeded", "retryable": False,
                    "lastChangedPaths": active,
                })
        else:
            with _WorkerLock(state):
                queue = _read_json(state / "queue.json", {"schemaVersion": 1, "changedPaths": []})
                pending = queue.get("changedPaths", [])
                if not isinstance(pending, list):
                    raise GraftProjectError("graft-worker-state-invalid")
        result = {
            "providerId": "graft",
            "status": "partial" if global_failure is not None else "succeeded",
            "retryable": global_failure is not None,
            "pending": bool(pending), "changedPathCount": len(active),
            "graphRoot": str(graph),
            "globalMapUpdated": global_failure is None,
            "globalMap": {
                "root": str(graph), "deep": False,
                "status": "failed" if global_failure is not None else "succeeded",
                **({"freshness": global_freshness} if global_freshness is not None else {}),
                **({"reason": global_failure} if global_failure is not None else {}),
            },
            "conversationId": conversation_id,
        }
        if build is not None:
            result["build"] = dict(build) if isinstance(build, Mapping) else build
        if global_failure is not None:
            result["reason"] = global_failure
            result.update(global_failure_details)
        if include_topic:
            topic_refresh = _topic_refresh_status(root, conversation_id)
            if topic_refresh is None:
                raise GraftProjectError("graft-topic-refresh-result-missing")
        else:
            topic_refresh = {
                "status": "skipped",
                "action": "none",
                "reason": "deep-not-requested",
                "conversationId": conversation_id,
            }
        result["topicRefresh"] = topic_refresh
        result["nextAction"] = (
            topic_refresh["action"]
            if topic_refresh["action"] != "none"
            else "retry-global-map" if global_failure is not None else "none"
        )
        return result


def validate_project_root(project_root: object) -> Path:
    """Validate the same Git/reparse/cache boundary used by the lifecycle."""

    root = _safe_root(project_root)
    _binding(root)
    return root
