"""Small stateless facade for V2 modular workflow resolution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from selfworkflow.plan_graph import build_plan_graph
from selfworkflow.request_v2 import RequestV2Error, normalize_request


class ResolveError(ValueError):
    def __init__(self, code: str = "resolve-input-invalid") -> None:
        self.code = code
        super().__init__("resolve-failed")


def resolve_task(catalog_content: bytes | str | Mapping[str, object], request: Mapping[str, object]) -> dict[str, object]:
    """Return an immutable PlanGraph; never execute a module or mutate state."""

    root = Path(__file__).resolve().parents[2]
    try:
        normalized, request_hash, diagnostics, states, snapshot_hash, stale = normalize_request(request, root)
        graph, reason_codes = build_plan_graph(catalog_content, normalized, request_hash, snapshot_hash, states, root)
        reasons = set(reason_codes)
        if stale:
            reasons.add("source-evidence-stale")
        return {
            "schemaVersion": 2,
            "status": "paused" if reasons else "active",
            "reasonCodes": sorted(reasons),
            "diagnostics": list(diagnostics),
            "planGraph": graph,
        }
    except ResolveError:
        raise
    except RequestV2Error:
        raise ResolveError() from None
    except Exception:
        raise ResolveError() from None
