"""Shared Fake-only host authorities for Provider security tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from threading import Lock
from typing import Any, Mapping

from selfworkflow.v3.approvals import (
    AuthorizationResolution,
    build_machine_authorization,
    issue_approval,
)
from selfworkflow.v3.command_registry import (
    build_adapter_command_template,
    build_trusted_command_registry,
)
from selfworkflow.v3.hashing import clone, content_hash
from selfworkflow.v3.plans import build_operation_plan, build_query_plan
from selfworkflow.v3.project_lease import ProviderLeaseManager
from selfworkflow.v3.receipts import build_mutation_evidence


NOW = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
H = content_hash({"fixture": "provider-security"})


class FakeClock:
    def __init__(self, now: datetime = NOW):
        self.value = now

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class FakeProcessIdentity:
    def __init__(self):
        self.pid = 100
        self.start = "process-start-a"
        self.live = True

    def current(self):
        return self.pid, self.start

    def is_live(self, pid, start):
        return self.live and pid == self.pid and start == self.start


class FakeBootIdentity:
    def __init__(self):
        self.value = "boot-a"

    def current(self):
        return self.value


class FakeHostAtomicLeasePort:
    """Mechanically shared CAS Fake; never valid in production mode."""

    def __init__(self):
        self.values: dict[str, dict[str, Any]] = {}
        self.lock = Lock()

    def capability_attestation(self):
        body = {
            "schemaVersion": 3,
            "capability": "cross-process-atomic-cas",
            "backendClass": "fake-test",
            "issuerId": "fake-host",
        }
        body["attestationHash"] = content_hash(body)
        return body

    def read(self, key):
        with self.lock:
            value = self.values.get(key)
            return None if value is None else clone(value)

    def compare_and_create(self, key, document):
        with self.lock:
            if key in self.values:
                return False
            self.values[key] = clone(dict(document))
            return True

    def compare_and_replace(self, key, expected_hash, document):
        with self.lock:
            current = self.values.get(key)
            if current is None or current.get("leaseHash") != expected_hash:
                return False
            self.values[key] = clone(dict(document))
            return True

    def compare_and_delete(self, key, expected_hash):
        with self.lock:
            current = self.values.get(key)
            if current is None or current.get("leaseHash") != expected_hash:
                return False
            del self.values[key]
            return True

    def replace_with_takeover(self, key: str, document: Mapping[str, Any]) -> None:
        with self.lock:
            self.values[key] = clone(dict(document))


class FakeReplayStore:
    def __init__(self):
        self.states: dict[str, str] = {}
        self.lock = Lock()

    def reserve(self, key):
        with self.lock:
            if key in self.states:
                return False
            self.states[key] = "reserved"
            return True

    def commit(self, key, terminal_state):
        if terminal_state not in {"terminal-succeeded", "terminal-failed"}:
            return False
        with self.lock:
            if self.states.get(key) != "reserved":
                return False
            self.states[key] = terminal_state
            return True

    def abort(self, key):
        with self.lock:
            if self.states.get(key) != "reserved":
                return False
            del self.states[key]
            return True


class FakeAuthorizationResolver:
    def __init__(self, *documents):
        self.documents = {item["authorizationHash"]: clone(item) for item in documents}
        self.statuses = {key: "active" for key in self.documents}
        self.trusted = True

    def resolve(self, authorization_hash):
        document = self.documents.get(authorization_hash)
        if document is None:
            return None
        return AuthorizationResolution(
            clone(document), self.statuses[authorization_hash], self.trusted, "fake-test",
        )

    def revoke(self, authorization_hash):
        self.statuses[authorization_hash] = "revoked"


def managed_target(action: str, target_id: str = "index") -> dict[str, Any]:
    return {
        "targetKind": "managed-state-root",
        "targetId": target_id,
        "allowedActions": [action],
        "evidenceRequired": True,
    }


def command_registry(
    *, operation_id: str, side_effect_class: str,
    provider_id: str = "fake.provider", binding_hash: str = H,
    adapter_hash: str = H, trust_source: str = "test-fixture",
    env_allowlist=(), executable: str | None = None,
):
    executable = executable or str(Path(sys.executable).resolve())
    template = build_adapter_command_template(
        template_id=f"{operation_id}.template",
        provider_id=provider_id,
        binding_snapshot_hash=binding_hash,
        adapter_hash=adapter_hash,
        operation_id=operation_id,
        side_effect_class=side_effect_class,
        executable=executable,
        argv_template=(
            executable, "-m", "fake.provider", "--operation", "{operationId}",
            "--project-root", "{projectRoot}",
        ),
        env_allowlist=env_allowlist,
    )
    return build_trusted_command_registry(
        (template,), issuer_id="fake-command-authority", trust_source=trust_source,
    )


def operation_bundle(
    project_root: str, *, operation_id: str = "sync-incremental",
    action: str = "sync", nonce: str = "nonce-a", attempt: str = "attempt-a",
    ownership_domain: str = "selfworkflow-managed",
):
    side_effect = "none" if operation_id == "inspect" else "local-write"
    registry = command_registry(operation_id=operation_id, side_effect_class=side_effect)
    targets = () if side_effect == "none" else (managed_target(action),)
    machine = None
    resolver = FakeAuthorizationResolver()
    if side_effect != "none":
        machine = build_machine_authorization(
            provider_id="fake.provider", project_root=project_root,
            subject_kind="operation-plan", operation_id=operation_id,
            side_effect_class=side_effect, execution_nonce=nonce,
            attempt_ref=attempt, issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=10), nonce="machine-nonce",
        )
        resolver = FakeAuthorizationResolver(machine.document)
    kwargs = dict(
        provider_id="fake.provider", operation_id=operation_id,
        binding_snapshot_hash=H, adapter_hash=H, plan_hash=H,
        project_root=project_root, command_registry=registry,
        command_template_id=f"{operation_id}.template",
        mutation_targets=targets, execution_nonce=nonce, attempt_ref=attempt,
        ownership_domain=ownership_domain, machine_authorization=machine,
        now=NOW,
    )
    draft = build_operation_plan(**kwargs)
    approval = issue_approval(
        draft.subject, confirmation_source="user-confirmation", scope="exact-plan",
        target_hashes=[item["mutationTargetHash"] for item in draft.document["mutationTargets"]],
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10),
        nonce=nonce,
    )
    plan = build_operation_plan(**kwargs, approval=approval)
    return plan, approval, registry, machine, resolver


def query_bundle(
    project_root: str, *, side_effects: str = "none",
    operation_id: str = "inspect", action: str = "sync",
    nonce: str = "nonce-a", attempt: str = "attempt-a",
    ownership_domain: str | None = None,
):
    registry = command_registry(operation_id=operation_id, side_effect_class=side_effects)
    targets = () if side_effects == "none" else (managed_target(action),)
    ownership = ownership_domain or (
        "user-owned" if side_effects == "none" else "selfworkflow-managed"
    )
    machine = None
    resolver = FakeAuthorizationResolver()
    if side_effects != "none":
        machine = build_machine_authorization(
            provider_id="fake.provider", project_root=project_root,
            subject_kind="query-plan", operation_id=operation_id,
            side_effect_class=side_effects, execution_nonce=nonce,
            attempt_ref=attempt, issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=10), nonce="machine-nonce",
        )
        resolver = FakeAuthorizationResolver(machine.document)
    kwargs = dict(
        provider_id="fake.provider", operation_id=operation_id,
        binding_snapshot_hash=H, plan_hash=H, adapter_hash=H,
        typed_input_schema_ref="query.input", typed_input={"symbol": "A"},
        project_root=project_root, project_state_receipt_hash=H,
        workspace_fingerprint_hash=H, query_byte_budget=4096, call_limit=1,
        timeout_seconds=30, side_effects=side_effects,
        mutation_targets=targets, execution_nonce=nonce, attempt_ref=attempt,
        command_registry=registry, command_template_id=f"{operation_id}.template",
        ownership_domain=ownership, machine_authorization=machine, now=NOW,
    )
    draft = build_query_plan(**kwargs)
    approval = issue_approval(
        draft.subject, confirmation_source="user-confirmation", scope="exact-plan",
        target_hashes=[item["mutationTargetHash"] for item in draft.document["mutationTargets"]],
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10),
        nonce=nonce,
    )
    plan = build_query_plan(**kwargs, approval=approval)
    return plan, approval, registry, machine, resolver


def lease_manager(
    *, port: FakeHostAtomicLeasePort | None = None,
    clock: FakeClock | None = None,
    process: FakeProcessIdentity | None = None,
    boot: FakeBootIdentity | None = None,
):
    return ProviderLeaseManager(
        host_port=port or FakeHostAtomicLeasePort(),
        clock=clock or FakeClock(), process=process or FakeProcessIdentity(),
        boot=boot or FakeBootIdentity(), host_identity="host-a",
        user_session="session-a", heartbeat_seconds=30, ttl_seconds=600,
        test_mode=True,
    )


def evidence_for(plan, *, started_at: datetime = NOW, completed_at: datetime = NOW):
    target = plan.document["mutationTargets"][0]
    subject_kind = "operation-plan" if "operationPlanHash" in plan.document else "query-plan"
    plan_hash = plan.document["operationPlanHash" if subject_kind == "operation-plan" else "queryPlanHash"]
    state = {"identityHash": H, "revision": "r1"}
    return build_mutation_evidence(
        subject_kind=subject_kind,
        subject_plan_hash=plan_hash,
        execution_nonce=plan.document["executionNonce"],
        attempt_ref=plan.document["attemptRef"],
        provider_binding_hash=plan.document["bindingSnapshotHash"],
        project_root_hash=plan.document["canonicalProjectRootHash"],
        provider_id=plan.document["providerId"],
        started_at=started_at, completed_at=completed_at, observed_at=started_at,
        pre_state_identity=H, post_state_identity=H,
        mutation_target_hash=target["mutationTargetHash"],
        evidence_kind="managed-state-manifest", before=state, after=state,
        actual_targets=({
            "targetKind": "managed-state", "targetId": target["targetId"],
            "action": target["allowedActions"][0],
        },),
        declared_targets=plan.document["mutationTargets"],
    )
