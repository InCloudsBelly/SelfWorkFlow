"""Fail-closed evidence checks for the explicit implement-spec adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import re
from typing import Any


_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REQUIRED = {
    "specHash", "tickets", "ticketDagHash", "planReviewHash",
    "implementationConfirmationHash", "independentAgentsHash",
    "independentReviewHash", "gitPermissionsHash", "planReviewStatus",
    "implementationConfirmationStatus", "independentAgentsStatus",
    "independentReviewStatus", "gitPermissionsStatus",
}


class ImplementSpecEvidenceError(ValueError):
    """Raised when the explicit implement-spec preconditions are incomplete."""


def ticket_dag_hash(tickets: Sequence[Mapping[str, Any]]) -> str:
    """Return the canonical hash that binds the ticket graph to the request."""

    material = [
        {
            "id": ticket["id"],
            "dependencies": sorted(ticket["dependencies"]),
            "acceptanceHash": ticket["acceptanceHash"],
        }
        for ticket in sorted(tickets, key=lambda item: item["id"])
    ]
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_implement_spec_evidence(value: object) -> None:
    """Validate the evidence required before selecting implement-spec."""

    if not isinstance(value, Mapping) or set(value) != _REQUIRED:
        raise ImplementSpecEvidenceError("implement-spec-evidence-shape-invalid")
    for field in (
        "specHash", "ticketDagHash", "planReviewHash",
        "implementationConfirmationHash", "independentAgentsHash",
        "independentReviewHash", "gitPermissionsHash",
    ):
        if not isinstance(value[field], str) or _HASH.fullmatch(value[field]) is None:
            raise ImplementSpecEvidenceError("implement-spec-evidence-hash-invalid")
    statuses = {
        "planReviewStatus": "passed",
        "implementationConfirmationStatus": "confirmed",
        "independentAgentsStatus": "supported",
        "independentReviewStatus": "supported",
        "gitPermissionsStatus": "confirmed",
    }
    if any(value[field] != expected for field, expected in statuses.items()):
        raise ImplementSpecEvidenceError("implement-spec-evidence-status-invalid")
    tickets = value["tickets"]
    if (
        not isinstance(tickets, Sequence) or isinstance(tickets, (str, bytes))
        or len(tickets) < 2 or len(tickets) > 256
    ):
        raise ImplementSpecEvidenceError("implement-spec-ticket-dag-invalid")
    ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for ticket in tickets:
        if not isinstance(ticket, Mapping) or set(ticket) != {
            "id", "dependencies", "acceptanceHash",
        }:
            raise ImplementSpecEvidenceError("implement-spec-ticket-invalid")
        ticket_id = ticket["id"]
        dependencies = ticket["dependencies"]
        dependency_values_valid = (
            isinstance(dependencies, Sequence)
            and not isinstance(dependencies, (str, bytes))
            and all(isinstance(item, str) for item in dependencies)
        )
        if (
            not isinstance(ticket_id, str) or _ID.fullmatch(ticket_id) is None
            or ticket_id in ids
            or not dependency_values_valid
            or len(dependencies) != len(set(dependencies))
            or any(
                not isinstance(item, str) or _ID.fullmatch(item) is None
                or item == ticket_id
                for item in dependencies
            )
            or not isinstance(ticket["acceptanceHash"], str)
            or _HASH.fullmatch(ticket["acceptanceHash"]) is None
        ):
            raise ImplementSpecEvidenceError("implement-spec-ticket-invalid")
        ids.add(ticket_id)
        normalized.append({
            "id": ticket_id,
            "dependencies": sorted(dependencies),
            "acceptanceHash": ticket["acceptanceHash"],
        })
    if any(
        dependency not in ids
        for ticket in normalized
        for dependency in ticket["dependencies"]
    ):
        raise ImplementSpecEvidenceError("implement-spec-ticket-dependency-invalid")
    if value["ticketDagHash"] != ticket_dag_hash(normalized):
        raise ImplementSpecEvidenceError("implement-spec-ticket-dag-hash-invalid")

    dependencies = {
        ticket["id"]: set(ticket["dependencies"])
        for ticket in normalized
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(ticket_id: str) -> None:
        if ticket_id in visiting:
            raise ImplementSpecEvidenceError("implement-spec-ticket-cycle")
        if ticket_id in visited:
            return
        visiting.add(ticket_id)
        for dependency in dependencies[ticket_id]:
            visit(dependency)
        visiting.remove(ticket_id)
        visited.add(ticket_id)

    for ticket_id in sorted(dependencies):
        visit(ticket_id)
