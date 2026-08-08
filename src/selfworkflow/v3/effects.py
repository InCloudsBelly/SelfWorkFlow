"""Effect ports. Production code receives effects; it never discovers or runs them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class EffectResult:
    exit_code: int
    stdout_summary: str
    stderr_summary: str
    started_at: datetime
    completed_at: datetime
    touched_paths: tuple[str, ...] = ()


class EffectPort(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: str,
        timeout_seconds: int,
        output_limit_bytes: int,
    ) -> EffectResult:
        """Run one already-rendered command through a host-owned effect boundary."""


class EffectError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
