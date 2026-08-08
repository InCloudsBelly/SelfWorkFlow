"""Terminal-review tests for the fail-closed Provider execution MVP."""

from __future__ import annotations

import importlib
import unittest

from selfworkflow.v3 import approvals, project_lease


class ProviderMvpFailClosedTests(unittest.TestCase):
    def test_authoritative_authorization_and_replay_state_machine_are_public_contracts(self):
        self.assertTrue(hasattr(approvals, "AuthorizationResolver"))
        self.assertTrue(hasattr(approvals.ReplayStore, "reserve"))
        self.assertTrue(hasattr(approvals.ReplayStore, "commit"))
        self.assertTrue(hasattr(approvals.ReplayStore, "abort"))
        self.assertFalse(hasattr(approvals.ReplayStore, "consume"))

    def test_repo_does_not_ship_a_python_path_atomic_lease_store(self):
        self.assertFalse(hasattr(project_lease, "AtomicFileLeaseStore"))
        self.assertTrue(hasattr(project_lease, "HostAtomicLeasePort"))

    def test_trusted_command_registry_is_required_surface(self):
        registry = importlib.import_module("selfworkflow.v3.command_registry")
        self.assertTrue(hasattr(registry, "AdapterCommandTemplate"))
        self.assertTrue(hasattr(registry, "TrustedCommandRegistry"))


if __name__ == "__main__":
    unittest.main()
