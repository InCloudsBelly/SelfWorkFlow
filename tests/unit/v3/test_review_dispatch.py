import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from selfworkflow.v3.hashing import content_hash, hash_bytes


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
PLAN_HASH = "sha256:" + "f" * 64


def _summary():
    value = {
        "schemaVersion": 3,
        "summaryId": "phase-4-post-grill-review",
        "designHash": HASH_A,
        "reviewerPolicyHash": HASH_B,
        "objective": "Enforce an independent post-Grill Brainstorming review.",
        "scope": {"included": ["review dispatch", "review gate"], "excluded": ["provider execution"]},
        "constraints": ["fork_context must be false"],
        "assumptions": ["The Host can attest dispatch metadata."],
        "alternatives": [{"alternativeId": "fresh-subagent", "summary": "Use a fresh SubAgent.", "disposition": "selected"}],
        "risks": [{"riskId": "self-report-spoofing", "description": "A reviewer may self-report independence.", "mitigation": "Trust only Host observations."}],
        "acceptanceCriteria": [{"criterionId": "fresh-context", "description": "The reviewer receives no inherited context.", "evidenceExpectation": "A Host-observed dispatch receipt."}],
    }
    value["summaryHash"] = content_hash(value)
    return value


def _verified(summary=None, *, plan_hash=PLAN_HASH):
    from selfworkflow.v3.review_inputs import verify_review_inputs

    value = _summary() if summary is None else summary
    provenance = {
        "schemaVersion": 3,
        "summaryHash": value["summaryHash"], "designHash": value["designHash"],
        "reviewerPolicyHash": value["reviewerPolicyHash"],
        "planHash": plan_hash, "attemptRef": "attempt-designed",
        "sourceClasses": ["acceptance-criteria", "confirmed-design"],
        "sourceFields": [
            "acceptanceCriteria", "alternatives", "assumptions", "constraints",
            "objective", "risks", "scope.excluded", "scope.included",
        ],
        "grillTranscriptReceived": False, "grillReasoningReceived": False,
        "parentContextReceived": False,
        "issuedAt": "2026-08-09T11:59:00Z", "expiresAt": "2026-08-09T12:05:00Z",
        "nonce": "summary-provenance-1",
    }
    provenance["attestationHash"] = content_hash(provenance)
    completion = {
        "schemaVersion": 3, "moduleId": "design-grill-me",
        "triggerSource": "explicit-user-request", "grillStatus": "completed",
        "commonUnderstandingConfirmed": True, "confirmationSource": "user-confirmation",
        "designHash": value["designHash"], "summaryHash": value["summaryHash"],
        "planHash": plan_hash, "attemptRef": "attempt-designed",
        "issuedAt": "2026-08-09T11:59:00Z", "expiresAt": "2026-08-09T12:05:00Z",
        "nonce": "grill-completion-1",
    }
    completion["attestationHash"] = content_hash(completion)
    return verify_review_inputs(
        value,
        summary_attestation_resolver=lambda ref: provenance if ref == value["summaryHash"] else None,
        grill_completion_ref=completion["attestationHash"],
        grill_completion_resolver=lambda ref: completion if ref == completion["attestationHash"] else None,
        reviewer_policy_hash=value["reviewerPolicyHash"], plan_hash=plan_hash,
        attempt_ref="attempt-designed",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )


def _result(summary, *, verdict="approve", findings=None):
    value = {
        "schemaVersion": 3,
        "verdict": verdict,
        "reviewLevel": "L2",
        "summaryHash": summary["summaryHash"],
        "designHash": summary["designHash"],
        "findings": findings or [],
    }
    value["resultHash"] = content_hash(value)
    return value


def _code_result(subject, *, verdict="approve", findings=None):
    value = {
        "schemaVersion": 3,
        "verdict": verdict,
        "reviewLevel": "L2",
        "reviewSubjectHash": content_hash(subject),
        "findings": findings or [],
    }
    value["resultHash"] = content_hash(value)
    return value


