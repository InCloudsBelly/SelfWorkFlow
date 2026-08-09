"""Strict loader for the authoritative post-Grill review policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.hashing import content_hash


class ReviewPolicyError(ValueError):
    def __init__(self, reason: str = "post-grill-review-policy-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


_POLICY_TOKEN = object()


class ReviewPolicyArtifact:
    """Immutable policy value issued only by the strict repository loader."""

    __slots__ = ("_document", "_policy_hash", "_token")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ReviewPolicyArtifact is issued by load_post_grill_review_policy")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("ReviewPolicyArtifact is immutable")

    @property
    def policy_hash(self) -> str:
        return self._policy_hash

    @property
    def document(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._document))

    def _is_valid(self) -> bool:
        return (
            self._token is _POLICY_TOKEN
            and self._policy_hash == content_hash(self._document)
        )


def load_post_grill_review_policy(source: object = None) -> ReviewPolicyArtifact:
    path = (
        Path(__file__).resolve().parents[3] / "workflow/v3/post-grill-review.yaml"
        if source is None else Path(source)
    )
    try:
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            raise ReviewPolicyError()
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if type(raw) is not dict:
            raise ReviewPolicyError()
        document = load_contract(
            "post-grill-review-policy.schema.json",
            json.dumps(raw, ensure_ascii=False, allow_nan=False),
        )
    except ReviewPolicyError:
        raise
    except (ContractError, OSError, TypeError, ValueError, yaml.YAMLError):
        raise ReviewPolicyError() from None
    artifact = object.__new__(ReviewPolicyArtifact)
    object.__setattr__(artifact, "_document", document)
    object.__setattr__(artifact, "_policy_hash", content_hash(document))
    object.__setattr__(artifact, "_token", _POLICY_TOKEN)
    return artifact
