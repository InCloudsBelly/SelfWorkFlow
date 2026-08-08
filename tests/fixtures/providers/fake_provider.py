"""Test-only Provider and EffectPort; never imported by production runner defaults."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from selfworkflow.v3.effects import EffectMutation, EffectResult


@dataclass(frozen=True)
class EffectCall:
    argv: tuple[str, ...]
    env: dict[str, str]
    cwd: str
    touched_paths: tuple[str, ...]
    exit_code: int
    stdout_summary: str
    stderr_summary: str
    started_at: datetime
    completed_at: datetime


class FakeEffectPort:
    is_test_port = True

    def __init__(
        self, *, exit_code: int = 0, touched_paths: tuple[str, ...] = (),
        mutations: tuple[EffectMutation, ...] = (),
        mutation_evidence: tuple[Mapping[str, object], ...] = (),
        observation_complete: bool = True,
        stdout: str = "ok", stderr: str = "",
    ):
        self.exit_code = exit_code
        self.touched_paths = touched_paths
        self.mutations = mutations
        self.mutation_evidence = mutation_evidence
        self.observation_complete = observation_complete
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[EffectCall] = []

    def run(self, argv: Sequence[str], *, env: Mapping[str, str], cwd: str, timeout_seconds: int, output_limit_bytes: int) -> EffectResult:
        start = datetime.now(timezone.utc)
        result = EffectResult(
            self.exit_code, self.stdout[:output_limit_bytes], self.stderr[:output_limit_bytes],
            start, start, self.touched_paths, self.mutations,
            self.mutation_evidence, self.observation_complete,
        )
        self.calls.append(EffectCall(tuple(argv), dict(env), cwd, self.touched_paths, result.exit_code, result.stdout_summary, result.stderr_summary, start, start))
        return result


class FakeProvider:
    operation_ids = ("inspect", "initialize-index", "sync-incremental", "rebuild-index", "upgrade-managed-adapter", "repair-managed-state")