def _attestation(observation, implementation_agent, implementation_context):
    value = {
        "schemaVersion": 3,
        "dispatchId": observation["dispatchId"],
        "dispatchNonce": observation["dispatchNonce"],
        "planHash": observation["planHash"],
        "attemptRef": observation["attemptRef"],
        "issuedAt": observation["issuedAt"],
        "expiresAt": observation["expiresAt"],
        "reviewMode": observation["reviewMode"],
        "forkContext": observation["forkContext"],
        "payloadHash": content_hash(observation["payload"]),
        "implementationAgentIdentity": implementation_agent,
        "implementationContextIdentity": implementation_context,
        "hostAgentIdentity": "host-agent",
        "hostContextIdentity": "host-context",
        "reviewerAgentIdentity": observation["reviewerAgent"],
        "reviewerContextIdentity": observation["reviewerContext"],
        "resultHash": observation["result"]["resultHash"],
        "reviewModel": observation["reviewModel"],
        "reviewExecutionMode": observation["reviewExecutionMode"],
        "subagentLifecycle": observation["subagentLifecycle"],
        "subagentExecutionId": observation["subagentExecutionId"],
        "reviewReportHash": observation["reviewReportHash"],
        "skillManifestHash": observation["skillManifestHash"],
        "reviewPackageHash": observation["reviewPackageHash"],
    }
    value["attestationHash"] = content_hash(value)
    return value


class _SpyPort:
    def __init__(self, *, attested=True, same_identity=False, verdict="approve", tamper_attestation=False, unique_dispatches=False, lifecycle="created-executed-cleaned", execution_mode="ephemeral-subagent", report="# Review\n\nNo findings."):
        self.calls = []
        self.attested = attested
        self.same_identity = same_identity
        self.verdict = verdict
        self.tamper_attestation = tamper_attestation
        self.unique_dispatches = unique_dispatches
        self.lifecycle = lifecycle
        self.execution_mode = execution_mode
        self.report = report
        self.last_attestation = None
        self.issued_at = "2026-08-09T11:59:00Z"
        self.expires_at = "2026-08-09T12:05:00Z"

    def dispatch_review(self, **call):
        self.calls.append(call)
        from selfworkflow.v3.review_dispatch import HostDispatchObservation

        if call["review_mode"] == "independent-code-review":
            summary = call["payload"].get(
                "reviewPackage", call["payload"]["codeReviewSubject"]
            )
            result = _code_result(
                summary,
                verdict=self.verdict,
                findings=([{"findingId": "important-1", "severity": "important", "summary": "Fix the gate."}] if self.verdict == "changes-required" else []),
            )
        else:
            summary = call["payload"]["designReviewSummary"]
            result = _result(
                summary,
                verdict=self.verdict,
                findings=([{"findingId": "important-1", "severity": "important", "summary": "Fix the gate."}] if self.verdict == "changes-required" else []),
            )
        reviewer_agent = call["implementation_agent_identity"] if self.same_identity else "review-agent"
        reviewer_context = call["implementation_context_identity"] if self.same_identity else "review-context"
        ordinal = len(self.calls)
        dispatch_id = f"dispatch-{ordinal}" if self.unique_dispatches else "dispatch-1"
        dispatch_nonce = f"dispatch-nonce-{ordinal}" if self.unique_dispatches else "dispatch-nonce-1"
        if self.unique_dispatches and not self.same_identity:
            reviewer_agent = f"review-agent-{ordinal}"
            reviewer_context = f"review-context-{ordinal}"
        observed = {
            "dispatchId": dispatch_id, "reviewMode": call["review_mode"],
            "dispatchNonce": dispatch_nonce,
            "planHash": call["plan_hash"], "attemptRef": call["attempt_ref"],
            "issuedAt": self.issued_at, "expiresAt": self.expires_at,
            "forkContext": call["fork_context"], "payload": call["payload"],
            "reviewerAgent": reviewer_agent, "reviewerContext": reviewer_context,
            "result": result,
            "reviewModel": call.get("review_model"),
            "reviewExecutionMode": self.execution_mode,
            "subagentLifecycle": self.lifecycle,
            "subagentExecutionId": f"subagent-{ordinal}",
            "reviewReportHash": hash_bytes(self.report.encode("utf-8")),
            "skillManifestHash": content_hash({
                "schemaVersion": 1,
                "skills": (
                    call.get("payload", {}).get("projectReview", {}).get("skillManifest", [])
                    if isinstance(call.get("payload", {}).get("projectReview"), dict)
                    else [{
                        "layer": "generic",
                        "id": "selfworkflow.testing-review-quality",
                        "path": "skills/testing-review-quality/SKILL.md",
                        "contentHash": "sha256:f0955d06cbb43daaff947964700974e0f22bbd1338e62ae7a63514fa03a76c08",
                        "required": True,
                    }]
                ),
            }),
            "reviewPackageHash": call.get("payload", {}).get("reviewPackageHash"),
        }
        attestation = _attestation(
            observed, call["implementation_agent_identity"],
            call["implementation_context_identity"],
        ) if self.attested else None
        if attestation is not None and self.tamper_attestation:
            attestation["dispatchId"] = "replayed-dispatch"
            attestation["attestationHash"] = content_hash({key: value for key, value in attestation.items() if key != "attestationHash"})
        self.last_attestation = attestation
        return HostDispatchObservation(
            dispatch_id=dispatch_id, dispatch_nonce=dispatch_nonce,
            plan_hash=call["plan_hash"], attempt_ref=call["attempt_ref"],
            issued_at=self.issued_at, expires_at=self.expires_at,
            review_mode=call["review_mode"],
            fork_context=call["fork_context"], sent_payload=call["payload"],
            host_agent_identity="host-agent", host_context_identity="host-context",
            reviewer_agent_identity=reviewer_agent,
            reviewer_context_identity=reviewer_context,
            host_attestation=attestation, returned_value=result,
            project_review_context=call.get("project_review_context"),
            review_model=call.get("review_model"),
            review_execution_mode=self.execution_mode,
            subagent_lifecycle=self.lifecycle,
            subagent_execution_id=f"subagent-{ordinal}",
            review_report_markdown=self.report,
        )


