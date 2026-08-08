"""Shared validation errors and resource budgets for completion evidence."""

import hashlib
import json
import math
import re
from types import MappingProxyType
import unicodedata


ERROR_MESSAGES = MappingProxyType(
    {
        "protected-rules-invalid": "The protected-rule document is invalid.",
        "protected-rule-layer-invalid": "A lower-priority rule layer is invalid.",
        "protected-rule-layer-conflict": (
            "Lower-priority rule layers contain a conflicting rule identity."
        ),
        "protected-rule-override-denied": (
            "A lower-priority rule cannot replace a protected rule."
        ),
        "protected-rule-owner-authorization-required": (
            "A protected-rule change requires the complete breaking-change gate."
        ),
        "evidence-json-invalid": "The evidence JSON document is invalid.",
        "evidence-invalid": "The completion evidence structure is invalid.",
        "result-content-invalid": "The completion result content is invalid.",
        "evidence-time-invalid": "The completion evidence time is invalid.",
        "completion-policy-invalid": "The completion policy is invalid.",
        "artifact-store-invalid": "The evidence artifact store is invalid.",
        "manifest-invalid": "A completion file manifest is invalid.",
        "workflow-error-code-invalid": "The workflow error code is invalid.",
        "output-construction-denied": "Workflow output types use private factories.",
        "review-fallback-authorization-invalid": (
            "The trusted review fallback authorization is invalid."
        ),
        "trusted-artifact-store-required": (
            "A collector-sealed trusted artifact store is required."
        ),
        "trusted-artifact-store-construction-denied": (
            "Trusted artifact stores are created only by the collector."
        ),
        "artifact-collector-invalid": "The artifact collector input is invalid.",
        "evidence-budget-exceeded": (
            "The completion evidence exceeds a configured resource budget."
        ),
        "result-content-budget-exceeded": (
            "The normalized content exceeds a configured resource budget."
        ),
        "manifest-budget-exceeded": (
            "The file manifest exceeds a configured resource budget."
        ),
    }
)

MAX_JSON_CHARS = 1024 * 1024
MAX_JSON_UTF8_BYTES = 1024 * 1024
MAX_CANONICAL_STRING_BYTES = 1024 * 1024
MAX_CANONICAL_TOTAL_BYTES = 8 * 1024 * 1024
MAX_CANONICAL_NODES = 50_000
MAX_CAPABILITIES = 64
MAX_SELECTED_SKILLS = 256
MAX_ACCEPTANCE_CRITERIA = 512
MAX_VERIFICATIONS = 512
MAX_SKIPPED = 512
MAX_RESIDUAL_RISKS = 256
MAX_CHANGES = 10_000
MAX_MANIFEST_ENTRIES = 20_000
MAX_MANIFEST_FILE_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_RECORDS = 2048
MAX_TEXT_UTF8_BYTES = 64 * 1024
MAX_IDENTIFIER_UTF8_BYTES = 1024
MAX_REPOSITORY_PATH_CHARS = 1024
MAX_REPOSITORY_SEGMENT_CHARS = 255
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_WINDOWS_INVALID_CHARACTERS = frozenset('<>:"\\|?*')
_REVIEW_LEVEL_ORDER = MappingProxyType({"L0": 0, "L1": 1, "L2": 2, "L3": 3})


class _DuplicateJsonKeyError(ValueError):
    pass


class WorkflowEvidenceError(ValueError):
    """Stable workflow failure that does not include rejected input values."""

    def __init__(self, code: str):
        if type(code) is not str or code not in ERROR_MESSAGES:
            code = "workflow-error-code-invalid"
        self.code = code
        self.message = ERROR_MESSAGES[code]
        super().__init__(self.message)


def fail(code: str) -> None:
    raise WorkflowEvidenceError(code) from None


def require_collection_budget(value: tuple[object, ...], maximum: int) -> None:
    if len(value) > maximum:
        fail("evidence-budget-exceeded")


def bounded_text(
    value: object,
    *,
    maximum: int = MAX_TEXT_UTF8_BYTES,
    allow_empty: bool = False,
) -> bool:
    """Check exact text against a character-first and UTF-8 byte budget."""

    if (
        type(value) is not str
        or type(maximum) is not int
        or maximum < 0
        or (not allow_empty and not value)
        or len(value) > maximum
    ):
        return False
    try:
        return len(value.encode("utf-8")) <= maximum
    except Exception:
        return False


