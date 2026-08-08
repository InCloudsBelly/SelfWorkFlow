"""Test-only Provider and EffectPort; never imported by production runner defaults."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from selfworkflow.v3.effects import EffectMutation, EffectNotStarted, EffectResult, LiveLeaseGuard
from selfworkflow.v3.hashing import content_hash


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
        started_at: datetime | None = None, completed_at: datetime | None = None,
        not_started: bool = False,
        during_effect: Callable[[], None] | None = None,
        invoke_live_guard: bool = True,
    ):
        self.exit_code = exit_code
        self.touched_paths = touched_paths
        self.mutations = mutations
        self.mutation_evidence = mutation_evidence
        self.observation_complete = observation_complete
        self.stdout = stdout
        self.stderr = stderr
        self.started_at = started_at
        self.completed_at = completed_at
        self.not_started = not_started
        self.during_effect = during_effect
        self.invoke_live_guard = invoke_live_guard
        self.calls: list[EffectCall] = []

    def capability_attestation(self):
        body = {
            "schemaVersion": 3,
            "backendClass": "fake-test",
            "sealedCommand": True,
            "liveLeaseGuard": True,
            "evidenceClass": "fake-only",
        }
        body["attestationHash"] = content_hash(body)
        return body

    def run(
        self, command_spec: Mapping[str, object], *, timeout_seconds: int,
        output_limit_bytes: int, invocation_time: datetime,
        live_lease_guard: LiveLeaseGuard | None,
    ) -> EffectResult:
        if self.not_started:
            raise EffectNotStarted("effect-not-started")
        start = self.started_at or invocation_time
        completed = self.completed_at or invocation_time
        if self.during_effect is not None:
            self.during_effect()
        if live_lease_guard is not None and self.invoke_live_guard:
            live_lease_guard.check()
        result = EffectResult(
            self.exit_code, self.stdout[:output_limit_bytes], self.stderr[:output_limit_bytes],
            start, completed, self.touched_paths, self.mutations,
            self.mutation_evidence, self.observation_complete,
        )
        self.calls.append(EffectCall(
            tuple(command_spec["argv"]), dict(command_spec["env"]),
            str(command_spec["cwd"]), self.touched_paths, result.exit_code,
            result.stdout_summary, result.stderr_summary, start, completed,
        ))
        return result


class FakeProvider:
    operation_ids = ("inspect", "initialize-index", "sync-incremental", "rebuild-index", "upgrade-managed-adapter", "repair-managed-state")
