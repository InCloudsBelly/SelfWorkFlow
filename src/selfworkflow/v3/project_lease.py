"""Provider/project leases backed only by an injected host atomic CAS port.

This repository deliberately provides no production filesystem lease backend.
Production local-write execution must inject a host implementation that attests
cross-process atomic compare-and-swap semantics.  Tests use an in-memory Fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol

from selfworkflow.v3.approvals import AuthorizationResolution, AuthorizationResolver
from selfworkflow.v3.contracts import validate_provider_project_lease, validate_provider_stale_unlock_authorization
from selfworkflow.v3.hashing import clone, content_hash, project_root_hash


class LeaseError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class Clock(Protocol):
    def now(self) -> datetime: ...


class ProcessIdentity(Protocol):
    def current(self) -> tuple[int, str]: ...
    def is_live(self, pid: int, process_start_time: str) -> bool: ...


class BootIdentity(Protocol):
    def current(self) -> str: ...


class HostAtomicLeasePort(Protocol):
    """Trusted-host port; implementations must provide real cross-process CAS."""

    def capability_attestation(self) -> Mapping[str, Any]: ...
    def read(self, key: str) -> dict[str, Any] | None: ...
    def compare_and_create(self, key: str, document: Mapping[str, Any]) -> bool: ...
    def compare_and_replace(self, key: str, expected_hash: str, document: Mapping[str, Any]) -> bool: ...
    def compare_and_delete(self, key: str, expected_hash: str) -> bool: ...


# Backward-readable protocol name only.  It is not a concrete store.
LeaseStore = HostAtomicLeasePort


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _UnavailableProcessIdentity:
    def current(self) -> tuple[int, str]:
        raise LeaseError("lease-identity-unavailable")

    def is_live(self, pid: int, process_start_time: str) -> bool:
        raise LeaseError("lease-identity-unavailable")


class _UnavailableBootIdentity:
    def current(self) -> str:
        raise LeaseError("lease-identity-unavailable")


@dataclass(frozen=True)
class ProviderProjectLease:
    document: dict[str, Any]

    @property
    def lease_hash(self) -> str:
        return self.document["leaseHash"]


@dataclass(frozen=True)
class StaleUnlockAuthorization:
    document: dict[str, Any]


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise LeaseError("lease-time-not-utc")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise LeaseError("lease-time-invalid") from None
    if result.utcoffset() != timedelta(0):
        raise LeaseError("lease-time-not-utc")
    return result


def _hash_document(body: Mapping[str, Any], field: str) -> str:
    return content_hash({key: value for key, value in body.items() if key != field})


def _validate_capability(port: HostAtomicLeasePort, *, test_mode: bool) -> None:
    try:
        attestation = clone(dict(port.capability_attestation()))
    except Exception:
        raise LeaseError("host-atomic-lease-capability-required") from None
    required = {"schemaVersion", "capability", "backendClass", "issuerId", "attestationHash"}
    if set(attestation) != required or attestation.get("schemaVersion") != 3:
        raise LeaseError("host-atomic-lease-capability-invalid")
    if attestation.get("capability") != "cross-process-atomic-cas":
        raise LeaseError("host-atomic-lease-capability-invalid")
    if attestation.get("backendClass") not in {"external-host", "fake-test"}:
        raise LeaseError("host-atomic-lease-capability-invalid")
    expected_hash = _hash_document(attestation, "attestationHash")
    if attestation.get("attestationHash") != expected_hash:
        raise LeaseError("host-atomic-lease-capability-invalid")
    if attestation["backendClass"] == "fake-test" and not test_mode:
        raise LeaseError("test-lease-backend-rejected")


def build_stale_unlock_authorization(
    lease: ProviderProjectLease, *, issued_at: datetime, expires_at: datetime,
    nonce: str, confirmation_source: str = "user-confirmation",
    issuer_id: str = "host-local-authority", test_mode: bool = False,
) -> StaleUnlockAuthorization:
    if confirmation_source != "user-confirmation":
        raise LeaseError("stale-unlock-source-invalid")
    if issuer_id == "test-fixture" and not test_mode:
        raise LeaseError("test-authorization-rejected")
    document = lease.document
    body = {
        "schemaVersion": 3,
        "leaseHash": lease.lease_hash,
        "providerId": document["providerId"],
        "canonicalProjectRootHash": document["canonicalProjectRootHash"],
        "operationId": document["operationId"],
        "operationNonce": document["operationNonce"],
        "ownerNonce": document["ownerNonce"],
        "storeVersion": document["storeVersion"],
        "issuedAt": _utc(issued_at),
        "expiresAt": _utc(expires_at),
        "nonce": nonce,
        "issuerId": issuer_id,
        "confirmationSource": confirmation_source,
        "revocationState": "active",
    }
    body["authorizationHash"] = content_hash(body)
    validate_provider_stale_unlock_authorization(body, allow_test_issuer=test_mode)
    return StaleUnlockAuthorization(clone(body))


class ProviderLeaseManager:
    def __init__(
        self, *, host_port: HostAtomicLeasePort, clock: Clock | None = None,
        process: ProcessIdentity | None = None, boot: BootIdentity | None = None,
        host_identity: str | None = None, user_session: str | None = None,
        heartbeat_seconds: int = 30, ttl_seconds: int = 300,
        test_mode: bool = False,
    ) -> None:
        self.host_port = host_port
        self.clock = clock or SystemClock()
        self.process = process or _UnavailableProcessIdentity()
        self.boot = boot or _UnavailableBootIdentity()
        self.host_identity = host_identity
        self.user_session = user_session
        self.heartbeat_seconds = heartbeat_seconds
        self.ttl_seconds = ttl_seconds
        self.test_mode = test_mode
        _validate_capability(host_port, test_mode=test_mode)

    def assert_host_capability(self, *, test_mode: bool) -> None:
        _validate_capability(self.host_port, test_mode=test_mode)

    def _identity(self) -> tuple[int, str, str, str, str]:
        if not self.host_identity or not self.user_session:
            raise LeaseError("lease-identity-unavailable")
        try:
            pid, start = self.process.current()
            boot = self.boot.current()
        except LeaseError:
            raise
        except Exception:
            raise LeaseError("lease-identity-unavailable") from None
        if not isinstance(pid, int) or pid < 1 or not all(
            isinstance(value, str) and value
            for value in (start, boot, self.host_identity, self.user_session)
        ):
            raise LeaseError("lease-identity-unavailable")
        return pid, start, boot, self.host_identity, self.user_session

    @staticmethod
    def _key(provider_id: str, root_hash: str) -> str:
        return content_hash({"providerId": provider_id, "canonicalProjectRootHash": root_hash})

    @staticmethod
    def _stored(document: Mapping[str, Any]) -> ProviderProjectLease:
        material = dict(document)
        try:
            validate_provider_project_lease(material)
        except Exception:
            raise LeaseError("lease-store-record-invalid") from None
        return ProviderProjectLease(clone(material))

    def acquire(
        self, *, project_root: str, provider_id: str,
        operation_id: str, nonce: str,
    ) -> ProviderProjectLease:
        self.assert_host_capability(test_mode=self.test_mode)
        root_hash = project_root_hash(project_root)
        key = self._key(provider_id, root_hash)
        now = self.clock.now()
        existing = self.host_port.read(key)
        if existing is not None:
            lease = self._stored(existing)
            if self._is_stale(lease, now):
                raise LeaseError("stale-unlock-requires-authorization")
            raise LeaseError("lease-concurrent-owner")
        pid, start, boot, host, session = self._identity()
        body: dict[str, Any] = {
            "schemaVersion": 3,
            "canonicalProjectRootHash": root_hash,
            "providerId": provider_id,
            "operationId": operation_id,
            "operationNonce": nonce,
            "ownerNonce": content_hash({
                "provider": provider_id, "root": root_hash,
                "operationNonce": nonce, "issuedAt": _utc(now),
            })[7:39],
            "storeVersion": 1,
            "ownerPid": pid,
            "processStartTime": start,
            "userSession": session,
            "hostIdentity": host,
            "bootIdentity": boot,
            "heartbeatAt": _utc(now),
            "issuedAt": _utc(now),
            "expiresAt": _utc(now + timedelta(seconds=self.ttl_seconds)),
        }
        body["leaseHash"] = content_hash(body)
        validate_provider_project_lease(body)
        try:
            created = self.host_port.compare_and_create(key, body)
        except Exception:
            raise LeaseError("lease-host-port-failed") from None
        if not created:
            raise LeaseError("lease-concurrent-owner")
        return ProviderProjectLease(clone(body))

    def validate_live(
        self, lease: ProviderProjectLease, *, project_root_hash: str,
        provider_id: str, operation_id: str, nonce: str,
        at_time: datetime | None = None,
    ) -> None:
        self.assert_host_capability(test_mode=self.test_mode)
        validate_provider_project_lease(lease.document)
        if lease.document["leaseHash"] != _hash_document(lease.document, "leaseHash"):
            raise LeaseError("lease-hash-invalid")
        expected = {
            "canonicalProjectRootHash": project_root_hash,
            "providerId": provider_id,
            "operationId": operation_id,
            "operationNonce": nonce,
        }
        if any(lease.document.get(key) != value for key, value in expected.items()):
            raise LeaseError("lease-plan-mismatch")
        try:
            current = self.host_port.read(self._key(provider_id, project_root_hash))
        except Exception:
            raise LeaseError("lease-host-port-failed") from None
        if current is None:
            raise LeaseError("lease-not-current")
        current_lease = self._stored(current)
        if (
            current_lease.lease_hash != lease.lease_hash
            or current_lease.document["ownerNonce"] != lease.document["ownerNonce"]
            or current_lease.document["storeVersion"] != lease.document["storeVersion"]
        ):
            raise LeaseError("lease-not-current")
        now = at_time or self.clock.now()
        if self._is_stale(lease, now):
            raise LeaseError("lease-stale")
        self._assert_owner(lease)

    def heartbeat(self, lease: ProviderProjectLease) -> ProviderProjectLease:
        self.validate_live(
            lease,
            project_root_hash=str(lease.document["canonicalProjectRootHash"]),
            provider_id=str(lease.document["providerId"]),
            operation_id=str(lease.document["operationId"]),
            nonce=str(lease.document["operationNonce"]),
        )
        now = self.clock.now()
        body = clone(lease.document)
        body["storeVersion"] += 1
        body["heartbeatAt"] = _utc(now)
        body["expiresAt"] = _utc(now + timedelta(seconds=self.ttl_seconds))
        body["leaseHash"] = _hash_document(body, "leaseHash")
        validate_provider_project_lease(body)
        key = self._key(str(body["providerId"]), str(body["canonicalProjectRootHash"]))
        try:
            replaced = self.host_port.compare_and_replace(key, lease.lease_hash, body)
        except Exception:
            raise LeaseError("lease-host-port-failed") from None
        if not replaced:
            raise LeaseError("lease-cas-conflict")
        return ProviderProjectLease(body)

    def release(
        self, lease: ProviderProjectLease, *,
        stale_authorization: StaleUnlockAuthorization | Mapping[str, Any] | None = None,
        authorization_resolver: AuthorizationResolver | None = None,
    ) -> None:
        key = self._key(str(lease.document["providerId"]), str(lease.document["canonicalProjectRootHash"]))
        current_doc = self.host_port.read(key)
        if current_doc is None:
            raise LeaseError("lease-not-current")
        current = self._stored(current_doc)
        if current.lease_hash != lease.lease_hash:
            raise LeaseError("lease-not-current")
        now = self.clock.now()
        if self._is_stale(current, now):
            if stale_authorization is None or authorization_resolver is None:
                raise LeaseError("stale-unlock-requires-authoritative-authorization")
            self._validate_stale_authorization(
                current, stale_authorization, authorization_resolver, now,
            )
        else:
            self._assert_owner(current)
        try:
            deleted = self.host_port.compare_and_delete(key, current.lease_hash)
        except Exception:
            raise LeaseError("lease-host-port-failed") from None
        if not deleted:
            raise LeaseError("lease-cas-conflict")

    def _validate_stale_authorization(
        self, lease: ProviderProjectLease,
        authorization: StaleUnlockAuthorization | Mapping[str, Any],
        resolver: AuthorizationResolver, now: datetime,
    ) -> None:
        embedded = authorization.document if isinstance(authorization, StaleUnlockAuthorization) else dict(authorization)
        try:
            resolution = resolver.resolve(embedded["authorizationHash"])
        except Exception:
            raise LeaseError("stale-unlock-authorization-resolution-failed") from None
        if not isinstance(resolution, AuthorizationResolution):
            raise LeaseError("stale-unlock-authorization-resolution-invalid")
        if resolution.authority_class not in {"external-host", "fake-test"}:
            raise LeaseError("stale-unlock-authorization-resolution-invalid")
        if resolution.authority_class == "fake-test" and not self.test_mode:
            raise LeaseError("test-authorization-resolver-rejected")
        if resolution.status != "active" or not resolution.issuer_trusted:
            raise LeaseError("stale-unlock-authorization-revoked")
        document = clone(resolution.document)
        if document != embedded:
            raise LeaseError("stale-unlock-authorization-not-authoritative")
        validate_provider_stale_unlock_authorization(document, allow_test_issuer=self.test_mode)
        expected = {
            "leaseHash": lease.lease_hash,
            "providerId": lease.document["providerId"],
            "canonicalProjectRootHash": lease.document["canonicalProjectRootHash"],
            "operationId": lease.document["operationId"],
            "operationNonce": lease.document["operationNonce"],
            "ownerNonce": lease.document["ownerNonce"],
            "storeVersion": lease.document["storeVersion"],
        }
        if any(document.get(key) != value for key, value in expected.items()):
            raise LeaseError("stale-unlock-authorization-mismatch")
        if document.get("revocationState") != "active" or not (
            _parse_utc(document["issuedAt"]) <= now <= _parse_utc(document["expiresAt"])
        ):
            raise LeaseError("stale-unlock-authorization-invalid")

    def _assert_owner(self, lease: ProviderProjectLease) -> None:
        pid, start, boot, host, session = self._identity()
        expected = {
            "ownerPid": pid,
            "processStartTime": start,
            "bootIdentity": boot,
            "hostIdentity": host,
            "userSession": session,
        }
        if any(lease.document.get(key) != value for key, value in expected.items()):
            raise LeaseError("lease-owner-not-live")
        try:
            live = self.process.is_live(pid, start)
        except Exception:
            raise LeaseError("lease-identity-unavailable") from None
        if not live:
            raise LeaseError("lease-owner-not-live")

    def _is_stale(self, lease: ProviderProjectLease, now: datetime) -> bool:
        try:
            boot_changed = lease.document["bootIdentity"] != self.boot.current()
            owner_dead = not self.process.is_live(
                int(lease.document["ownerPid"]), str(lease.document["processStartTime"]),
            )
            heartbeat = _parse_utc(str(lease.document["heartbeatAt"]))
            expires = _parse_utc(str(lease.document["expiresAt"]))
        except Exception:
            return True
        return (
            boot_changed or owner_dead
            or heartbeat < now - timedelta(seconds=self.heartbeat_seconds)
            or expires < now
        )
