"""Cross-process Provider/project leases with an injected CAS authority."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterator, Mapping, Protocol

from selfworkflow.v3.contracts import (
    validate_provider_project_lease,
    validate_provider_stale_unlock_authorization,
)
from selfworkflow.v3.hashing import clone, content_hash, project_root_hash


MAX_LEASE_BYTES = 64 * 1024


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


class LeaseStore(Protocol):
    def read(self, key: str) -> dict[str, Any] | None: ...
    def create(self, key: str, document: Mapping[str, Any]) -> bool: ...
    def replace(self, key: str, expected_hash: str, document: Mapping[str, Any]) -> bool: ...
    def delete(self, key: str, expected_hash: str) -> bool: ...


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


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _validate_directory_chain(path: Path) -> Path:
    if not path.is_absolute():
        raise LeaseError("lease-state-root-not-absolute")
    try:
        resolved = path.resolve(strict=True)
        if resolved == Path(resolved.anchor):
            raise LeaseError("lease-state-root-too-broad")
        current = Path(resolved.anchor)
        for part in resolved.parts[1:]:
            current /= part
            info = current.lstat()
            if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                raise LeaseError("lease-state-root-unsafe")
        return resolved
    except LeaseError:
        raise
    except (OSError, ValueError):
        raise LeaseError("lease-state-root-invalid") from None


def _strict_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_LEASE_BYTES:
        raise LeaseError("lease-store-record-too-large")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LeaseError("lease-store-json-duplicate-key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(LeaseError("lease-store-json-invalid")),
        )
    except LeaseError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise LeaseError("lease-store-json-invalid") from None
    if not isinstance(value, dict):
        raise LeaseError("lease-store-json-invalid")
    return value


class AtomicFileLeaseStore:
    """Small bounded JSON CAS store under one explicit non-reparse state root."""

    def __init__(self, state_root: str | Path) -> None:
        self.root = _validate_directory_chain(Path(state_root))
        self._root_chain = self._capture_root_chain()

    def _capture_root_chain(self) -> tuple[tuple[Path, os.stat_result], ...]:
        result: list[tuple[Path, os.stat_result]] = []
        current = Path(self.root.anchor)
        for part in self.root.parts[1:]:
            current /= part
            info = current.lstat()
            if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                raise LeaseError("lease-state-root-unsafe")
            result.append((current, info))
        return tuple(result)

    def _assert_root_identity(self) -> None:
        try:
            for path, expected in self._root_chain:
                current = path.lstat()
                if (
                    _is_reparse(current) or not stat.S_ISDIR(current.st_mode)
                    or not os.path.samestat(expected, current)
                ):
                    raise LeaseError("lease-state-root-changed")
        except LeaseError:
            raise
        except OSError:
            raise LeaseError("lease-state-root-changed") from None

    def _path(self, key: str) -> Path:
        self._assert_root_identity()
        return self.root / (content_hash({"leaseKey": key})[7:] + ".json")

    @contextmanager
    def _guard(self, key: str) -> Iterator[None]:
        path = self._path(key).with_suffix(".guard")
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise LeaseError("lease-store-busy") from None
        try:
            os.close(descriptor)
            self._assert_root_identity()
            yield
        finally:
            self._assert_root_identity()
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _read_unlocked(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            before = path.lstat()
        except FileNotFoundError:
            return None
        if _is_reparse(before) or not stat.S_ISREG(before.st_mode) or before.st_size > MAX_LEASE_BYTES:
            raise LeaseError("lease-store-record-unsafe")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                raw = os.read(descriptor, MAX_LEASE_BYTES + 1)
            finally:
                os.close(descriptor)
        except OSError:
            raise LeaseError("lease-store-read-failed") from None
        if not os.path.samestat(before, opened) or len(raw) != opened.st_size:
            raise LeaseError("lease-store-record-changed")
        self._assert_root_identity()
        document = _strict_json(raw)
        validate_provider_project_lease(document)
        return document

    def read(self, key: str) -> dict[str, Any] | None:
        with self._guard(key):
            value = self._read_unlocked(key)
            return None if value is None else clone(value)

    def create(self, key: str, document: Mapping[str, Any]) -> bool:
        with self._guard(key):
            if self._read_unlocked(key) is not None:
                return False
            raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if len(raw) > MAX_LEASE_BYTES:
                raise LeaseError("lease-store-record-too-large")
            path = self._path(key)
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
                try:
                    written = 0
                    while written < len(raw):
                        count = os.write(descriptor, raw[written:])
                        if count <= 0:
                            raise LeaseError("lease-store-write-failed")
                        written += count
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except FileExistsError:
                return False
            self._assert_root_identity()
            return True

    def replace(self, key: str, expected_hash: str, document: Mapping[str, Any]) -> bool:
        with self._guard(key):
            current = self._read_unlocked(key)
            if current is None or current.get("leaseHash") != expected_hash:
                return False
            raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if len(raw) > MAX_LEASE_BYTES:
                raise LeaseError("lease-store-record-too-large")
            path = self._path(key)
            temp = path.with_suffix("." + content_hash(document)[7:23] + ".tmp")
            try:
                descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
                try:
                    written = 0
                    while written < len(raw):
                        count = os.write(descriptor, raw[written:])
                        if count <= 0:
                            raise LeaseError("lease-store-write-failed")
                        written += count
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.replace(temp, path)
                self._assert_root_identity()
            finally:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass
            return True

    def delete(self, key: str, expected_hash: str) -> bool:
        with self._guard(key):
            current = self._read_unlocked(key)
            if current is None or current.get("leaseHash") != expected_hash:
                return False
            self._path(key).unlink()
            self._assert_root_identity()
            return True


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


def _hash_document(body: Mapping[str, Any], field: str) -> str:
    return content_hash({key: value for key, value in body.items() if key != field})


def build_stale_unlock_authorization(
    lease: ProviderProjectLease, *, issued_at: datetime, expires_at: datetime,
    nonce: str, confirmation_source: str = "user-confirmation",
) -> StaleUnlockAuthorization:
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
        "confirmationSource": confirmation_source,
        "revocationState": "active",
    }
    body["authorizationHash"] = content_hash(body)
    validate_provider_stale_unlock_authorization(body)
    return StaleUnlockAuthorization(clone(body))


class ProviderLeaseManager:
    def __init__(
        self, *, store: LeaseStore, clock: Clock | None = None,
        process: ProcessIdentity | None = None, boot: BootIdentity | None = None,
        host_identity: str | None = None, user_session: str | None = None,
        heartbeat_seconds: int = 30, ttl_seconds: int = 300,
    ) -> None:
        self.store = store
        self.clock = clock or SystemClock()
        self.process = process or _UnavailableProcessIdentity()
        self.boot = boot or _UnavailableBootIdentity()
        self.host_identity = host_identity
        self.user_session = user_session
        self.heartbeat_seconds = heartbeat_seconds
        self.ttl_seconds = ttl_seconds

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
            isinstance(value, str) and value for value in (start, boot, self.host_identity, self.user_session)
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

    def acquire(self, *, project_root: str, provider_id: str, operation_id: str, nonce: str) -> ProviderProjectLease:
        root_hash = project_root_hash(project_root)
        key = self._key(provider_id, root_hash)
        now = self.clock.now()
        existing = self.store.read(key)
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
            "ownerNonce": content_hash({"provider": provider_id, "root": root_hash, "operationNonce": nonce, "issuedAt": _utc(now)})[7:39],
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
        if not self.store.create(key, body):
            raise LeaseError("lease-concurrent-owner")
        return ProviderProjectLease(clone(body))

    def validate_live(
        self, lease: ProviderProjectLease, *, project_root_hash: str,
        provider_id: str, operation_id: str, nonce: str,
    ) -> None:
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
        current = self.store.read(self._key(provider_id, project_root_hash))
        if current is None:
            raise LeaseError("lease-not-current")
        current_lease = self._stored(current)
        if current_lease.lease_hash != lease.lease_hash:
            raise LeaseError("lease-not-current")
        if self._is_stale(lease, self.clock.now()):
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
        if not self.store.replace(key, lease.lease_hash, body):
            raise LeaseError("lease-cas-conflict")
        return ProviderProjectLease(body)

    def release(
        self, lease: ProviderProjectLease, *,
        stale_authorization: StaleUnlockAuthorization | Mapping[str, Any] | None = None,
    ) -> None:
        key = self._key(str(lease.document["providerId"]), str(lease.document["canonicalProjectRootHash"]))
        current_doc = self.store.read(key)
        if current_doc is None:
            raise LeaseError("lease-not-current")
        current = self._stored(current_doc)
        if current.lease_hash != lease.lease_hash:
            raise LeaseError("lease-not-current")
        now = self.clock.now()
        if self._is_stale(current, now):
            if stale_authorization is None:
                raise LeaseError("stale-unlock-requires-authorization")
            self._validate_stale_authorization(current, stale_authorization, now)
        else:
            self._assert_owner(current)
        if not self.store.delete(key, current.lease_hash):
            raise LeaseError("lease-cas-conflict")

    def _validate_stale_authorization(
        self, lease: ProviderProjectLease,
        authorization: StaleUnlockAuthorization | Mapping[str, Any], now: datetime,
    ) -> None:
        document = authorization.document if isinstance(authorization, StaleUnlockAuthorization) else dict(authorization)
        validate_provider_stale_unlock_authorization(document)
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
            document["issuedAt"] <= _utc(now) <= document["expiresAt"]
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
        except Exception:
            return True
        return (
            boot_changed or owner_dead
            or str(lease.document["heartbeatAt"]) < _utc(now - timedelta(seconds=self.heartbeat_seconds))
            or str(lease.document["expiresAt"]) < _utc(now)
        )
