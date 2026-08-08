"""Canonical capability-evidence snapshots for stateless plan identity."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from selfworkflow.pipeline import canonical_hash


class CapabilitySnapshotError(ValueError):
    pass


def _time(value: object) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise CapabilitySnapshotError("capability-snapshot-invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise CapabilitySnapshotError("capability-snapshot-invalid") from None


def normalize_capability_snapshot(
    value: Mapping[str, object], *, trusted_now: datetime | None = None
) -> tuple[dict[str, object], str, dict[str, str], bool]:
    if type(value) is not dict or set(value) != {"schemaVersion", "capturedAt", "evidence"}:
        raise CapabilitySnapshotError("capability-snapshot-invalid")
    if value["schemaVersion"] != 1 or type(value["evidence"]) is not list or len(value["evidence"]) > 256:
        raise CapabilitySnapshotError("capability-snapshot-invalid")
    captured = _time(value["capturedAt"])
    now = trusted_now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise CapabilitySnapshotError("capability-snapshot-invalid")
    snapshot_from_future = captured > now
    normalized: list[dict[str, object]] = []
    states: dict[str, str] = {}
    stale = snapshot_from_future
    for item in value["evidence"]:
        required = {"name", "provider", "subject", "state", "observedAt", "validUntil", "evidenceRef", "evidenceHash"}
        if type(item) is not dict or set(item) != required:
            raise CapabilitySnapshotError("capability-snapshot-invalid")
        name = item["name"]
        if type(name) is not str or not name or name in states or item["state"] not in {"supported", "unsupported", "unverified"}:
            raise CapabilitySnapshotError("capability-snapshot-invalid")
        observed, valid_until = _time(item["observedAt"]), _time(item["validUntil"])
        state = item["state"]
        if snapshot_from_future or not observed <= captured < valid_until or not observed <= now < valid_until:
            state = "unverified"
            stale = True
        subject = item["subject"]
        if type(subject) is not dict or set(subject) != {"kind", "id", "version", "build", "sourceLock"}:
            raise CapabilitySnapshotError("capability-snapshot-invalid")
        if any(type(subject[key]) is not str or not subject[key] for key in ("kind", "id")):
            raise CapabilitySnapshotError("capability-snapshot-invalid")
        normalized_item = {
            "name": name,
            "provider": item["provider"],
            "subject": dict(subject),
            "state": state,
            "observedAt": item["observedAt"],
            "validUntil": item["validUntil"],
            "evidenceRef": item["evidenceRef"],
            "evidenceHash": item["evidenceHash"],
        }
        normalized.append(normalized_item)
        states[name] = state
    normalized.sort(key=lambda item: item["name"])
    snapshot = {"schemaVersion": 1, "capturedAt": value["capturedAt"], "evidence": normalized}
    return snapshot, canonical_hash(snapshot), dict(sorted(states.items())), stale
