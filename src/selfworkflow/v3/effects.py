"""Injected Provider effect boundary; no production process implementation lives here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class EffectMutation:
    kind: str
    target: str
    action: str


@dataclass(frozen=True)
class EffectResult:
    exit_code: int
    stdout_summary: str
    stderr_summary: str
    started_at: datetime
    completed_at: datetime
    touched_paths: tuple[str, ...] = ()
    mutations: tuple[EffectMutation, ...] = ()
    mutation_evidence: tuple[Mapping[str, Any], ...] = ()
    observation_complete: bool = True


class LiveLeaseGuard(Protocol):
    """Runner-owned callback that the host effect port must invoke during execution."""

    def check(self) -> str: ...


class EffectPort(Protocol):
    def run(
        self, command_spec: Mapping[str, Any], *, timeout_seconds: int,
        output_limit_bytes: int, invocation_time: datetime,
        live_lease_guard: LiveLeaseGuard | None,
    ) -> EffectResult: ...


class EffectError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class EffectNotStarted(EffectError):
    """The sole effect failure proving no external action began."""