class _IgnoringReviewModelPort(_SpyPort):
    def dispatch_review(self, **call):
        observation = super().dispatch_review(**call)
        object.__setattr__(observation, "review_model", None)
        return observation


class _DroppingReviewBoundaryPort(_SpyPort):
    def dispatch_review(self, **call):
        observation = super().dispatch_review(**call)
        payload = dict(observation.sent_payload)
        payload.pop("reviewExecutionBoundary", None)
        object.__setattr__(observation, "sent_payload", payload)
        return observation


class ReviewDispatchTests(unittest.TestCase):
    def test_dispatch_returns_bounded_report_and_ephemeral_lifecycle(self):
        from selfworkflow.v3.review_dispatch import dispatch_independent_review

        receipt = dispatch_independent_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=_SpyPort(),
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
        )
        self.assertEqual(receipt["reviewExecutionMode"], "ephemeral-subagent")
        self.assertEqual(receipt["subagentLifecycle"], "created-executed-cleaned")
        self.assertEqual(receipt["reviewReportMarkdown"], "# Review\n\nNo findings.")
        self.assertRegex(receipt["reviewReportHash"], r"^sha256:[0-9a-f]{64}$")

    def test_dispatch_rejects_non_ephemeral_review_execution(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        with self.assertRaisesRegex(ReviewDispatchError, "review-subagent-required"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=_SpyPort(execution_mode="current-dialog"),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_dispatch_rejects_cleanup_failure(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        with self.assertRaisesRegex(ReviewDispatchError, "review-subagent-cleanup-invalid"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=_SpyPort(lifecycle="created-executed-cleanup-failed"),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_dispatch_rejects_missing_review_report(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        with self.assertRaisesRegex(ReviewDispatchError, "review-report-invalid"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=_SpyPort(report=""), plan_hash=PLAN_HASH,
                attempt_ref="attempt-designed",
            )

    def test_dispatch_forces_fresh_context_and_summary_only_payload(self):
        from selfworkflow.v3.review_dispatch import dispatch_independent_review

        port = _SpyPort()
        receipt = dispatch_independent_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=port,
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
        )
        self.assertEqual(len(port.calls), 1)
        call = port.calls[0]
        self.assertEqual(call["review_mode"], "independent-design-review")
        self.assertIs(call["fork_context"], False)
        self.assertNotIn("review_model", call)
        self.assertEqual(
            set(call["payload"]),
            {"schemaVersion", "reviewMode", "reviewExecutionBoundary", "designReviewSummary"},
        )
        self.assertEqual(receipt["independence"], "independent")
        self.assertEqual(receipt["reviewVerdict"], "approve")
        self.assertFalse(receipt["parentContextImported"])

    def test_dispatch_binds_reviewer_capability_boundary(self):
        from selfworkflow.v3.review_dispatch import dispatch_independent_review

        port = _SpyPort()
        dispatch_independent_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=port,
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
        )

        boundary = port.calls[0]["payload"]["reviewExecutionBoundary"]
        self.assertEqual(boundary["role"], "reviewer")
        self.assertEqual(boundary["modelPolicy"], "inherit-parent")
        self.assertEqual(boundary["codeGraphPolicy"], "deny")
        self.assertEqual(
            boundary["allowedOperations"],
            ["read-review-package", "write-review-report"],
        )
        self.assertIn("codegraph.maintain", boundary["deniedOperations"])
        self.assertIn("codegraph.query", boundary["deniedOperations"])
        self.assertIn("workspace.write", boundary["deniedOperations"])

    def test_dispatch_rejects_host_that_drops_reviewer_boundary(self):
        from selfworkflow.v3.review_dispatch import (
            ReviewDispatchError, dispatch_independent_review,
        )

        with self.assertRaisesRegex(
            ReviewDispatchError, "review-execution-boundary-mismatch"
        ):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=_DroppingReviewBoundaryPort(), plan_hash=PLAN_HASH,
                attempt_ref="attempt-designed",
            )

    def test_dispatch_binds_valid_review_model_selection_to_host_payload(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        selection = {
            "agentId": "codex",
            "model": "gpt-5.6-sol",
            "reasoningEffort": "max",
            "selectionMode": "default",
        }
        port = _SpyPort()
        with self.assertRaisesRegex(ReviewDispatchError, "review-model-override-disabled"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=port,
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
                review_model=selection,
            )
        self.assertEqual(port.calls, [])

    def test_dispatch_rejects_unvalidated_review_model_selection(self):
        from selfworkflow.v3.review_dispatch import (
            ReviewDispatchError, dispatch_independent_review,
        )

        with self.assertRaisesRegex(ReviewDispatchError, "review-model-override-disabled"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=_SpyPort(),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
                review_model={
                    "agentId": "codex", "model": "gpt-5.6-sol",
                    "reasoningEffort": "Xmax", "selectionMode": "default",
                },
            )

    def test_dispatch_rejects_host_that_does_not_observe_selected_review_model(self):
        from selfworkflow.v3.review_dispatch import (
            ReviewDispatchError, dispatch_independent_review,
        )

        selection = {
            "agentId": "codex",
            "model": "gpt-5.6-sol",
            "reasoningEffort": "max",
            "selectionMode": "default",
        }
        with self.assertRaisesRegex(
            ReviewDispatchError, "review-model-override-disabled"
        ):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=_IgnoringReviewModelPort(), plan_hash=PLAN_HASH,
                attempt_ref="attempt-designed", review_model=selection,
            )

    def test_dispatch_passes_the_same_project_review_inputs_to_the_host_port(self):
        from selfworkflow.project_review import build_code_review_context, load_project_review_profile
        from selfworkflow.v3.review_dispatch import dispatch_independent_review

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "review.md").write_text("project review", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            digest = "sha256:" + hashlib.sha256(b"project review").hexdigest()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "additionalReviewSkills": [{
                        "id": "project.review", "path": "review.md",
                        "contentHash": digest, "required": True,
                    }],
                }), encoding="utf-8"
            )
            profile = load_project_review_profile(root)
        context = build_code_review_context(
            profile, strength="Deep", is_code_task=True, conversation_id="review-context"
        )
        port = _SpyPort()
        dispatch_independent_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=port,
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            project_review_context=context,
        )

        call = port.calls[0]
        self.assertIn("projectReview", call["payload"])
        self.assertEqual(
            call["payload"]["projectReview"]["skillPrecedence"],
            "project-override",
        )
        self.assertEqual(
            call["payload"]["projectReview"]["primarySkillIds"],
            ["project.review"],
        )
        self.assertEqual(
            call["payload"]["projectReview"]["supplementarySkillIds"],
            ["selfworkflow.testing-review-quality"],
        )
        self.assertEqual(call["project_review_context"], context)
        self.assertEqual(
            call["project_review_context"]["reviewers"]["standards"],
            call["project_review_context"]["reviewers"]["spec"],
        )

    def test_required_unverified_project_review_context_is_fail_closed(self):
        from selfworkflow.project_review import build_code_review_context, load_project_review_profile
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".selfworkflow").mkdir()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "additionalReviewSkills": [{
                        "id": "project.required", "path": "missing.md",
                        "contentHash": "sha256:" + "0" * 64, "required": True,
                    }],
                }), encoding="utf-8"
            )
            context = build_code_review_context(
                load_project_review_profile(root), strength="Full",
                is_code_task=True, conversation_id="blocked-review",
            )
        with self.assertRaisesRegex(ReviewDispatchError, "project-review-required-unverified"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=_SpyPort(),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
                project_review_context=context,
            )

    def test_project_review_context_length_mismatch_has_stable_error(self):
        from selfworkflow.project_review import build_code_review_context, load_project_review_profile
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "review.md"
            skill.write_text("project review", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            digest = "sha256:" + hashlib.sha256(b"project review").hexdigest()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "additionalReviewSkills": [{
                        "id": "project.review", "path": "review.md",
                        "contentHash": digest, "required": True,
                    }],
                }), encoding="utf-8"
            )
            context = build_code_review_context(
                load_project_review_profile(root), strength="Full",
                is_code_task=True, conversation_id="length-mismatch",
            )
        reviewers = dict(context["reviewers"])
        standards = dict(reviewers["standards"])
        standards["skillBytes"] = standards["skillBytes"] + (b"extra",)
        reviewers["standards"] = standards
        invalid = dict(context)
        invalid["reviewers"] = reviewers
        with self.assertRaisesRegex(ReviewDispatchError, "project-review-context-invalid"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=_SpyPort(),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
                project_review_context=invalid,
            )

    def test_project_review_context_manifest_metadata_is_strictly_validated(self):
        from selfworkflow.project_review import build_code_review_context, load_project_review_profile
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "review.md"
            skill.write_text("project review", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            digest = "sha256:" + hashlib.sha256(b"project review").hexdigest()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "additionalReviewSkills": [{
                        "id": "project.review", "path": "review.md",
                        "contentHash": digest, "required": True,
                    }],
                }), encoding="utf-8"
            )
            context = build_code_review_context(
                load_project_review_profile(root), strength="Full",
                is_code_task=True, conversation_id="metadata-validation",
            )
        reviewers = dict(context["reviewers"])
        standards = dict(reviewers["standards"])
        manifest = [dict(item) for item in standards["manifest"]]
        manifest[0]["path"] = "../escape.md"
        standards["manifest"] = tuple(manifest)
        reviewers["standards"] = standards
        invalid = dict(context)
        invalid["reviewers"] = reviewers
        with self.assertRaisesRegex(ReviewDispatchError, "project-review-context-invalid"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=_SpyPort(),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
                project_review_context=invalid,
            )

    def test_combined_code_review_runs_one_dispatch_covering_both_axes(self):
        from selfworkflow.project_review import build_code_review_context, load_project_review_profile
        from selfworkflow.v3.review_dispatch import dispatch_code_review

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "review.md"
            skill.write_text("project review", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            digest = "sha256:" + hashlib.sha256(b"project review").hexdigest()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "additionalReviewSkills": [{
                        "id": "project.review", "path": "review.md",
                        "contentHash": digest, "required": True,
                    }],
                }), encoding="utf-8"
            )
            context = build_code_review_context(
                load_project_review_profile(root), strength="Full",
                is_code_task=True, conversation_id="dual-review",
            )
        port = _SpyPort(unique_dispatches=True)
        result = dispatch_code_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=port,
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            project_review_context=context,
        )
        self.assertEqual(len(port.calls), 1)
        self.assertEqual(
            [call["review_mode"] for call in port.calls],
            ["independent-code-review"],
        )
        self.assertEqual(
            [call["payload"]["reviewAxis"] for call in port.calls],
            ["combined"],
        )
        self.assertTrue(all("codeReviewSubject" in call["payload"] for call in port.calls))
        self.assertEqual(port.calls[0]["payload"]["reviewAxes"], ["standards", "spec"])
        self.assertEqual(result["projectReviewHash"], content_hash(
            port.calls[0]["payload"]["projectReview"]
        ))
        self.assertEqual(set(result["reviewers"]), {"combined"})
        self.assertEqual(
            result["reviewers"]["combined"]["reviewMode"],
            "independent-code-review",
        )

    def test_dual_code_review_rejects_unattested_or_non_approving_axis(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_code_review

        with self.assertRaisesRegex(ReviewDispatchError, "review-code-review-gate-failed"):
            dispatch_code_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=_SpyPort(attested=False, unique_dispatches=True),
                plan_hash=PLAN_HASH, attempt_ref="attempt-reviewed",
            )

    def test_agent_self_report_fields_are_rejected_and_host_identity_wins(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        class SelfReportingPort(_SpyPort):
            def dispatch_review(self, **call):
                observation = super().dispatch_review(**call)
                value = copy.deepcopy(observation.returned_value)
                value["agentInstanceId"] = "implementation-agent"
                return observation.__class__(
                    **{**observation.__dict__, "returned_value": value}
                )

        with self.assertRaisesRegex(ReviewDispatchError, "review-result-invalid"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=SelfReportingPort(),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_attestation_is_bound_to_actual_dispatch_payload_identities_and_result(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        with self.assertRaisesRegex(ReviewDispatchError, "review-host-attestation"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=_SpyPort(tamper_attestation=True),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_missing_attestation_or_same_host_identity_cannot_claim_independence(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        receipt = dispatch_independent_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=_SpyPort(attested=False),
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
        )
        self.assertEqual(receipt["independence"], "unverified")
        with self.assertRaisesRegex(ReviewDispatchError, "review-identity-not-independent"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=_SpyPort(same_identity=True),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_changes_required_is_preserved_and_unverified_summary_is_rejected(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        receipt = dispatch_independent_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=_SpyPort(verdict="changes-required"),
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
        )
        self.assertEqual(receipt["reviewVerdict"], "changes-required")
        with self.assertRaisesRegex(ReviewDispatchError, "post-grill-review-input-invalid"):
            dispatch_independent_review(
                _summary(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=_SpyPort(),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_duplicate_semantic_ids_are_rejected(self):
        from selfworkflow.v3.review_inputs import ReviewInputError

        duplicate = _summary()
        duplicate["risks"].append({**duplicate["risks"][0], "description": "different"})
        duplicate["summaryHash"] = content_hash({key: value for key, value in duplicate.items() if key != "summaryHash"})
        with self.assertRaisesRegex(ReviewInputError, "post-grill-review-input-invalid"):
            _verified(duplicate)


if __name__ == "__main__":
    unittest.main()
