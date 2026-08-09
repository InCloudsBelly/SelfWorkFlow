import copy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import traceback
import unittest

from jsonschema import Draft202012Validator
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OWNER_NOW = datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc)


def _protected_document():
    return yaml.safe_load(
        (REPOSITORY_ROOT / "workflow/protected-rules.yaml").read_text(
            encoding="utf-8"
        )
    )


def _open_object_schema_paths(value):
    paths = []

    def visit(node, path):
        if isinstance(node, dict):
            if node.get("type") == "object":
                properties = node.get("properties", {})
                required = node.get("required", [])
                if node.get("additionalProperties") is not False or set(required) != set(
                    properties
                ):
                    paths.append(path)
            for key, item in node.items():
                visit(item, f"{path}/{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, f"{path}/{index}")

    visit(value, "$")
    return paths


def _put(store, artifact):
    from selfworkflow.evidence import canonical_content_hash

    artifact_hash = canonical_content_hash(artifact)
    store[artifact_hash] = artifact
    return artifact_hash


def _owner_invocation(**overrides):
    from selfworkflow.evidence import ExecutionInvocation

    values = {
        "executable": "powershell",
        "module": None,
        "argv": ("-File", "scripts/test.ps1", "-Test", "protected-rules"),
        "cwd": ".",
        "environment": {},
        "input_hash": "sha256:" + "0" * 64,
    }
    return ExecutionInvocation(**(values | overrides))


def _invocation_envelope(invocation):
    return dict(invocation.envelope)


def _trusted_owner_store(records, *, behavioral_invocation=None):
    from selfworkflow.evidence import ArtifactCollector, ExecutionInvocation

    collector = ArtifactCollector()
    for artifact in records.values():
        attributes = artifact["attributes"]
        if artifact["kind"] in {"owner-confirmation", "owner-review"}:
            collector.record_attestation(
                kind=artifact["kind"],
                subject_id=artifact["subjectId"],
                subject_hash=artifact["subjectHash"],
                actor_id=artifact["actorId"],
                context_id=artifact["contextId"],
                recorded_at=artifact["recordedAt"],
                provider=attributes["provider"],
                receipt_id=attributes["receiptId"],
                output_content={
                    "decision": attributes["decision"],
                    **(
                        {"level": attributes["level"]}
                        if "level" in attributes
                        else {"scope": attributes["scope"]}
                    ),
                },
                decision=attributes["decision"],
                level=attributes.get("level", ""),
                implementation_actor=attributes.get("implementationActor", ""),
                implementation_context=attributes.get("implementationContext", ""),
                scope=attributes.get("scope", ""),
            )
        elif artifact["kind"] == "behavioral-test":
            envelope = attributes["invocation"]
            invocation = behavioral_invocation or ExecutionInvocation(
                executable=envelope["executable"],
                module=envelope["module"],
                argv=tuple(envelope["argv"]),
                cwd=envelope["cwd"],
                environment={},
                input_hash=envelope["inputHash"],
            )
            collector.record_execution(
                kind="behavioral-test",
                status=artifact["status"],
                subject_id=artifact["subjectId"],
                subject_hash=artifact["subjectHash"],
                actor_id=artifact["actorId"],
                context_id=artifact["contextId"],
                related_ids=tuple(artifact["relatedIds"]),
                recorded_at=artifact["recordedAt"],
                provider=attributes["provider"],
                receipt_id=attributes["receiptId"],
                invocation=invocation,
                output_content={"status": artifact["status"]},
                check_type=attributes["checkType"],
                exit_code=attributes["exitCode"],
                suite=attributes["suite"],
            )
        else:
            raise AssertionError("unexpected owner artifact kind")
    return collector.seal()


def _owner_case(
    proposed_rules=None,
    *,
    new_version="3.0.0",
    review_level="L2",
    operation_nonce="owner-operation-1",
    proposed_at="2026-08-08T07:30:00Z",
    valid_for_seconds=7200,
    behavioral_invocation_overrides=None,
):
    from selfworkflow.evidence import (
        OwnerChangeRequest,
        canonical_content_hash,
        owner_change_proposal_hash,
        owner_pre_test_subject_hash,
    )

    protected = _protected_document()
    proposed = copy.deepcopy(protected["rules"] if proposed_rules is None else proposed_rules)
    base_hash = canonical_content_hash(protected["rules"])
    proposed_hash = canonical_content_hash(proposed)
    pre_test_subject_hash = owner_pre_test_subject_hash(
        base_rules_hash=base_hash,
        proposed_rules_hash=proposed_hash,
        previous_version=protected["policyVersion"],
        new_version=new_version,
        operation_nonce=operation_nonce,
        proposed_at=datetime.strptime(proposed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        ),
        valid_for_seconds=valid_for_seconds,
    )
    invocation = _owner_invocation(
        input_hash=pre_test_subject_hash,
        **(behavioral_invocation_overrides or {}),
    )
    proposal_hash = owner_change_proposal_hash(
        base_rules_hash=base_hash,
        proposed_rules_hash=proposed_hash,
        previous_version=protected["policyVersion"],
        new_version=new_version,
        operation_nonce=operation_nonce,
        proposed_at=datetime.strptime(proposed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        ),
        valid_for_seconds=valid_for_seconds,
        behavioral_test_invocation_hash=invocation.invocation_hash,
    )
    store = {}
    confirmation = {
        "kind": "owner-confirmation",
        "status": "passed",
        "subjectId": "protected-rules-change",
        "subjectHash": proposal_hash,
        "actorId": "repository-owner",
        "contextId": "owner-change-task",
        "relatedIds": [],
        "recordedAt": "2026-08-08T08:00:00Z",
        "attributes": {
            "provider": "owner-confirmation-provider",
            "receiptId": "owner-confirmation-1",
            "inputHash": proposal_hash,
            "outputHash": canonical_content_hash(
                {
                    "decision": "authorized",
                    "scope": "replace-protected-rules",
                }
            ),
            "decision": "authorized",
            "scope": "replace-protected-rules",
        },
    }
    review = {
        "kind": "owner-review",
        "status": "passed",
        "subjectId": "protected-rules-change",
        "subjectHash": proposal_hash,
        "actorId": "independent-reviewer",
        "contextId": "independent-review-task",
        "relatedIds": [],
        "recordedAt": "2026-08-08T08:00:00Z",
        "attributes": {
            "provider": "owner-review-provider",
            "receiptId": "owner-review-1",
            "inputHash": proposal_hash,
            "outputHash": canonical_content_hash(
                {"decision": "passed", "level": review_level}
            ),
            "decision": "passed",
            "level": review_level,
            "implementationActor": "implementer",
            "implementationContext": "task-3",
        },
    }
    tests = {
        "kind": "behavioral-test",
        "status": "passed",
        "subjectId": "protected-rules-change",
        "subjectHash": proposal_hash,
        "actorId": "test-runner",
        "contextId": "behavioral-test-run",
        "relatedIds": [],
        "recordedAt": "2026-08-08T08:00:00Z",
        "attributes": {
            "provider": "behavioral-test-provider",
            "receiptId": "behavioral-test-1",
            "inputHash": proposal_hash,
            "outputHash": canonical_content_hash({"status": "passed"}),
            "invocation": _invocation_envelope(invocation),
            "invocationHash": invocation.invocation_hash,
            "checkType": "behavioral-test",
            "exitCode": 0,
            "suite": "protected-rules",
        },
    }
    request = OwnerChangeRequest(
        base_rules_hash=base_hash,
        proposed_rules_hash=proposed_hash,
        previous_version=protected["policyVersion"],
        new_version=new_version,
        owner_actor="repository-owner",
        implementation_actor="implementer",
        implementation_context="task-3",
        operation_nonce=operation_nonce,
        proposed_at=datetime.strptime(proposed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        ),
        valid_for_seconds=valid_for_seconds,
        behavioral_test_invocation_hash=invocation.invocation_hash,
        confirmation_artifact_hash=_put(store, confirmation),
        review_artifact_hash=_put(store, review),
        behavioral_test_artifact_hash=_put(store, tests),
    )
    return protected, proposed, request, store


class ProtectedRulesTests(unittest.TestCase):
    def test_owner_change_request_rejects_oversized_direct_text(self):
        from selfworkflow.evidence import OwnerChangeRequest, WorkflowEvidenceError

        _, _, request, _ = _owner_case([])
        values = {
            field: getattr(request, field) for field in request.__dataclass_fields__
        }
        for field in ("owner_actor", "implementation_context", "operation_nonce"):
            with self.subTest(field=field):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    OwnerChangeRequest(**(values | {field: "x" * (2 * 1024 * 1024)}))
                self.assertEqual(
                    caught.exception.code,
                    "protected-rule-owner-authorization-required",
                )

    def test_owner_behavioral_invocation_input_binds_pretest_subject(self):
        protected, proposed, request, records = _owner_case([])
        del protected, proposed

        behavioral = records[request.behavioral_test_artifact_hash]
        self.assertRegex(
            request.pre_test_subject_hash,
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(
            behavioral["attributes"]["invocation"]["inputHash"],
            request.pre_test_subject_hash,
        )

    def test_owner_gate_rejects_behavioral_invocation_for_wrong_pretest_subject(self):
        from selfworkflow.evidence import (
            OwnerChangeRequest,
            WorkflowEvidenceError,
            merge_protected_rules,
        )

        protected, proposed, request, records = _owner_case([])
        wrong_invocation = _owner_invocation(input_hash="sha256:" + "f" * 64)
        behavioral = records.pop(request.behavioral_test_artifact_hash)
        behavioral["attributes"]["invocation"] = _invocation_envelope(
            wrong_invocation
        )
        behavioral["attributes"]["invocationHash"] = wrong_invocation.invocation_hash
        behavioral_hash = _put(records, behavioral)
        values = {
            field: getattr(request, field) for field in request.__dataclass_fields__
        }
        candidate = OwnerChangeRequest(
            **(
                values
                | {
                    "behavioral_test_invocation_hash": wrong_invocation.invocation_hash,
                    "behavioral_test_artifact_hash": behavioral_hash,
                }
            )
        )

        with self.assertRaises(WorkflowEvidenceError) as raised:
            merge_protected_rules(
                protected,
                owner_rules=proposed,
                owner_change=candidate,
                artifact_store=_trusted_owner_store(
                    records, behavioral_invocation=wrong_invocation
                ),
                now=OWNER_NOW,
            )
        self.assertEqual(
            raised.exception.code,
            "protected-rule-owner-authorization-required",
        )

    def test_owner_confirmation_and_review_cannot_replay_for_new_invocation(self):
        from selfworkflow.evidence import (
            OwnerChangeRequest,
            WorkflowEvidenceError,
            merge_protected_rules,
        )

        protected, proposed, old_request, old_records = _owner_case([])
        _, _, fresh_request, fresh_records = _owner_case(
            [],
            behavioral_invocation_overrides={
                "argv": (
                    "-File",
                    "scripts/test.ps1",
                    "-Test",
                    "protected-rules",
                    "--isolated",
                )
            },
        )
        records = {
            old_request.confirmation_artifact_hash: old_records[
                old_request.confirmation_artifact_hash
            ],
            old_request.review_artifact_hash: old_records[
                old_request.review_artifact_hash
            ],
            fresh_request.behavioral_test_artifact_hash: fresh_records[
                fresh_request.behavioral_test_artifact_hash
            ],
        }
        values = {
            field: getattr(fresh_request, field)
            for field in fresh_request.__dataclass_fields__
        }
        replay = OwnerChangeRequest(
            **(
                values
                | {
                    "confirmation_artifact_hash": old_request.confirmation_artifact_hash,
                    "review_artifact_hash": old_request.review_artifact_hash,
                }
            )
        )

        with self.assertRaises(WorkflowEvidenceError) as raised:
            merge_protected_rules(
                protected,
                owner_rules=proposed,
                owner_change=replay,
                artifact_store=_trusted_owner_store(records),
                now=OWNER_NOW,
            )
        self.assertEqual(
            raised.exception.code,
            "protected-rule-owner-authorization-required",
        )

    def test_owner_nonce_and_trusted_timeline_block_replay_future_and_stale_receipts(self):
        from selfworkflow.evidence import (
            OwnerChangeRequest,
            WorkflowEvidenceError,
            merge_protected_rules,
        )

        protected, proposed, request, records = _owner_case([])
        merged = merge_protected_rules(
            protected,
            owner_rules=proposed,
            owner_change=request,
            artifact_store=_trusted_owner_store(records),
            now=OWNER_NOW,
        )
        self.assertEqual(merged.policy_version, "3.0.0")

        values = {
            field: getattr(request, field) for field in request.__dataclass_fields__
        }
        replay = OwnerChangeRequest(**(values | {"operation_nonce": "other-operation"}))
        for label, candidate, observation in (
            ("nonce", replay, OWNER_NOW),
            (
                "future-proposal",
                _owner_case([], proposed_at="2026-08-08T08:31:00Z")[2],
                OWNER_NOW,
            ),
            (
                "stale-proposal",
                request,
                datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            ),
        ):
            with self.subTest(label=label):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    merge_protected_rules(
                        protected,
                        owner_rules=proposed,
                        owner_change=candidate,
                        artifact_store=_trusted_owner_store(records),
                        now=observation,
                    )
                self.assertEqual(
                    caught.exception.code,
                    "protected-rule-owner-authorization-required",
                )

    def test_owner_review_accepts_l3_through_the_shared_level_order(self):
        from selfworkflow.evidence import merge_protected_rules

        protected, proposed, request, records = _owner_case([], review_level="L3")
        merged = merge_protected_rules(
            protected,
            owner_rules=proposed,
            owner_change=request,
            artifact_store=_trusted_owner_store(records),
            now=OWNER_NOW,
        )
        self.assertEqual(merged.policy_version, "3.0.0")

    def test_cross_layer_duplicate_constraint_ids_are_rejected_not_downgraded(self):
        from selfworkflow.evidence import WorkflowEvidenceError, merge_protected_rules

        protected = _protected_document()
        layers = [
            {
                "contractVersion": 1,
                "kind": "skill",
                "name": "strong-review",
                "operations": [
                    {
                        "operation": "add-requirement",
                        "id": "review-floor",
                        "constraint": {
                            "kind": "review-level",
                            "target": "completion-review",
                            "mode": "at-least",
                            "value": "L2",
                        },
                    }
                ],
            },
            {
                "contractVersion": 1,
                "kind": "overlay",
                "name": "weak-review",
                "operations": [
                    {
                        "operation": "add-requirement",
                        "id": "review-floor",
                        "constraint": {
                            "kind": "review-level",
                            "target": "completion-review",
                            "mode": "at-least",
                            "value": "L0",
                        },
                    }
                ],
            },
        ]
        with self.assertRaises(WorkflowEvidenceError) as caught:
            merge_protected_rules(protected, layers)
        self.assertEqual(caught.exception.code, "protected-rule-layer-conflict")

    def test_checked_in_contract_is_closed_and_exact(self):
        protected = _protected_document()
        schema = json.loads(
            (REPOSITORY_ROOT / "schemas/protected-rules.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(protected)
        self.assertEqual(_open_object_schema_paths(schema), [])
        self.assertEqual(protected["policyVersion"], "2.0.0")
        self.assertEqual(protected["ordinaryLayerContractVersion"], 1)
        self.assertEqual(
            protected["ownerModificationGate"],
            {
                "versionChange": "semver-major",
                "confirmationArtifactKind": "owner-confirmation",
                "reviewArtifactKind": "owner-review",
                "behavioralTestArtifactKind": "behavioral-test",
            },
        )
        self.assertEqual(
            tuple(rule["id"] for rule in protected["rules"]),
            (
                "truthful-capability-review-verification",
                "no-silent-degradation",
                "protect-credentials-and-sensitive-data",
                "authorize-side-effects-and-irreversible-actions",
                "protect-user-existing-changes",
                "require-fresh-verification-before-completion",
                "require-independent-post-grill-brainstorming-review",
            ),
        )
        self.assertNotIn(
            "require-independent-post-grill-brainstorm-review",
            tuple(rule["id"] for rule in protected["rules"]),
        )

    def test_checked_in_v2_transition_has_formal_owner_evidence(self):
        from selfworkflow.evidence import (
            ExecutionInvocation,
            OwnerChangeRequest,
            canonical_content_hash,
            merge_protected_rules,
        )

        protected = _protected_document()
        base = copy.deepcopy(protected)
        base["policyVersion"] = "1.0.0"
        base["rules"] = base["rules"][:-1]
        evidence_root = (
            REPOSITORY_ROOT / "docs/releases/evidence/protected-rules-v2"
        )
        records = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in evidence_root.glob("*.json")
        }
        self.assertEqual(
            set(records), {"owner-confirmation", "owner-review", "behavioral-test"}
        )
        invocation_envelope = records["behavioral-test"]["attributes"]["invocation"]
        invocation = ExecutionInvocation(
            executable=invocation_envelope["executable"],
            module=invocation_envelope["module"],
            argv=tuple(invocation_envelope["argv"]),
            cwd=invocation_envelope["cwd"],
            environment={},
            input_hash=invocation_envelope["inputHash"],
        )
        request = OwnerChangeRequest(
            base_rules_hash="sha256:7db00fc634f74a995e4397cd44f96c9ec4c2939a930b36e40c13d245f9ed91c2",
            proposed_rules_hash="sha256:370c575231a746c6df81b7b2e811d054e7ec6ca4712b3554d56b49c7881f1c5c",
            previous_version="1.0.0",
            new_version="2.0.0",
            owner_actor="repository-owner-user",
            implementation_actor="codex-implementation-agent",
            implementation_context="selfworkflow-v3-task",
            operation_nonce="protected-rules-v2-operation-1",
            proposed_at=datetime(2026, 8, 9, 1, 15, tzinfo=timezone.utc),
            valid_for_seconds=7200,
            behavioral_test_invocation_hash=invocation.invocation_hash,
            confirmation_artifact_hash=canonical_content_hash(records["owner-confirmation"]),
            review_artifact_hash=canonical_content_hash(records["owner-review"]),
            behavioral_test_artifact_hash=canonical_content_hash(records["behavioral-test"]),
        )
        merged = merge_protected_rules(
            base,
            owner_rules=protected["rules"],
            owner_change=request,
            artifact_store=_trusted_owner_store(
                records, behavioral_invocation=invocation,
            ),
            now=datetime(2026, 8, 9, 1, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(merged.policy_version, "2.0.0")

    def test_lower_layers_have_only_monotonic_typed_operations(self):
        from selfworkflow.evidence import WorkflowEvidenceError, merge_protected_rules

        protected = _protected_document()
        misleading_id = "allow-silent-degradation"
        layers = [
            {
                "contractVersion": 1,
                "kind": "skill",
                "name": "negative-looking-skill",
                "operations": [
                    {
                        "operation": "advisory",
                        "id": misleading_id,
                        "constraint": {
                            "kind": "workflow-action",
                            "target": "documentation",
                            "mode": "recommend",
                            "value": "record",
                        },
                    }
                ],
            },
            {
                "contractVersion": 1,
                "kind": "project",
                "name": "project-requirements",
                "operations": [
                    {
                        "operation": "add-requirement",
                        "id": "project-tests",
                        "constraint": {
                            "kind": "verification-status",
                            "target": "project-tests",
                            "mode": "equals",
                            "value": "passed",
                        },
                    }
                ],
            },
        ]
        merged = merge_protected_rules(protected, layers)
        negative = merged.rule_for(misleading_id)
        self.assertEqual(negative.operation, "advisory")
        self.assertEqual(
            negative.constraint,
            ("workflow-action", "documentation", "recommend", "record"),
        )
        self.assertEqual(negative.statement, "")
        self.assertFalse(negative.protected)
        self.assertEqual(
            merge_protected_rules(protected, list(reversed(layers))),
            merged,
        )
        with self.assertRaises(FrozenInstanceError):
            negative.operation = "disable"

        for operation in ("disable", "replace", True):
            invalid = copy.deepcopy(layers[:1])
            invalid[0]["operations"][0]["operation"] = operation
            with self.subTest(operation=operation):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    merge_protected_rules(protected, invalid)
                self.assertEqual(caught.exception.code, "protected-rule-layer-invalid")

        for mutation in (
            lambda item: item.update({"statement": "free text has no authority"}),
            lambda item: item["constraint"].update({"kind": "disable-gate"}),
            lambda item: item["constraint"].update({"value": "skip"}),
        ):
            invalid = copy.deepcopy(layers[:1])
            mutation(invalid[0]["operations"][0])
            with self.subTest(invalid=invalid[0]["operations"][0]):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    merge_protected_rules(protected, invalid)
                self.assertEqual(caught.exception.code, "protected-rule-layer-invalid")

        override = copy.deepcopy(layers[:1])
        override[0]["operations"][0]["id"] = protected["rules"][0]["id"]
        with self.assertRaises(WorkflowEvidenceError) as caught:
            merge_protected_rules(protected, override)
        self.assertEqual(caught.exception.code, "protected-rule-override-denied")

        # A negative-looking ordinary ID cannot alter the fixed completion evaluator.
        from tests.unit.test_evidence import _case, _evaluate, _replace_artifact

        case = _case()
        capability = case["evidence"]["capabilities"][0]
        capability["state"] = "unsupported"
        _replace_artifact(
            case,
            capability,
            lambda artifact: artifact["attributes"].update(
                {"state": "unsupported"}
            ),
        )
        self.assertEqual(_evaluate(case).code, "required-capability-unsupported")

    def test_owner_delete_all_requires_real_hash_version_and_artifact_gates(self):
        from selfworkflow.evidence import WorkflowEvidenceError, merge_protected_rules

        protected, proposed, request, store = _owner_case([])
        self.assertEqual(proposed, [])
        with self.assertRaises(WorkflowEvidenceError) as caught:
            merge_protected_rules(protected, owner_rules=[])
        self.assertEqual(
            caught.exception.code,
            "protected-rule-owner-authorization-required",
        )
        with self.assertRaises(WorkflowEvidenceError) as caught:
            merge_protected_rules(
                protected,
                owner_rules=[],
                owner_change=request,
                artifact_store=store,
            )
        self.assertEqual(
            caught.exception.code,
            "protected-rule-owner-authorization-required",
        )

        merged = merge_protected_rules(
            protected,
            owner_rules=[],
            owner_change=request,
            artifact_store=_trusted_owner_store(store),
            now=OWNER_NOW,
        )
        self.assertEqual(merged.rules, ())
        self.assertEqual(merged.policy_version, "3.0.0")
        with self.assertRaises(FrozenInstanceError):
            request.new_version = "3.0.0"

    def test_owner_receipts_bind_the_full_versioned_proposal(self):
        from selfworkflow.evidence import (
            OwnerChangeRequest,
            WorkflowEvidenceError,
            merge_protected_rules,
        )

        protected, proposed, request, records = _owner_case([])
        self.assertEqual(
            merge_protected_rules(
                protected,
                owner_rules=proposed,
                owner_change=request,
                artifact_store=_trusted_owner_store(records),
                now=OWNER_NOW,
            ).policy_version,
            "3.0.0",
        )

        replayed_document = copy.deepcopy(protected)
        replayed_document["policyVersion"] = "5.0.0"
        values = {
            field: getattr(request, field)
            for field in request.__dataclass_fields__
        }
        replayed_request = OwnerChangeRequest(
            **(
                values
                | {"previous_version": "5.0.0", "new_version": "6.0.0"}
            )
        )
        with self.assertRaises(WorkflowEvidenceError) as caught:
            merge_protected_rules(
                replayed_document,
                owner_rules=proposed,
                owner_change=replayed_request,
                artifact_store=_trusted_owner_store(records),
            )
        self.assertEqual(
            caught.exception.code,
            "protected-rule-owner-authorization-required",
        )

    def test_owner_gate_recomputes_hashes_and_rejects_zero_or_nonmajor_claims(self):
        from selfworkflow.evidence import (
            OwnerChangeRequest,
            WorkflowEvidenceError,
            merge_protected_rules,
        )

        protected, proposed, valid, store = _owner_case([])
        values = {
            field: getattr(valid, field)
            for field in valid.__dataclass_fields__
        }
        class Text(str):
            pass

        with self.assertRaises(WorkflowEvidenceError) as caught:
            OwnerChangeRequest(**(values | {"owner_actor": Text("owner")}))
        self.assertEqual(
            caught.exception.code,
            "protected-rule-owner-authorization-required",
        )
        attacks = (
            {"base_rules_hash": "sha256:" + "0" * 64},
            {"proposed_rules_hash": "sha256:" + "0" * 64},
            {"new_version": "1.9.0"},
            {"new_version": "major"},
            {"confirmation_artifact_hash": "sha256:" + "0" * 64},
            {"review_artifact_hash": "sha256:" + "0" * 64},
            {"behavioral_test_artifact_hash": "sha256:" + "0" * 64},
        )
        for override in attacks:
            request = OwnerChangeRequest(**(values | override))
            with self.subTest(field=tuple(override)):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    merge_protected_rules(
                        protected,
                        owner_rules=proposed,
                        owner_change=request,
                        artifact_store=_trusted_owner_store(store),
                    )
                self.assertEqual(
                    caught.exception.code,
                    "protected-rule-owner-authorization-required",
                )

    def test_oversized_semver_components_fail_with_fixed_redacted_errors(self):
        from selfworkflow.evidence import WorkflowEvidenceError, merge_protected_rules

        oversized = "9" * 5000 + ".0.0"
        protected = _protected_document()
        protected["policyVersion"] = oversized
        with self.assertRaises(WorkflowEvidenceError) as caught:
            merge_protected_rules(protected)
        self.assertEqual(caught.exception.code, "protected-rules-invalid")
        self.assertEqual(caught.exception.message, "The protected-rule document is invalid.")
        self.assertNotIn(oversized, str(caught.exception))

        schema = json.loads(
            (REPOSITORY_ROOT / "schemas/protected-rules.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(Draft202012Validator(schema).is_valid(protected))

    def test_owner_artifacts_are_recomputed_bound_passed_and_independent(self):
        from selfworkflow.evidence import (
            OwnerChangeRequest,
            WorkflowEvidenceError,
            merge_protected_rules,
        )

        mutations = (
            lambda artifact: artifact.update({"status": "failed"}),
            lambda artifact: artifact.update({"subjectHash": "sha256:" + "0" * 64}),
            lambda artifact: artifact.update({"actorId": "implementer"}),
            lambda artifact: artifact.update({"contextId": "task-3"}),
        )
        for mutate, expected_code in (
            (
                lambda artifact: artifact.update({"actorId": "not-the-owner"}),
                "protected-rule-owner-authorization-required",
            ),
            (
                lambda artifact: artifact["attributes"].update(
                    {"scope": "all-files"}
                ),
                "artifact-collector-invalid",
            ),
        ):
            protected, proposed, request, store = _owner_case([])
            old_hash = request.confirmation_artifact_hash
            artifact = copy.deepcopy(store.pop(old_hash))
            mutate(artifact)
            new_hash = _put(store, artifact)
            values = {
                field: getattr(request, field)
                for field in request.__dataclass_fields__
            }
            request = OwnerChangeRequest(
                **(values | {"confirmation_artifact_hash": new_hash})
            )
            with self.assertRaises(WorkflowEvidenceError) as caught:
                merge_protected_rules(
                    protected,
                    owner_rules=proposed,
                    owner_change=request,
                    artifact_store=_trusted_owner_store(store),
                )
            self.assertEqual(
                caught.exception.code,
                expected_code,
            )

        for mutation_index, mutate in enumerate(mutations):
            protected, proposed, request, store = _owner_case([])
            review_hash = request.review_artifact_hash
            review = copy.deepcopy(store.pop(review_hash))
            mutate(review)
            new_hash = _put(store, review)
            values = {
                field: getattr(request, field)
                for field in request.__dataclass_fields__
            }
            request = OwnerChangeRequest(
                **(values | {"review_artifact_hash": new_hash})
            )
            with self.subTest(review=review):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    merge_protected_rules(
                        protected,
                        owner_rules=proposed,
                        owner_change=request,
                        artifact_store=_trusted_owner_store(store),
                    )
                self.assertEqual(
                    caught.exception.code,
                    "protected-rule-owner-authorization-required",
                )

        protected, proposed, request, store = _owner_case([])
        behavioral_hash = request.behavioral_test_artifact_hash
        behavioral = copy.deepcopy(store.pop(behavioral_hash))
        behavioral["status"] = "failed"
        behavioral["attributes"]["exitCode"] = 1
        new_hash = _put(store, behavioral)
        values = {
            field: getattr(request, field)
            for field in request.__dataclass_fields__
        }
        request = OwnerChangeRequest(
            **(values | {"behavioral_test_artifact_hash": new_hash})
        )
        with self.assertRaises(WorkflowEvidenceError) as caught:
            merge_protected_rules(
                protected,
                owner_rules=proposed,
                owner_change=request,
                artifact_store=_trusted_owner_store(store),
            )
        self.assertEqual(
            caught.exception.code,
            "protected-rule-owner-authorization-required",
        )

    def test_hostile_rule_and_owner_inputs_are_redacted(self):
        from selfworkflow.evidence import WorkflowEvidenceError, merge_protected_rules

        secret = "TOP-SECRET-HOSTILE-RULE-INPUT"

        class HostileMapping(dict):
            def items(self):
                raise RuntimeError(secret)

        protected = _protected_document()
        hostile = dict(protected)
        hostile["ownerModificationGate"] = HostileMapping()
        with self.assertRaises(WorkflowEvidenceError) as caught:
            merge_protected_rules(hostile)
        self.assertEqual(caught.exception.code, "protected-rules-invalid")
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))

    def test_workflow_document_states_the_current_enforcement_boundary(self):
        text = (REPOSITORY_ROOT / "workflow/core.md").read_text(encoding="utf-8")
        headings = tuple(
            line.strip() for line in text.splitlines() if line.startswith("## ")
        )
        self.assertEqual(
            headings,
            (
                "## 核心流程",
                "## 按需能力",
                "## 安全底线",
            ),
        )
        self.assertIn("不得虚构能力、Review 或测试结果", text)
        self.assertIn("不得静默降级", text)
        self.assertIn("`unverified`", text)
        forbidden = re.compile(
            r"\b(catalog|router|installer|mcp|openai|anthropic|codex|claude)\b",
            flags=re.IGNORECASE,
        )
        self.assertIsNone(forbidden.search(text))
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            self.assertTrue((REPOSITORY_ROOT / target).is_file(), target)


def _test_ids(suite):
    result = []
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            result.extend(_test_ids(test))
        else:
            result.append(test.id())
    return result


class AggregateTestEntryTests(unittest.TestCase):
    def test_registry_exactly_matches_unit_modules(self):
        import tests.unit as unit_package

        expected = tuple(
            f"tests.unit.{path.stem}"
            for path in sorted((REPOSITORY_ROOT / "tests/unit").glob("test_*.py"))
        )
        self.assertEqual(unit_package.UNIT_TEST_MODULES, expected)

    def test_explicit_modules_aggregate_and_discovery_are_equal_and_unique(self):
        import tests.unit as unit_package

        loader = unittest.TestLoader()
        explicit = unittest.TestSuite(
            loader.loadTestsFromName(name) for name in unit_package.UNIT_TEST_MODULES
        )
        aggregate = unit_package.load_tests(loader, unittest.TestSuite(), None)
        discovery = loader.discover(
            str(REPOSITORY_ROOT / "tests"),
            pattern="test*.py",
            top_level_dir=str(REPOSITORY_ROOT),
        )
        explicit_ids = _test_ids(explicit)
        aggregate_ids = _test_ids(aggregate)
        discovery_unit_ids = [
            test_id for test_id in _test_ids(discovery) if ".unit." in test_id
        ]
        self.assertEqual(len(explicit_ids), len(set(explicit_ids)))
        self.assertEqual(aggregate_ids, explicit_ids)
        self.assertEqual(discovery_unit_ids, explicit_ids)


if __name__ == "__main__":
    unittest.main()
