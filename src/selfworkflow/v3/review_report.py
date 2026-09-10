"""Bounded, non-reasoning Review report returned by an ephemeral reviewer."""

from __future__ import annotations

from selfworkflow.v3.hashing import hash_bytes


class ReviewReportError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


MAX_REVIEW_REPORT_BYTES = 64 * 1024


def normalize_review_report(value: object) -> tuple[str, str]:
    """Validate a Markdown summary and return it with its content hash.

    The report is a bounded delivery artifact, not execution evidence and not a
    container for private reviewer reasoning.
    """

    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ReviewReportError("review-report-invalid")
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_REVIEW_REPORT_BYTES:
        raise ReviewReportError("review-report-too-large")
    return value, hash_bytes(encoded)
