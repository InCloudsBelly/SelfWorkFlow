from __future__ import annotations

from datetime import timedelta
import tempfile
import unittest

from selfworkflow.v3.effects import EffectMutation
from selfworkflow.v3.hashing import clone, content_hash
from selfworkflow.v3.project_state import WorkspaceObservation
from selfworkflow.v3.runner import RunnerError, run_operation, run_query
from tests.fixtures.providers.fake_provider import FakeEffectPort
from tests.fixtures.providers.security_fakes import (
    FakeHostAtomicLeasePort,
    FakeReplayStore,
    H,
    NOW,
    evidence_for,
    lease_manager,
    operation_bundle,
    query_bundle,
)


class Observer:
    def __init__(self, *observations):
        self.observations = iter(observations)

    def capture(self):
        return next(self.observations)


class ProviderRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def write_context(self, plan):
        manager = lease_manager()
        lease = manager.acquire(
            project_root=self.temp.name, provider_id=plan.document["providerId"],
            operation_id=plan.document["operationId"],
            nonce=plan.document["executionNonce"],
        )
        return manager, lease

    def test_caller_can_release_its_lease_after_runner_success_or_failure(self):
        for query in (False, True):
            for exit_code in (0, 1):
                with self.subTest(query=query, exit_code=exit_code):
                    bundle = query_bundle(self.temp.name, side_effects="local-write", operation_id="sync-incremental", action="sync") if query else operation_bundle(self.temp.name)
                    plan, approval, registry, _machine, resolver = bundle
                    manager, lease = self.write_context(plan)
                    arguments = dict(approval=approval, effect_port=FakeEffectPort(exit_code=exit_code, mutation_evidence=(evidence_for(plan),)), now=NOW,
                                     trusted_command_registry=registry, authorization_resolver=resolver, lease=lease, lease_manager=manager,
                                     replay_store=FakeReplayStore(), test_mode=True)
                    if query:
                        observation = WorkspaceObservation(H, {"fingerprintHash": H})
                        arguments.update(observer=Observer(observation, observation), returned_files=[], index_revision="r1", index_completeness="complete")
                    invoke = run_query if query else run_operation
                    if query and exit_code:
                        with self.assertRaisesRegex(RunnerError, "effect-failed"):
                            invoke(plan, **arguments)
                    else:
                        invoke(plan, **arguments)
                    manager.release(lease)
                    next_lease = manager.acquire(project_root=self.temp.name, provider_id=plan.document["providerId"], operation_id=plan.document["operationId"], nonce="next-caller")
                    manager.release(next_lease)

    def test_success_executes_only_sealed_command_and_commits_terminal_success(self):
        plan, approval, registry, _machine, resolver = operation_bundle(self.temp.name)
        manager, lease = self.write_context(plan)
        evidence = evidence_for(plan)
        port = FakeEffectPort(
            mutations=(EffectMutation("managed-state", "index", "sync"),),
            mutation_evidence=(evidence,),
        )
        replay = FakeReplayStore()
        receipt, _result = run_operation(
            plan, approval=approval, effect_port=port, now=NOW,
            trusted_command_registry=registry, authorization_resolver=resolver,
            lease=lease, lease_manager=manager, replay_store=replay,
            test_mode=True,
        )
        self.assertEqual(port.calls[0].argv, tuple(plan.document["commandSpec"]["argv"]))
        self.assertEqual(port.calls[0].env, plan.document["commandSpec"]["env"])
        self.assertEqual(port.calls[0].cwd, plan.document["commandSpec"]["cwd"])
        self.assertEqual(receipt["outcome"], "succeeded")
        self.assertEqual(receipt["replayState"], "terminal-succeeded")
        self.assertIn("terminal-succeeded", replay.states.values())

    def test_caller_can_release_after_post_validation_exception(self):
        plan, approval, registry, _machine, resolver = operation_bundle(self.temp.name)
        manager, lease = self.write_context(plan)
        with self.assertRaises(RunnerError):
            run_operation(plan, approval=approval, effect_port=FakeEffectPort(mutation_evidence=()), now=NOW,
                          trusted_command_registry=registry, authorization_resolver=resolver, lease=lease,
                          lease_manager=manager, replay_store=FakeReplayStore(), test_mode=True)
        manager.release(lease)

    def test_runner_does_not_adopt_or_release_a_replacement_owner(self):
        from selfworkflow.v3.project_lease import LeaseError
        plan, approval, registry, _machine, resolver = operation_bundle(self.temp.name)
        manager, lease = self.write_context(plan)
        key = manager._key(plan.document["providerId"], lease.document["canonicalProjectRootHash"])

        def takeover():
            replacement = clone(lease.document)
            replacement["ownerNonce"] = "replacement-owner"
            replacement["leaseHash"] = content_hash({key: value for key, value in replacement.items() if key != "leaseHash"})
            manager.host_port.replace_with_takeover(key, replacement)

        with self.assertRaises(RunnerError):
            run_operation(plan, approval=approval, effect_port=FakeEffectPort(during_effect=takeover), now=NOW,
                          trusted_command_registry=registry, authorization_resolver=resolver, lease=lease,
                          lease_manager=manager, replay_store=FakeReplayStore(), test_mode=True)
        with self.assertRaisesRegex(LeaseError, "lease-not-current"):
            manager.release(lease)
        self.assertEqual(manager.host_port.read(key)["ownerNonce"], "replacement-owner")

    def test_independent_heartbeat_keeps_the_old_snapshot_stale(self):
        from selfworkflow.v3.project_lease import LeaseError
        plan, *_ = operation_bundle(self.temp.name)
        manager, original = self.write_context(plan)
        latest = manager.heartbeat(original)
        with self.assertRaisesRegex(LeaseError, "lease-not-current"):
            manager.release(original)
        manager.release(latest)

    def test_missing_registry_resolver_lease_or_host_capability_fails_before_effect(self):
        plan, approval, registry, _machine, resolver = operation_bundle(self.temp.name)
        port = FakeEffectPort()
        replay = FakeReplayStore()
        with self.assertRaisesRegex(RunnerError, "trusted-command-registry-required"):
            run_operation(
                plan, approval=approval, effect_port=port, now=NOW,
                authorization_resolver=resolver, replay_store=replay, test_mode=True,
            )
        with self.assertRaisesRegex(RunnerError, "machine-authorization-resolver-required"):
            run_operation(
                plan, approval=approval, effect_port=port, now=NOW,
                trusted_command_registry=registry, replay_store=replay, test_mode=True,
            )
        with self.assertRaisesRegex(RunnerError, "live-provider-lease-required"):
            run_operation(
                plan, approval=approval, effect_port=port, now=NOW,
                trusted_command_registry=registry, authorization_resolver=resolver,
                replay_store=replay, test_mode=True,
            )
        self.assertEqual(port.calls, [])

    def test_revoked_or_untrusted_authoritative_machine_state_is_rejected(self):
        plan, approval, registry, machine, resolver = operation_bundle(self.temp.name)
        manager, lease = self.write_context(plan)
        resolver.revoke(machine.authorization_hash)
        with self.assertRaisesRegex(RunnerError, "machine-authorization-revoked"):
            run_operation(
                plan, approval=approval, effect_port=FakeEffectPort(), now=NOW,
                trusted_command_registry=registry, authorization_resolver=resolver,
                lease=lease, lease_manager=manager, replay_store=FakeReplayStore(),
                test_mode=True,
            )
        resolver.statuses[machine.authorization_hash] = "active"
        resolver.trusted = False
        with self.assertRaisesRegex(RunnerError, "issuer-untrusted"):
            run_operation(
                plan, approval=approval, effect_port=FakeEffectPort(), now=NOW,
                trusted_command_registry=registry, authorization_resolver=resolver,
                lease=lease, lease_manager=manager, replay_store=FakeReplayStore(),
                test_mode=True,
            )
        resolver.trusted = True
        with self.assertRaisesRegex(RunnerError, "machine-authorization-expired"):
            run_operation(
                plan, approval=approval, effect_port=FakeEffectPort(),
                now=NOW + timedelta(minutes=11),
                trusted_command_registry=registry, authorization_resolver=resolver,
                lease=lease, lease_manager=manager, replay_store=FakeReplayStore(),
                test_mode=True,
            )

    def test_zero_mutation_still_requires_exact_verified_evidence(self):
        plan, approval, registry, _machine, resolver = operation_bundle(self.temp.name)
        manager, lease = self.write_context(plan)
        replay = FakeReplayStore()
        with self.assertRaises(RunnerError) as raised:
            run_operation(
                plan, approval=approval, effect_port=FakeEffectPort(), now=NOW,
                trusted_command_registry=registry, authorization_resolver=resolver,
                lease=lease, lease_manager=manager, replay_store=replay,
                test_mode=True,
            )
        self.assertEqual(raised.exception.reason, "required-mutation-evidence-missing")
        self.assertEqual(raised.exception.replay_state, "terminal-failed")
        self.assertIn("terminal-failed", replay.states.values())

    def test_effect_not_started_is_only_retryable_abort_path(self):
        plan, approval, registry, _machine, resolver = operation_bundle(
            self.temp.name, operation_id="inspect", ownership_domain="user-owned",
        )
        replay = FakeReplayStore()
        with self.assertRaises(RunnerError) as raised:
            run_operation(
                plan, approval=approval, effect_port=FakeEffectPort(not_started=True),
                now=NOW, trusted_command_registry=registry,
                authorization_resolver=resolver, replay_store=replay, test_mode=True,
            )
        self.assertEqual(raised.exception.replay_state, "aborted")
        self.assertTrue(raised.exception.retryable)
        receipt, _ = run_operation(
            plan, approval=approval, effect_port=FakeEffectPort(), now=NOW,
            trusted_command_registry=registry, authorization_resolver=resolver,
            replay_store=replay, test_mode=True,
        )
        self.assertEqual(receipt["replayState"], "terminal-succeeded")

    def test_post_effect_failure_is_terminal_and_cannot_replay(self):
        plan, approval, registry, _machine, resolver = operation_bundle(
            self.temp.name, operation_id="inspect", ownership_domain="user-owned",
        )
        replay = FakeReplayStore()
        bad_window = FakeEffectPort(
            started_at=NOW + timedelta(seconds=1),
            completed_at=NOW + timedelta(seconds=2),
        )
        with self.assertRaises(RunnerError) as raised:
            run_operation(
                plan, approval=approval, effect_port=bad_window, now=NOW,
                trusted_command_registry=registry, authorization_resolver=resolver,
                replay_store=replay, test_mode=True,
            )
        self.assertEqual(raised.exception.reason, "effect-invocation-outside-window")
        self.assertEqual(raised.exception.replay_state, "terminal-failed")
        with self.assertRaisesRegex(RunnerError, "approval-replay"):
            run_operation(
                plan, approval=approval, effect_port=FakeEffectPort(), now=NOW,
                trusted_command_registry=registry, authorization_resolver=resolver,
                replay_store=replay, test_mode=True,
            )

    def test_past_effect_window_is_rejected_as_terminal(self):
        plan, approval, registry, _machine, resolver = operation_bundle(
            self.temp.name, operation_id="inspect", ownership_domain="user-owned",
            nonce="nonce-past", attempt="attempt-past",
        )
        with self.assertRaises(RunnerError) as raised:
            run_operation(
                plan, approval=approval,
                effect_port=FakeEffectPort(
                    started_at=NOW - timedelta(seconds=2),
                    completed_at=NOW - timedelta(seconds=1),
                ),
                now=NOW, trusted_command_registry=registry,
                authorization_resolver=resolver, replay_store=FakeReplayStore(),
                test_mode=True,
            )
        self.assertEqual(raised.exception.reason, "effect-invocation-outside-window")
        self.assertEqual(raised.exception.replay_state, "terminal-failed")

    def test_lease_takeover_during_effect_cannot_succeed(self):
        plan, approval, registry, _machine, resolver = operation_bundle(self.temp.name)
        host = FakeHostAtomicLeasePort()
        manager = lease_manager(port=host)
        lease = manager.acquire(
            project_root=self.temp.name, provider_id="fake.provider",
            operation_id="sync-incremental", nonce="nonce-a",
        )
        key = manager._key("fake.provider", lease.document["canonicalProjectRootHash"])

        def takeover():
            current = host.read(key)
            current["ownerNonce"] = "takeover"
            current["leaseHash"] = content_hash({
                k: v for k, v in current.items() if k != "leaseHash"
            })
            host.replace_with_takeover(key, current)

        replay = FakeReplayStore()
        with self.assertRaises(RunnerError) as raised:
            run_operation(
                plan, approval=approval,
                effect_port=FakeEffectPort(
                    mutation_evidence=(evidence_for(plan),), during_effect=takeover,
                ),
                now=NOW, trusted_command_registry=registry,
                authorization_resolver=resolver, lease=lease,
                lease_manager=manager, replay_store=replay, test_mode=True,
            )
        self.assertEqual(raised.exception.replay_state, "terminal-failed")

    def test_readonly_query_drift_is_terminal_and_production_rejects_fake_port(self):
        plan, approval, registry, _machine, resolver = query_bundle(self.temp.name)
        observation = WorkspaceObservation(H, {"fingerprintHash": H})
        drift = WorkspaceObservation("identity-b", {"fingerprintHash": H})
        with self.assertRaisesRegex(RunnerError, "test-effect-port-rejected"):
            run_query(
                plan, approval=approval, effect_port=FakeEffectPort(),
                observer=Observer(observation, observation), now=NOW,
                returned_files=[], index_revision="r1", index_completeness="complete",
                trusted_command_registry=registry, authorization_resolver=resolver,
                replay_store=FakeReplayStore(), test_mode=False,
            )
        with self.assertRaises(RunnerError) as raised:
            run_query(
                plan, approval=approval, effect_port=FakeEffectPort(),
                observer=Observer(observation, drift), now=NOW,
                returned_files=[], index_revision="r1", index_completeness="complete",
                trusted_command_registry=registry, authorization_resolver=resolver,
                replay_store=FakeReplayStore(), test_mode=True,
            )
        self.assertEqual(raised.exception.reason, "workspace-drift-during-query")
        self.assertEqual(raised.exception.replay_state, "terminal-failed")

    def test_local_write_query_uses_authority_lease_guard_and_exact_evidence(self):
        plan, approval, registry, _machine, resolver = query_bundle(
            self.temp.name, side_effects="local-write",
            operation_id="sync-incremental", action="sync",
        )
        manager, lease = self.write_context(plan)
        observation = WorkspaceObservation(H, {"fingerprintHash": H})
        execution = run_query(
            plan, approval=approval,
            effect_port=FakeEffectPort(mutation_evidence=(evidence_for(plan),)),
            observer=Observer(observation, observation), now=NOW,
            returned_files=[], index_revision="r1", index_completeness="complete",
            trusted_command_registry=registry, authorization_resolver=resolver,
            lease=lease, lease_manager=manager, replay_store=FakeReplayStore(),
            test_mode=True,
        )
        self.assertEqual(execution.receipt["actualSideEffects"], "none")
        self.assertEqual(execution.receipt["replayState"], "terminal-succeeded")
        self.assertEqual(len(execution.receipt["mutationEvidenceRefs"]), 1)


if __name__ == "__main__":
    unittest.main()
