import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from selfworkflow.v3.project_lease import (
    LeaseError,
    ProviderLeaseManager,
    build_stale_unlock_authorization,
)


class Clock:
    def __init__(self): self.value = datetime(2026, 8, 9, tzinfo=timezone.utc)
    def now(self): return self.value
    def advance(self, seconds): self.value += timedelta(seconds=seconds)


class Process:
    def __init__(self): self.pid = 100; self.start = "start-a"; self.live = True
    def current(self): return self.pid, self.start
    def is_live(self, pid, start): return self.live and pid == self.pid and start == self.start


class Boot:
    def __init__(self): self.value = "boot-a"
    def current(self): return self.value


class Store:
    def __init__(self): self.values = {}
    def read(self, key): return None if key not in self.values else dict(self.values[key])
    def create(self, key, document):
        if key in self.values: return False
        self.values[key] = dict(document); return True
    def replace(self, key, expected_hash, document):
        if key not in self.values or self.values[key]["leaseHash"] != expected_hash: return False
        self.values[key] = dict(document); return True
    def delete(self, key, expected_hash):
        if key not in self.values or self.values[key]["leaseHash"] != expected_hash: return False
        del self.values[key]; return True


class ProjectLockingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock, self.process, self.boot, self.store = Clock(), Process(), Boot(), Store()
        self.manager = self.new_manager()

    def new_manager(self):
        return ProviderLeaseManager(
            store=self.store, clock=self.clock, process=self.process, boot=self.boot,
            host_identity="host-a", user_session="session-a",
            heartbeat_seconds=2, ttl_seconds=10,
        )

    def tearDown(self): self.temp.cleanup()

    def acquire(self, nonce="nonce-a"):
        return self.manager.acquire(
            project_root=self.temp.name, provider_id="fake.provider",
            operation_id="sync-incremental", nonce=nonce,
        )

    def unlock(self, lease):
        authorization = build_stale_unlock_authorization(
            lease, issued_at=self.clock.now(),
            expires_at=self.clock.now() + timedelta(minutes=1), nonce="unlock-a",
        )
        self.manager.release(lease, stale_authorization=authorization)

    def test_live_owner_and_cross_manager_concurrency_are_enforced(self):
        lease = self.acquire()
        with self.assertRaisesRegex(LeaseError, "lease-concurrent-owner"):
            self.new_manager().acquire(
                project_root=self.temp.name, provider_id="fake.provider",
                operation_id="sync-incremental", nonce="nonce-b",
            )
        self.clock.advance(1)
        refreshed = self.manager.heartbeat(lease)
        self.assertNotEqual(refreshed.lease_hash, lease.lease_hash)
        self.manager.release(refreshed)

    def test_pid_reuse_and_reboot_require_typed_stale_unlock(self):
        lease = self.acquire()
        self.process.start = "start-b"
        self.process.pid = 101
        with self.assertRaisesRegex(LeaseError, "stale-unlock-requires-authorization"):
            self.acquire("nonce-b")
        self.unlock(lease)
        replacement = self.acquire("nonce-b")
        self.boot.value = "boot-c"
        with self.assertRaisesRegex(LeaseError, "stale-unlock-requires-authorization"):
            self.manager.release(replacement)
        self.unlock(replacement)

    def test_stale_heartbeat_requires_typed_unlock_and_tamper_is_rejected(self):
        lease = self.acquire()
        self.clock.advance(3)
        with self.assertRaisesRegex(LeaseError, "stale-unlock-requires-authorization"):
            self.manager.release(lease)
        authorization = build_stale_unlock_authorization(
            lease, issued_at=self.clock.now(),
            expires_at=self.clock.now() + timedelta(minutes=1), nonce="unlock-a",
        )
        authorization.document["operationNonce"] = "wrong"
        with self.assertRaises(Exception):
            self.manager.release(lease, stale_authorization=authorization)


if __name__ == "__main__": unittest.main()
