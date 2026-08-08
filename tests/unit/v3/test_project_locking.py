from __future__ import annotations

from datetime import timedelta
import tempfile
from threading import Barrier, Thread
import unittest

from selfworkflow.v3.contracts import ContractError, validate_provider_stale_unlock_authorization
from selfworkflow.v3.project_lease import (
    LeaseError,
    ProviderLeaseManager,
    build_stale_unlock_authorization,
)
from tests.fixtures.providers.security_fakes import (
    FakeAuthorizationResolver,
    FakeBootIdentity,
    FakeClock,
    FakeHostAtomicLeasePort,
    FakeProcessIdentity,
    NOW,
)


class ProjectLockingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.port = FakeHostAtomicLeasePort()
        self.clock = FakeClock()
        self.process = FakeProcessIdentity()
        self.boot = FakeBootIdentity()

    def tearDown(self):
        self.temp.cleanup()

    def manager(self):
        return ProviderLeaseManager(
            host_port=self.port, clock=self.clock, process=self.process,
            boot=self.boot, host_identity="host-a", user_session="session-a",
            heartbeat_seconds=2, ttl_seconds=10, test_mode=True,
        )

    def test_two_manager_instances_are_mechanically_mutually_exclusive(self):
        first = self.manager()
        second = self.manager()
        lease = first.acquire(
            project_root=self.temp.name, provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        with self.assertRaisesRegex(LeaseError, "lease-concurrent-owner"):
            second.acquire(
                project_root=self.temp.name, provider_id="fake.provider",
                operation_id="sync-incremental", nonce="nonce-b",
            )
        second.validate_live(
            lease, project_root_hash=lease.document["canonicalProjectRootHash"],
            provider_id="fake.provider", operation_id="sync-incremental",
            nonce="nonce-a",
        )

    def test_concurrent_compare_and_create_has_one_winner(self):
        barrier = Barrier(2)
        outcomes: list[str] = []

        def acquire(nonce):
            barrier.wait()
            try:
                self.manager().acquire(
                    project_root=self.temp.name, provider_id="fake.provider",
                    operation_id="sync-incremental", nonce=nonce,
                )
                outcomes.append("won")
            except LeaseError:
                outcomes.append("lost")

        threads = [Thread(target=acquire, args=(f"nonce-{i}",)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ["lost", "won"])

    def test_fake_backend_and_unreliable_default_identity_fail_closed(self):
        with self.assertRaisesRegex(LeaseError, "test-lease-backend-rejected"):
            ProviderLeaseManager(host_port=self.port)
        manager = ProviderLeaseManager(host_port=self.port, test_mode=True)
        with self.assertRaisesRegex(LeaseError, "lease-identity-unavailable"):
            manager.acquire(
                project_root=self.temp.name, provider_id="fake.provider",
                operation_id="sync-incremental", nonce="nonce-a",
            )

    def test_stale_unlock_needs_current_authoritative_non_revoked_receipt(self):
        manager = self.manager()
        lease = manager.acquire(
            project_root=self.temp.name, provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        self.clock.advance(3)
        authorization = build_stale_unlock_authorization(
            lease, issued_at=NOW, expires_at=NOW + timedelta(minutes=1),
            nonce="unlock-a",
        )
        with self.assertRaisesRegex(LeaseError, "authoritative-authorization"):
            manager.release(lease, stale_authorization=authorization)
        resolver = FakeAuthorizationResolver(authorization.document)
        resolver.revoke(authorization.document["authorizationHash"])
        with self.assertRaisesRegex(LeaseError, "authorization-revoked"):
            manager.release(
                lease, stale_authorization=authorization,
                authorization_resolver=resolver,
            )
        resolver.statuses[authorization.document["authorizationHash"]] = "active"
        manager.release(
            lease, stale_authorization=authorization,
            authorization_resolver=resolver,
        )

    def test_owner_tuple_nonce_version_and_cas_takeover_are_checked(self):
        manager = self.manager()
        lease = manager.acquire(
            project_root=self.temp.name, provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        takeover = dict(lease.document)
        takeover["ownerNonce"] = "attacker"
        from selfworkflow.v3.hashing import content_hash
        takeover["leaseHash"] = content_hash({
            key: value for key, value in takeover.items() if key != "leaseHash"
        })
        key = manager._key("fake.provider", lease.document["canonicalProjectRootHash"])
        self.port.replace_with_takeover(key, takeover)
        with self.assertRaisesRegex(LeaseError, "lease-not-current"):
            manager.validate_live(
                lease, project_root_hash=lease.document["canonicalProjectRootHash"],
                provider_id="fake.provider", operation_id="sync-incremental",
                nonce="nonce-a",
            )

    def test_public_stale_authorization_validator_rejects_test_issuer(self):
        manager = self.manager()
        lease = manager.acquire(
            project_root=self.temp.name, provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        authorization = build_stale_unlock_authorization(
            lease, issued_at=NOW, expires_at=NOW + timedelta(minutes=1),
            nonce="unlock-test", issuer_id="test-fixture", test_mode=True,
        )
        with self.assertRaisesRegex(ContractError, "test-authorization-rejected"):
            validate_provider_stale_unlock_authorization(authorization.document)


if __name__ == "__main__":
    unittest.main()
