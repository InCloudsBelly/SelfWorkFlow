import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from selfworkflow.v3.hashing import content_hash, project_root_hash
from selfworkflow.v3.receipts import ReceiptError, build_mutation_evidence, validate_mutation_evidence
from selfworkflow.v3.contracts import ContractError, validate_provider_mutation_evidence


H = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


class MutationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root_hash = project_root_hash(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def target(self, kind, target_id, actions):
        mutation_hash = content_hash({
            "targetKind": kind, "targetId": target_id,
            "allowedActions": list(actions), "evidenceRequired": True,
        })
        return {
            "targetKind": kind,
            "targetId": target_id,
            "canonicalTargetHash": content_hash({"targetKind": kind, "targetId": target_id}),
            "mutationTargetHash": mutation_hash,
            "containmentRootHash": self.root_hash if kind in {"exact-file", "directory-subtree", "managed-state-root"} else content_hash({"targetKind": kind, "scope": target_id}),
            "recursion": "bounded" if kind in {"directory-subtree", "managed-state-root"} else "none",
            "reparsePolicy": "reject",
            "allowedActions": list(actions),
            "evidenceRequired": True,
        }

    def evidence(self, kind, target, actual_kind, target_id, action, *, provider="fake.provider", observed=NOW):
        before = [] if kind == "filesystem-manifest" else {"identityHash": H, "revision": "1"}
        after = ([{"path": target_id, "type": "file", "size": 1, "contentHash": H, "reparseIdentityHash": H}]
                 if kind == "filesystem-manifest" else {"identityHash": content_hash("after"), "revision": "2"})
        return build_mutation_evidence(
            subject_kind="operation-plan", subject_plan_hash=H,
            execution_nonce="nonce-a", attempt_ref="attempt-a",
            provider_binding_hash=H, project_root_hash=self.root_hash,
            provider_id=provider, started_at=NOW,
            completed_at=NOW + timedelta(seconds=1), observed_at=observed,
            pre_state_identity=H, post_state_identity=content_hash("after"),
            mutation_target_hash=target["mutationTargetHash"], evidence_kind=kind,
            before=before, after=after,
            actual_targets=({"targetKind": actual_kind, "targetId": target_id, "action": action},),
            declared_targets=(target,),
        )

    def validate(self, evidence, targets, **overrides):
        values = dict(
            subject_plan_hash=H, execution_nonce="nonce-a", attempt_ref="attempt-a",
            provider_id="fake.provider", provider_binding_hash=H,
            project_root_hash=self.root_hash,
            started_at=NOW, completed_at=NOW + timedelta(seconds=1),
            declared_targets=targets,
        )
        values.update(overrides)
        validate_mutation_evidence(evidence, **values)

    def test_four_kinds_are_bound_to_target_and_action(self):
        cases = (
            ("filesystem-manifest", self.target("directory-subtree", "managed", ("modify",)), "filesystem", "managed/index", "modify"),
            ("managed-state-manifest", self.target("managed-state-root", "index", ("sync",)), "managed-state", "index", "sync"),
            ("process-state-delta", self.target("process", "debuggee", ("mutate",)), "process", "debuggee", "mutate"),
            ("service-state-delta", self.target("service", "indexer", ("start",)), "service", "indexer", "start"),
        )
        for kind, target, actual_kind, target_id, action in cases:
            with self.subTest(kind=kind):
                evidence = self.evidence(kind, target, actual_kind, target_id, action)
                self.validate(evidence, (target,))

    def test_cross_provider_time_target_and_action_are_rejected(self):
        target = self.target("managed-state-root", "index", ("sync",))
        evidence = self.evidence("managed-state-manifest", target, "managed-state", "index", "sync")
        with self.assertRaisesRegex(ReceiptError, "provider-mismatch"):
            self.validate(evidence, (target,), provider_id="other.provider")
        with self.assertRaisesRegex(ReceiptError, "mutation-evidence-binding-mismatch"):
            self.validate(evidence, (target,), provider_binding_hash=content_hash("other-binding"))
        with self.assertRaisesRegex(ReceiptError, "time-window"):
            self.validate(evidence, (target,), completed_at=NOW + timedelta(seconds=2))
        other = self.target("managed-state-root", "other", ("sync",))
        with self.assertRaisesRegex(ReceiptError, "target-hash-mismatch"):
            self.validate(evidence, (other,))
        with self.assertRaisesRegex(ReceiptError, "out-of-bounds"):
            self.evidence("managed-state-manifest", target, "managed-state", "index", "repair")

    def test_cross_nonce_attempt_and_project_replay_are_rejected(self):
        target = self.target("managed-state-root", "index", ("sync",))
        evidence = self.evidence("managed-state-manifest", target, "managed-state", "index", "sync")
        with self.assertRaisesRegex(ReceiptError, "mutation-evidence-replay"):
            self.validate(evidence, (target,), execution_nonce="nonce-b")
        with self.assertRaisesRegex(ReceiptError, "mutation-evidence-replay"):
            self.validate(evidence, (target,), attempt_ref="attempt-b")
        with self.assertRaisesRegex(ReceiptError, "project-mismatch"):
            self.validate(evidence, (target,), project_root_hash=content_hash("other-root"))

    def test_unobservable_and_duplicate_are_closed(self):
        target = self.target("managed-state-root", "index", ("sync",))
        common = dict(
            subject_kind="operation-plan", subject_plan_hash=H,
            execution_nonce="nonce-a", attempt_ref="attempt-a",
            provider_binding_hash=H, project_root_hash=self.root_hash,
            provider_id="fake.provider", started_at=NOW,
            completed_at=NOW + timedelta(seconds=1), observed_at=NOW,
            pre_state_identity=H, post_state_identity=H,
            mutation_target_hash=target["mutationTargetHash"],
            evidence_kind="managed-state-manifest",
            before={"identityHash": H, "revision": "1"},
            after={"identityHash": H, "revision": "2"},
            actual_targets=({"targetKind": "managed-state", "targetId": "index", "action": "sync"},),
            declared_targets=(target,),
        )
        with self.assertRaisesRegex(ReceiptError, "required-mutation-unobservable"):
            build_mutation_evidence(**common, observable=False, required=True)
        duplicate = common["actual_targets"] * 2
        with self.assertRaisesRegex(ReceiptError, "mutation-evidence-duplicate"):
            build_mutation_evidence(**{**common, "actual_targets": duplicate})

    def test_serialized_evidence_hash_and_payload_are_recomputed(self):
        target = self.target("managed-state-root", "index", ("sync",))
        evidence = self.evidence("managed-state-manifest", target, "managed-state", "index", "sync")
        evidence["evidenceHash"] = H
        with self.assertRaises(ContractError):
            validate_provider_mutation_evidence(evidence)
        evidence = self.evidence("managed-state-manifest", target, "managed-state", "index", "sync")
        evidence["payloadHash"] = content_hash("wrong")
        evidence["evidenceHash"] = content_hash({key: value for key, value in evidence.items() if key != "evidenceHash"})
        with self.assertRaises(ContractError):
            validate_provider_mutation_evidence(evidence)


if __name__ == "__main__": unittest.main()
