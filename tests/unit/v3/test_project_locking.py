import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from selfworkflow.v3.project_lease import LeaseError, ProviderLeaseManager


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


class ProjectLockingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock, self.process, self.boot = Clock(), Process(), Boot()
        self.manager = ProviderLeaseManager(clock=self.clock, process=self.process, boot=self.boot, host_identity="host-a", user_session="session-a", heartbeat_seconds=2, ttl_seconds=10)
    def tearDown(self): self.temp.cleanup()

    def acquire(self): return self.manager.acquire(project_root=self.temp.name, provider_id="fake.provider", operation_id="sync-incremental", nonce="nonce-a")

    def test_live_owner_and_concurrency_are_enforced(self):
        lease = self.acquire()
        with self.assertRaisesRegex(LeaseError, "lease-concurrent-owner"):
            self.acquire()
        self.clock.advance(1)
        refreshed = self.manager.heartbeat(lease)
        self.assertNotEqual(refreshed.lease_hash, lease.lease_hash)
        self.manager.release(refreshed)

    def test_pid_reuse_reboot_and_heartbeat_make_old_lease_stale(self):
        lease = self.acquire()
        self.process.start = "start-b"
        # PID identity changed: the old lease is stale and a new owner may take the key.
        self.process.pid = 101
        replacement = self.acquire()
        self.assertNotEqual(replacement.document["processStartTime"], lease.document["processStartTime"])
        self.boot.value = "boot-c"
        with self.assertRaisesRegex(LeaseError, "stale-unlock-requires-authorization"):
            self.manager.release(replacement)
        self.manager.release(replacement, allow_stale_unlock=True)

    def test_stale_heartbeat_requires_authorized_unlock(self):
        lease = self.acquire()
        self.clock.advance(3)
        with self.assertRaisesRegex(LeaseError, "stale-unlock-requires-authorization"):
            self.manager.release(lease)
        self.manager.release(lease, allow_stale_unlock=True)


if __name__ == "__main__": unittest.main()