def review_level_at_least(actual: object, minimum: object) -> bool:
    """Compare exact standard review levels through one shared order."""

    return (
        type(actual) is str
        and type(minimum) is str
        and actual in _REVIEW_LEVEL_ORDER
        and minimum in _REVIEW_LEVEL_ORDER
        and _REVIEW_LEVEL_ORDER[actual] >= _REVIEW_LEVEL_ORDER[minimum]
    )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    del value
    raise ValueError


def freeze_json(
    value: object,
    *,
    depth: int = 0,
    state: list[int] | None = None,
) -> object:
    """Deep-freeze bounded parsed JSON without invoking custom containers."""

    if depth > 64:
        fail("evidence-json-invalid")
    counters = state if state is not None else [0, 0]
    counters[0] += 1
    if counters[0] > MAX_CANONICAL_NODES:
        fail("evidence-budget-exceeded")
    if type(value) is str:
        byte_limit = min(
            MAX_CANONICAL_STRING_BYTES,
            MAX_CANONICAL_TOTAL_BYTES - counters[1],
        )
        if len(value) > byte_limit:
            fail("evidence-budget-exceeded")
        size = len(value.encode("utf-8"))
        if size > byte_limit:
            fail("evidence-budget-exceeded")
        counters[1] += size
        return value
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            fail("evidence-json-invalid")
        return value
    if type(value) is list:
        if len(value) > MAX_CANONICAL_NODES - counters[0]:
            fail("evidence-budget-exceeded")
        return tuple(freeze_json(item, depth=depth + 1, state=counters) for item in value)
    if type(value) is dict:
        if len(value) > MAX_CANONICAL_NODES - counters[0]:
            fail("evidence-budget-exceeded")
        if any(type(key) is not str for key in value):
            fail("evidence-json-invalid")
        for key in value:
            byte_limit = min(
                MAX_CANONICAL_STRING_BYTES,
                MAX_CANONICAL_TOTAL_BYTES - counters[1],
            )
            if len(key) > byte_limit:
                fail("evidence-budget-exceeded")
            size = len(key.encode("utf-8"))
            if size > byte_limit:
                fail("evidence-budget-exceeded")
            counters[1] += size
        return MappingProxyType(
            {key: freeze_json(item, depth=depth + 1, state=counters) for key, item in value.items()}
        )
    fail("evidence-json-invalid")


