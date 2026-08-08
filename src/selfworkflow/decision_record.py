"""Closed, redacted validation for bounded minor-decision records."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator


class DecisionRecordError(ValueError):
    """Stable public failure that never echoes untrusted record content."""

    def __init__(self) -> None:
        super().__init__("decision-record-invalid")


def validate_decision_record(value: Mapping[str, object]) -> dict[str, object]:
    """Return a detached valid record or reject its closed/semantic contract."""

    try:
        schema_path = Path(__file__).resolve().parents[2] / "schemas/decision-record.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if next(Draft202012Validator(schema).iter_errors(value), None) is not None:
            raise DecisionRecordError()
        result = deepcopy(dict(value))
        alternative_ids = [item["id"] for item in result["alternatives"]]
        if (
            len(alternative_ids) != len(set(alternative_ids))
            or result["recommendationId"] not in alternative_ids
            or result["selectedId"] not in alternative_ids
            or result["selectedId"] != result["recommendationId"]
        ):
            raise DecisionRecordError()
        return result
    except DecisionRecordError:
        raise
    except Exception:
        raise DecisionRecordError() from None
