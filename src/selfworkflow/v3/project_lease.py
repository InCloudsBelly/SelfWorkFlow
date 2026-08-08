"""Provider/project leases independent from installer locks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import threading
from typing import Callable, Mapping, Protocol

from selfworkflow.v3.contracts import validate_provider_project_lease
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


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class CurrentProcessIdentity:
    def current(self) -> tuple[int, str]:
        return os.getpid(), str(os.getpid())

    def is_live(self, pid: int, process_start_time: str) -> bool:
        return pid == os.getpid() and process_start_time == str(os.getpid())


class SystemBootIdentity:
    def current(self) -> str:
        return content_hash({"boot": os.name, "pid": os.getpid()})


@dataclass(frozen=True)
class ProviderProjectLease:
    document: dict[str, object]

    @property
    def lease_hash(self) -> str:
        return self.document["leaseHash"]  # type: ignore[return-value]


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise LeaseError("lease-time-not-utc")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ProviderLeaseManager:
    """In-memory host-side lease authority; no installer lock is consulted."""

    def __init__(
        self, *, clock: Clock | None = None,
        process: ProcessIdentity | None = None,
        boot: BootIdentity | None = None,
        host_identity: str = "host",
        user_session: str = "session",
        heartbeat_seconds: int = 30,
        ttl_seconds: int = 300,
    ) -> None:
        self.clock = clock or SystemClock()
        self.process = process or CurrentProcessIdentity()
        self.boot = boot or SystemBootIdentity()
        self.host_identity = host_identity
        self.user_session = user_session
        self.heartbeat_seconds = heartbeat_seconds
        self.ttl_seconds = ttl_seconds
        self._leases: dict[tuple[str, str], ProviderProjectLease] = {}
        self._lock = threading.RLock()

    def acquire(self, *, project_root: str, provider_id: str, operation_id: str, nonce: str) -> ProviderProjectLease:
        root_hash = project_root_hash(project_root)
        key = (provider_id, root_hash)
        now = self.clock.now()
        with self._lock:
            old = self._leases.get(key)
            if old is not None and not self._is_stale(old, now):
                raise LeaseError("lease-concurrent-owner")
            pid, start = self.process.current()
            body: dict[str, object] = {
                "schemaVersion": 3, "leaseHash": "",
                "canonicalProjectRootHash": root_hash, "providerId": provider_id,
                "operationId": operation_id, "operationNonce": nonce,
                "ownerPid": pid, "processStartTime": start,
                "userSession": self.user_session, "hostIdentity": self.host_identity,
                "bootIdentity": self.boot.current(), "heartbeatAt": _utc(now),
                "issuedAt": _utc(now), "expiresAt": _utc(now + timedelta(seconds=self.ttl_seconds)),
            }
            body["leaseHash"] = content_hash({key: value for key, value in body.items() if key != "leaseHash"})
            validate_provider_project_lease(body)
            lease = ProviderProjectLease(clone(body))
            self._leases[key] = lease
            return lease

    def heartbeat(self, lease: ProviderProjectLease) -> ProviderProjectLease:
        with self._lock:
            current = self._find(lease)
            now = self.clock.now()
            if self._is_stale(current, now):
                raise LeaseError("lease-stale")
            if current.document["bootIdentity"] != self.boot.current() or not self.process.is_live(current.document["ownerPid"], current.document["processStartTime"]):
                raise LeaseError("lease-owner-not-live")
            body = clone(current.document)
            body["heartbeatAt"] = _utc(now)
            body["expiresAt"] = _utc(now + timedelta(seconds=self.ttl_seconds))
            body["leaseHash"] = content_hash({key: value for key, value in body.items() if key != "leaseHash"})
            validate_provider_project_lease(body)
            refreshed = ProviderProjectLease(body)
            self._leases[self._key(body)] = refreshed
            return refreshed

    def release(self, lease: ProviderProjectLease, *, allow_stale_unlock: bool = False) -> None:
        with self._lock:
            current = self._find(lease)
            now = self.clock.now()
            if self._is_stale(current, now) and not allow_stale_unlock:
                raise LeaseError("stale-unlock-requires-authorization")
            if not allow_stale_unlock and (
                current.document["bootIdentity"] != self.boot.current()
                or not self.process.is_live(current.document["ownerPid"], current.document["processStartTime"])
            ):
                raise LeaseError("lease-owner-not-live")
            del self._leases[self._key(current.document)]

    def _key(self, document: Mapping[str, object]) -> tuple[str, str]:
        return str(document["providerId"]), str(document["canonicalProjectRootHash"])

    def _find(self, lease: ProviderProjectLease) -> ProviderProjectLease:
        current = self._leases.get(self._key(lease.document))
        if current is None or current.lease_hash != lease.lease_hash:
            raise LeaseError("lease-not-current")
        return current

    def _is_stale(self, lease: ProviderProjectLease, now: datetime) -> bool:
        return (
            lease.document["bootIdentity"] != self.boot.current()
            or not self.process.is_live(lease.document["ownerPid"], lease.document["processStartTime"])
            or str(lease.document["heartbeatAt"]) < _utc(now - timedelta(seconds=self.heartbeat_seconds))
            or str(lease.document["expiresAt"]) < _utc(now)
        )