def parse_evidence_json(document: object) -> MappingProxyType:
    """Parse duplicate-free finite JSON into a deeply immutable structure."""

    if type(document) is not str:
        fail("evidence-json-invalid")
    if len(document) > MAX_JSON_CHARS:
        fail("evidence-budget-exceeded")
    try:
        if len(document.encode("utf-8")) > MAX_JSON_UTF8_BYTES:
            fail("evidence-budget-exceeded")
        loaded = json.loads(
            document,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        frozen = freeze_json(loaded)
    except WorkflowEvidenceError:
        raise
    except Exception:
        fail("evidence-json-invalid")
    if type(frozen) is not _MAPPING_PROXY_TYPE:
        fail("evidence-json-invalid")
    return frozen


def _normalize_content(
    value: object,
    *,
    depth: int,
    counters: list[int],
    active: set[int],
) -> object:
    if depth > 64:
        fail("result-content-invalid")
    counters[0] += 1
    if counters[0] > MAX_CANONICAL_NODES:
        fail("result-content-budget-exceeded")
    if type(value) is str:
        byte_limit = min(
            MAX_CANONICAL_STRING_BYTES,
            MAX_CANONICAL_TOTAL_BYTES - counters[1],
        )
        if len(value) > byte_limit:
            fail("result-content-budget-exceeded")
        size = len(value.encode("utf-8"))
        if size > byte_limit:
            fail("result-content-budget-exceeded")
        counters[1] += size
        return value
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            fail("result-content-invalid")
        return int(value) if value.is_integer() else value
    if type(value) in (list, tuple):
        if len(value) > MAX_CANONICAL_NODES - counters[0]:
            fail("result-content-budget-exceeded")
        identity = id(value)
        if identity in active:
            fail("result-content-invalid")
        active.add(identity)
        try:
            return [
                _normalize_content(item, depth=depth + 1, counters=counters, active=active)
                for item in value
            ]
        finally:
            active.remove(identity)
    if type(value) in (dict, _MAPPING_PROXY_TYPE):
        if len(value) > MAX_CANONICAL_NODES - counters[0]:
            fail("result-content-budget-exceeded")
        identity = id(value)
        if identity in active:
            fail("result-content-invalid")
        active.add(identity)
        try:
            try:
                entries = tuple(value.items())
            except Exception:
                fail("result-content-invalid")
            if any(type(key) is not str for key, _ in entries):
                fail("result-content-invalid")
            for key, _ in entries:
                byte_limit = min(
                    MAX_CANONICAL_STRING_BYTES,
                    MAX_CANONICAL_TOTAL_BYTES - counters[1],
                )
                if len(key) > byte_limit:
                    fail("result-content-budget-exceeded")
                size = len(key.encode("utf-8"))
                if size > byte_limit:
                    fail("result-content-budget-exceeded")
                counters[1] += size
            return {
                key: _normalize_content(item, depth=depth + 1, counters=counters, active=active)
                for key, item in entries
            }
        finally:
            active.remove(identity)
    fail("result-content-invalid")


def canonical_content_hash(content: object) -> str:
    """Hash normalized finite JSON content with deterministic object ordering."""

    try:
        normalized = _normalize_content(content, depth=0, counters=[0, 0], active=set())
        serialized = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(serialized) > MAX_CANONICAL_TOTAL_BYTES:
            fail("result-content-budget-exceeded")
        payload = serialized.encode("utf-8")
        if len(payload) > MAX_CANONICAL_TOTAL_BYTES:
            fail("result-content-budget-exceeded")
    except WorkflowEvidenceError:
        raise
    except Exception:
        fail("result-content-invalid")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def repository_path_identity(value: object) -> str:
    """Validate a canonical Windows-safe repo-relative path and return its identity."""

    if (
        type(value) is not str
        or not value
        or value == "."
        or len(value) > MAX_REPOSITORY_PATH_CHARS
        or unicodedata.normalize("NFC", value) != value
        or value.startswith("/")
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value) is not None
    ):
        fail("manifest-invalid")
    segments = value.split("/")
    if any(
        not segment
        or segment in {".", ".."}
        or len(segment) > MAX_REPOSITORY_SEGMENT_CHARS
        or segment.endswith((".", " "))
        or any(ord(character) < 32 or ord(character) == 127 for character in segment)
        or any(character in _WINDOWS_INVALID_CHARACTERS for character in segment)
        or segment.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        for segment in segments
    ):
        fail("manifest-invalid")
    return value.casefold()


def manifest_hashes(value: object) -> tuple[dict[str, str], dict[str, str]]:
    """Hash a bounded closed manifest and expose its Windows path identities."""

    if type(value) not in (dict, _MAPPING_PROXY_TYPE):
        fail("manifest-invalid")
    if len(value) > MAX_MANIFEST_ENTRIES:
        fail("manifest-budget-exceeded")
    try:
        entries = tuple(value.items())
    except Exception:
        fail("manifest-invalid")
    result: dict[str, str] = {}
    identities: dict[str, str] = {}
    total_bytes = 0
    total_characters = 0
    for path, content in entries:
        identity = repository_path_identity(path)
        if type(content) is not str or path in result or identity in identities:
            fail("manifest-invalid")
        total_characters += len(content)
        if (
            len(content) > MAX_MANIFEST_FILE_BYTES
            or total_characters > MAX_MANIFEST_TOTAL_BYTES
        ):
            fail("manifest-budget-exceeded")
        try:
            encoded = content.encode("utf-8")
        except Exception:
            fail("manifest-invalid")
        total_bytes += len(encoded)
        if (
            len(encoded) > MAX_MANIFEST_FILE_BYTES
            or total_bytes > MAX_MANIFEST_TOTAL_BYTES
        ):
            fail("manifest-budget-exceeded")
        result[path] = "sha256:" + hashlib.sha256(encoded).hexdigest()
        identities[identity] = path
    return dict(sorted(result.items())), identities
