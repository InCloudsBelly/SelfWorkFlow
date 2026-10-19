from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from selfworkflow.quality import (
    QualityGateError,
    _terminate_process_tree,
    build_review_package,
    capture_review_baseline,
    run_verification,
    validate_completion,
)
from selfworkflow.cli import main as cli_main


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr)


def _host_review(package, mode="Full", *, apply_review=True, stage_id="reviewed", attempt_ref="attempt-review", risk="R1", bounded_verify=False):
    """Conforming embedding-Host fixture; never used as real execution evidence."""
    from selfworkflow.v3.hashing import content_hash
    from selfworkflow.v3.host import Host
    from selfworkflow.v3.plan_graph import build_plan_graph
    from selfworkflow.v3.review_policy import load_post_grill_review_policy
    from selfworkflow.v3.review_services import bind_review_host_services
    from tests.unit.v3.artifact_fixtures import load_test_artifacts
    from tests.unit.v3.test_host_ledger import REQUEST, _module, HostLedgerTests
    from tests.unit.v3.test_post_grill_review_gate import _Consumer
    from tests.unit.v3.test_review_dispatch import _SpyPort, _verified

    modules = [{**_module("review-a"), "slot": "review.independent"}]
    if bounded_verify:
        modules.append({**_module("verify-fixture"), "stage": "verified", "slot": "verify.fixture", "selectionMode": "bounded-runtime"})
    catalog, pipeline = load_test_artifacts(
        modules,
        target_slot="review.independent", mode="static")
    request = copy.deepcopy(REQUEST)
    request.update(operationType="analyze", taskArchetype="mechanical-change",
        projectMinimums={"strength": mode}, complexity="C3" if mode == "Deep" else "C2",
        testLevelFloor="T3" if mode == "Deep" else "T2")
    request["risk"] = risk
    plan = build_plan_graph(request, catalog, pipeline)
    policy = load_post_grill_review_policy(Path(__file__).resolve().parents[2] / "workflow/v3/post-grill-review.yaml")
    port = _SpyPort(unique_dispatches=True)
    now = datetime.now(timezone.utc)
    port.issued_at = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    port.expires_at = (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    consumer = _Consumer()
    attestation = {
        "schemaVersion": 3, "backendClass": "external-host",
        "dispatchPortBound": True, "artifactResolversBound": True,
        "replayConsumersBound": True, "independentContextAvailable": True,
        "reviewExecutionMode": "ephemeral-subagent", "reviewPolicyHash": policy.policy_hash,
    }
    attestation["attestationHash"] = content_hash(attestation)
    services = bind_review_host_services(dispatch_port=port,
        summary_resolver=lambda _: None, summary_attestation_resolver=lambda _: None,
        grill_completion_resolver=lambda _: None,
        host_attestation_resolver=lambda ref: port.last_attestation if port.last_attestation and ref == port.last_attestation["attestationHash"] else None,
        host_attestation_consumer=consumer, fallback_authorization_resolver=lambda _: None,
        fallback_authorization_consumer=consumer, review_policy=policy, service_attestation=attestation)
    host = Host(plan, request, catalog, pipeline, review_services=services)
    ledger = HostLedgerTests()._advance_to_review(host, plan, host.new_ledger(), attempt_ref=attempt_ref)
    wrapper = {"schemaVersion": 1, "reviewKind": "code", "planHash": plan.plan_hash,
        "stageId": stage_id, "attemptRef": attempt_ref, "content": package}
    wrapper["packageHash"] = content_hash(wrapper)
    evidence = host.dispatch_code_review(_verified(plan_hash=plan.plan_hash),
        implementation_agent_identity="author", implementation_context_identity="author-context",
        attempt_ref=attempt_ref, review_package=wrapper, ledger=ledger)
    receipt = evidence["reviewers"]["combined"]
    artifacts = sorted([wrapper["packageHash"], receipt["receiptHash"]])
    result = {"schemaVersion": 3, "planHash": plan.plan_hash, "stageId": "reviewed",
        "attemptRef": attempt_ref, "capabilitySnapshotHash": plan["capabilitySnapshotHash"],
        "inputArtifactHashes": ledger["stages"][6]["attempts"][-1]["inputArtifactHashes"], "outputArtifactHashes": artifacts, "artifactHashes": artifacts,
        "slotResults": [{"slotId": "review.independent", "moduleId": "review-a", "artifactHash": receipt["receiptHash"]}],
        "gateResults": [], "runtimeSkips": [], "status": "passed", "completedAt": "2026-08-09T01:01:00Z"}
    result["artifactHashes"] = sorted(set(result["inputArtifactHashes"] + artifacts))
    if apply_review:
        ledger = host.apply_stage_result(ledger, result, code_review_evidence=evidence)
    return host, ledger, evidence, result


class QualityGateTests(unittest.TestCase):
    def test_completion_accepts_real_bounded_runtime_selection_receipts(self):
        from selfworkflow.v3.selector import SelectionInput, select_modules

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            package = build_review_package(root, baseline, self._spec(), [self._plan()])
            host, ledger, evidence, _ = _host_review(package, bounded_verify=True)
            signal, output = "sha256:" + "1" * 64, "sha256:" + "2" * 64
            ledger = host.start_stage(ledger, "verified", "attempt-verified", "2026-08-09T01:02:00Z",
                input_artifact_hashes=(signal,))
            selection = select_modules(host.plan, "verified", "verify.fixture", "attempt-verified",
                SelectionInput(artifact_id="verify-signal", artifact_hash=signal, preferred_module_ids=("verify-fixture",)))
            self.assertEqual(selection.status, "selected")
            self.assertEqual(selection.receipt.document["selectedModuleIds"], ["verify-fixture"])
            receipts = (selection.receipt,)
            ledger = host.apply_stage_result(ledger, {
                "schemaVersion": 3, "planHash": host.plan.plan_hash,
                "stageId": "verified", "attemptRef": "attempt-verified",
                "capabilitySnapshotHash": host.plan["capabilitySnapshotHash"],
                "inputArtifactHashes": [signal], "outputArtifactHashes": [output],
                "artifactHashes": sorted([signal, output]),
                "slotResults": [{"slotId": "verify.fixture", "moduleId": "verify-fixture", "artifactHash": output}],
                "selectionReceipts": [selection.receipt.as_dict()],
                "gateResults": [], "runtimeSkips": [], "status": "passed", "completedAt": "2026-08-09T01:03:00Z",
            })
            review = {"axis": "combined", "executionId": evidence["reviewers"]["combined"]["subagentExecutionId"],
                "attestation": "host_attested", "workflowMode": "Full", "packageHash": package["packageHash"], "findings": []}
            with self.assertRaisesRegex(QualityGateError, "quality-review-context-invalid"):
                validate_completion(root, baseline, self._spec(), package, [review], code_review_evidence=evidence,
                    review_host=host, review_ledger=ledger)
            self.assertEqual(validate_completion(root, baseline, self._spec(), package, [review],
                code_review_evidence=evidence, review_host=host, review_ledger=ledger, review_receipts=receipts)["status"], "complete")

    def test_completion_requires_current_host_service_plan_attempt_and_reviewed_ledger(self):
        from selfworkflow.v3.host import Host

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            package = build_review_package(root, baseline, self._spec(), [self._plan()])
            host, ledger, evidence, _ = _host_review(package)
            review = {"axis": "combined", "executionId": evidence["reviewers"]["combined"]["subagentExecutionId"],
                "attestation": "host_attested", "workflowMode": "Full", "packageHash": package["packageHash"], "findings": []}
            other_host, other_ledger, _, _ = _host_review(package, attempt_ref="other-attempt")
            new_host, new_ledger, _, _ = _host_review(package, risk="R0")
            same_service_other_attempt = Host(other_host.plan, other_host.request, other_host._catalog, other_host._pipeline,
                review_services=host._review_services)
            same_service_other_plan = Host(new_host.plan, new_host.request, new_host._catalog, new_host._pipeline,
                review_services=host._review_services)
            for current_host, current_ledger in (
                (None, None), (host, None), ({}, ledger),
                (other_host, other_ledger), (same_service_other_attempt, other_ledger),
                (same_service_other_plan, new_ledger),
            ):
                with self.subTest(host_type=type(current_host).__name__, ledger=current_ledger is not None):
                    with self.assertRaisesRegex(QualityGateError, "quality-review-context-invalid"):
                        validate_completion(root, baseline, self._spec(), package, [review],
                            code_review_evidence=evidence, review_host=current_host, review_ledger=current_ledger)
            self.assertFalse(evidence._completion_used)
            self.assertEqual(validate_completion(root, baseline, self._spec(), package, [review],
                code_review_evidence=evidence, review_host=host, review_ledger=ledger)["status"], "complete")

    def test_full_deep_completion_rejects_json_host_attestation_without_host_execution(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            for mode in ("Full", "Deep"):
                spec = self._spec() | {"workflowMode": mode}
                package = build_review_package(root, baseline, spec, [self._plan()])
                review = {"axis": "combined", "executionId": "never-dispatched",
                    "attestation": "host_attested", "workflowMode": mode,
                    "packageHash": package["packageHash"], "findings": []}
                with self.subTest(mode=mode):
                    with self.assertRaisesRegex(QualityGateError, "quality-review-host-unverified"):
                        validate_completion(root, baseline, spec, package, [review])

    def test_one_host_review_passes_reviewed_then_complete_but_not_replay_or_forgery(self):
        from selfworkflow.v3.host import CodeReviewEvidence, HostError

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            package = build_review_package(root, baseline, self._spec(), [self._plan()])
            host, ledger, evidence, result = _host_review(package, apply_review=False)
            review = {"axis": "combined", "executionId": evidence["reviewers"]["combined"]["subagentExecutionId"],
                "attestation": "host_attested", "workflowMode": "Full", "packageHash": package["packageHash"], "findings": []}
            with self.assertRaisesRegex(QualityGateError, "quality-review-context-invalid"):
                validate_completion(root, baseline, self._spec(), package, [review], code_review_evidence=evidence,
                    review_host=host, review_ledger=ledger)

            with self.assertRaises(AttributeError):
                copy.copy(evidence)
            for forged in (dict(evidence), object.__new__(CodeReviewEvidence)):
                with self.subTest(forged_type=type(forged).__name__):
                    with self.assertRaisesRegex(QualityGateError, "quality-review-host-unverified"):
                        validate_completion(root, baseline, self._spec(), package, [review], code_review_evidence=forged)
                    with self.assertRaisesRegex(HostError, "code-review-host-evidence-required"):
                        host.apply_stage_result(ledger, result, code_review_evidence=forged)
            with self.assertRaisesRegex(HostError, "code-review-host-evidence-required"):
                host.apply_stage_result(ledger, result)
            for target, key, value in (
                (evidence._result["reviewers"]["combined"], "expiresAt", "2099-01-01T00:00:00Z"),
                (evidence._package["content"]["specification"], "design", "mutated after dispatch"),
            ):
                original = target[key]
                try:
                    target[key] = value
                    with self.assertRaisesRegex(QualityGateError, "quality-review-host-unverified"):
                        validate_completion(root, baseline, self._spec(), package, [review], code_review_evidence=evidence)
                finally:
                    target[key] = original
            with patch("selfworkflow.v3.host._review_now", return_value=datetime.now(timezone.utc) + timedelta(hours=1)):
                with self.assertRaisesRegex(QualityGateError, "quality-review-host-unverified"):
                    validate_completion(root, baseline, self._spec(), package, [review], code_review_evidence=evidence)
            for mode in ("Full", "Deep"):
                changed_spec = self._spec() | {"design": "another design", "workflowMode": mode}
                other_package = build_review_package(root, baseline, changed_spec, [self._plan()])
                changed_review = review | {"workflowMode": mode, "packageHash": other_package["packageHash"]}
                with self.assertRaisesRegex(QualityGateError, "quality-review-evidence-binding-invalid"):
                    validate_completion(root, baseline, changed_spec, other_package, [changed_review], code_review_evidence=evidence)
            with self.assertRaisesRegex(QualityGateError, "quality-review-evidence-binding-invalid"):
                validate_completion(root, baseline, self._spec(), package, [review | {"executionId": "invented"}], code_review_evidence=evidence)

            for invalid_result in (result | {"attemptRef": "other-attempt"}, result | {"outputArtifactHashes": []}):
                with self.assertRaisesRegex(HostError, "code-review-evidence-binding-invalid"):
                    host.apply_stage_result(ledger, invalid_result, code_review_evidence=evidence)
            broken_slot = result | {"slotResults": [{"slotId": "review.independent", "moduleId": "unknown", "artifactHash": result["outputArtifactHashes"][0]}]}
            with self.assertRaises(HostError):
                host.apply_stage_result(ledger, broken_slot, code_review_evidence=evidence)
            self.assertFalse(evidence._stage_used, "failed apply must not consume evidence")
            passed = host.apply_stage_result(ledger, result, code_review_evidence=evidence)
            self.assertEqual(next(s for s in passed["stages"] if s["stageId"] == "reviewed")["status"], "passed")
            with self.assertRaisesRegex(HostError, "code-review-evidence-binding-invalid"):
                host.apply_stage_result(ledger, result, code_review_evidence=evidence)
            completed = validate_completion(root, baseline, self._spec(), package, [review], code_review_evidence=evidence,
                review_host=host, review_ledger=passed)
            self.assertEqual(completed["status"], "complete")
            self.assertEqual(len(host._review_services.dispatch_port.calls), 1)
            with self.assertRaisesRegex(QualityGateError, "quality-review-host-unverified"):
                validate_completion(root, baseline, self._spec(), package, [review], code_review_evidence=evidence)

    def _repo(self, root: Path) -> None:
        _git(root, "init")
        _git(root, "config", "user.email", "quality@example.invalid")
        _git(root, "config", "user.name", "Quality Test")
        (root / "tracked.txt").write_text("base\n", encoding="utf-8")
        (root / "dirty.txt").write_text("committed\n", encoding="utf-8")
        (root / "deleted.txt").write_text("delete me\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "base")
        (root / "dirty.txt").write_text("user dirty\n", encoding="utf-8")

    @staticmethod
    def _spec() -> dict[str, str]:
        return {
            "workflowMode": "Full",
            "userRequest": "强化测试与 Review。",
            "acceptanceCriteria": "行为修改必须 TDD；C/I 清零。",
            "design": "最终设计实际内容。",
            "testDesign": "最终测试设计实际内容。",
            "implementationPlan": "最终实施计划实际内容。",
            "projectRules": "保护用户已有修改。",
        }

    @staticmethod
    def _plan(identifier: str = "green", argv: list[str] | None = None) -> dict[str, object]:
        return {
            "id": identifier,
            "argv": argv or [sys.executable, "-c", "print('green')"],
            "cwdRelative": ".",
            "timeoutSeconds": 30,
            "confirmedByUser": True,
            "resultContract": {"kind": "process-exit", "allowedExitCodes": [0]},
        }

    def test_review_package_contains_actual_task_delta_and_all_spec_content(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(
                root, ["tracked.txt", "dirty.txt", "deleted.txt", "new.txt", "binary.bin"],
            )

            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            _git(root, "add", "tracked.txt")
            (root / "dirty.txt").write_text("task changed dirty\n", encoding="utf-8")
            (root / "deleted.txt").unlink()
            (root / "new.txt").write_text("new content\n", encoding="utf-8")
            (root / "binary.bin").write_bytes(b"\x00\xff\x01")

            plans = [self._plan("unit", [sys.executable, "-m", "unittest"])]
            plans[0]["timeoutSeconds"] = 120
            package = build_review_package(root, baseline, self._spec(), plans)
            second = build_review_package(root, baseline, self._spec(), plans)

            self.assertRegex(package["packageHash"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(package["packageHash"], second["packageHash"])
            self.assertEqual(package["specification"], self._spec())
            self.assertEqual(package["verificationPlans"], plans)
            changes = {item["path"]: item for item in package["changes"]}
            self.assertIn("-base", changes["tracked.txt"]["patch"])
            self.assertIn("+changed", changes["tracked.txt"]["patch"])
            self.assertIn("-user dirty", changes["dirty.txt"]["patch"])
            self.assertIn("+task changed dirty", changes["dirty.txt"]["patch"])
            self.assertEqual(changes["deleted.txt"]["status"], "deleted")
            self.assertEqual(changes["new.txt"]["status"], "added")
            self.assertEqual(changes["binary.bin"]["after"]["kind"], "binary")
            self.assertIn("staged", changes["tracked.txt"]["gitStates"])
            self.assertIn("unstaged", changes["dirty.txt"]["gitStates"])
            self.assertIn("untracked", changes["new.txt"]["gitStates"])

    def test_review_package_rejects_missing_spec_content_and_path_escape(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            with self.assertRaisesRegex(QualityGateError, "quality-path-invalid"):
                capture_review_baseline(root, ["../escape.txt"])

            baseline = capture_review_baseline(root, ["tracked.txt"])
            incomplete = self._spec()
            incomplete["design"] = ""
            with self.assertRaisesRegex(QualityGateError, "quality-spec-invalid"):
                build_review_package(root, baseline, incomplete)

            with self.assertRaisesRegex(QualityGateError, "quality-verification-plan-invalid"):
                build_review_package(root, baseline, self._spec(), [])

    def test_review_package_rejects_changes_outside_approved_paths(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("approved\n", encoding="utf-8")
            (root / "dirty.txt").write_text("out of scope\n", encoding="utf-8")
            with self.assertRaisesRegex(QualityGateError, "quality-out-of-scope-change"):
                build_review_package(root, baseline, self._spec())

    def test_review_package_binds_staged_index_bytes_when_worktree_entry_is_missing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["staged-only.txt"])
            staged = root / "staged-only.txt"
            staged.write_text("staged secret\n", encoding="utf-8")
            _git(root, "add", "staged-only.txt")
            staged.unlink()

            package = build_review_package(root, baseline, self._spec(), [self._plan()])
            self.assertEqual(len(package["changes"]), 1)
            change = package["changes"][0]
            self.assertEqual(change["path"], "staged-only.txt")
            self.assertEqual(change["after"]["kind"], "missing")
            self.assertEqual(change["afterIndex"]["content"], "staged secret\n")
            self.assertIn("+staged secret", change["stagedPatch"])

    def test_review_package_binds_staged_git_mode_even_when_bytes_do_not_change(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])

            _git(root, "update-index", "--chmod=+x", "tracked.txt")
            package = build_review_package(root, baseline, self._spec(), [self._plan()])

            self.assertEqual(len(package["changes"]), 1)
            change = package["changes"][0]
            self.assertEqual(change["beforeIndex"]["gitMode"], "100644")
            self.assertEqual(change["afterIndex"]["gitMode"], "100755")
            self.assertIn("old mode 100644", change["stagedPatch"])
            self.assertIn("new mode 100755", change["stagedPatch"])

            _git(root, "update-index", "--chmod=-x", "tracked.txt")
            with self.assertRaisesRegex(QualityGateError, "quality-package-stale"):
                run_verification(root, package, "green")

    def test_complete_gate_accepts_only_current_independent_clean_reviews_and_fresh_green_verify(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            plans = [self._plan()]
            package = build_review_package(root, baseline, self._spec(), plans)
            package_hash = package["packageHash"]
            reviews = [
                {
                    "axis": "combined", "executionId": "combined-1",
                    "attestation": "host_attested",
                    "workflowMode": "Full",
                    "packageHash": package_hash,
                    "findings": [{"severity": "low", "status": "accepted", "disposition": "non-blocking"}],
                },
            ]
            _host, _ledger, evidence, _result = _host_review(package)
            reviews[0]["executionId"] = evidence["reviewers"]["combined"]["subagentExecutionId"]
            verifications = [run_verification(root, package, "green")]

            completed = validate_completion(
                root, baseline, self._spec(), package, reviews, code_review_evidence=evidence,
                review_host=_host, review_ledger=_ledger,
            )
            self.assertEqual(completed["status"], "complete")
            self.assertEqual(len(completed["verifications"]), 1)

            cases = {
                "quality-review-missing": [],
                "quality-review-not-independent": [{**reviews[0], "executionId": ""}],
                "quality-review-open-blocker": [{**reviews[0], "findings": [{"severity": "medium", "status": "open", "disposition": ""}]}],
            }
            for reason, case_reviews in cases.items():
                with self.subTest(reason=reason):
                    with self.assertRaisesRegex(QualityGateError, reason):
                        validate_completion(root, baseline, self._spec(), package, case_reviews)

            self.assertNotIn("verifications", inspect.signature(validate_completion).parameters)

            (root / "tracked.txt").write_text("drifted\n", encoding="utf-8")
            with self.assertRaisesRegex(QualityGateError, "quality-package-stale"):
                validate_completion(root, baseline, self._spec(), package, reviews)

    def test_completion_binds_review_evidence_to_light_full_and_deep_modes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")

            light_spec = self._spec() | {"workflowMode": "Light"}
            light_package = build_review_package(
                root, baseline, light_spec, [self._plan()]
            )
            light_review = [{
                "axis": "self",
                "executionId": "self-review-1",
                "attestation": "self_attested",
                "workflowMode": "Light",
                "packageHash": light_package["packageHash"],
                "findings": [],
            }]
            self.assertEqual(
                validate_completion(
                    root, baseline, light_spec, light_package, light_review,
                )["workflowMode"],
                "Light",
            )

            for workflow_mode in ("Full", "Deep"):
                spec = self._spec() | {"workflowMode": workflow_mode}
                package = build_review_package(root, baseline, spec, [self._plan()])
                reviews = [
                    {
                        "axis": "combined",
                        "executionId": f"{workflow_mode}-combined",
                        "attestation": "host_attested",
                        "workflowMode": workflow_mode,
                        "packageHash": package["packageHash"],
                        "findings": [],
                    },
                ]
                _host, _ledger, evidence, _result = _host_review(package, workflow_mode)
                reviews[0]["executionId"] = evidence["reviewers"]["combined"]["subagentExecutionId"]
                self.assertEqual(
                    validate_completion(root, baseline, spec, package, reviews, code_review_evidence=evidence,
                        review_host=_host, review_ledger=_ledger)[
                        "workflowMode"
                    ],
                    workflow_mode,
                )
                with self.assertRaisesRegex(
                    QualityGateError, "quality-review-mode-mismatch"
                ):
                    validate_completion(
                        root,
                        baseline,
                        spec,
                        package,
                        [{**reviews[0], "workflowMode": "Light"}],
                    )

    def test_verification_runner_rejects_unbound_shell_and_outside_cwd(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            plans = [self._plan("shell", ["powershell", "-Command", "exit 0"])]
            with self.assertRaisesRegex(QualityGateError, "quality-verification-plan-invalid"):
                build_review_package(root, baseline, self._spec(), plans)

    def test_verification_runner_rebuilds_package_before_execution_and_stops_output_overflow(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            package = build_review_package(root, baseline, self._spec(), [self._plan()])
            (root / "tracked.txt").write_text("drifted\n", encoding="utf-8")
            with self.assertRaisesRegex(QualityGateError, "quality-package-stale"):
                run_verification(root, package, "green")

            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            loud = self._plan(
                "loud",
                [sys.executable, "-c", "import sys; sys.stdout.write('x' * (9 * 1024 * 1024))"],
            )
            loud_package = build_review_package(root, baseline, self._spec(), [loud])
            with self.assertRaisesRegex(QualityGateError, "quality-verification-output-limit"):
                run_verification(root, loud_package, "loud")

    def test_verification_runner_rejects_cwd_escape_unbound_plan_timeout_and_post_drift(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")

            escaped = self._plan()
            escaped["cwdRelative"] = "../outside"
            with self.assertRaisesRegex(QualityGateError, "quality-verification-plan-invalid"):
                build_review_package(root, baseline, self._spec(), [escaped])

            package = build_review_package(root, baseline, self._spec(), [self._plan()])
            with self.assertRaisesRegex(QualityGateError, "quality-verification-plan-unbound"):
                run_verification(root, package, "not-bound")

            timeout_plan = self._plan(
                "timeout", [sys.executable, "-c", "import time; time.sleep(5)"],
            )
            timeout_plan["timeoutSeconds"] = 1
            timeout_package = build_review_package(root, baseline, self._spec(), [timeout_plan])
            timeout_receipt = run_verification(root, timeout_package, "timeout")
            self.assertEqual(timeout_receipt["status"], "failed")
            self.assertTrue(timeout_receipt["consumerResult"]["timedOut"])

            drift_plan = self._plan(
                "drift",
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('tracked.txt').write_text('post drift')",
                ],
            )
            drift_package = build_review_package(root, baseline, self._spec(), [drift_plan])
            with self.assertRaisesRegex(QualityGateError, "quality-package-stale"):
                run_verification(root, drift_package, "drift")

    def test_verification_runner_isolates_environment_and_kills_output_overflow_tree(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            self._repo(root)
            baseline = capture_review_baseline(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")

            environment_plan = self._plan(
                "environment",
                [
                    sys.executable,
                    "-c",
                    "import os,sys; sys.exit(0 if os.getenv('SELFWORKFLOW_TEST_SECRET') is None else 9)",
                ],
            )
            package = build_review_package(root, baseline, self._spec(), [environment_plan])
            with patch.dict("os.environ", {"SELFWORKFLOW_TEST_SECRET": "must-not-leak"}):
                self.assertEqual(run_verification(root, package, "environment")["status"], "verified")

            child_code = (
                "import pathlib,time; time.sleep(1); "
                "pathlib.Path('child-survived.txt').write_text('bad')"
            )
            parent_code = (
                "import os,subprocess,sys; "
                f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
                "chunk=b'x'*65536; exec(\"while True:\\n os.write(1,chunk)\")"
            )
            tree_plan = self._plan("tree", [sys.executable, "-c", parent_code])
            tree_package = build_review_package(root, baseline, self._spec(), [tree_plan])
            with self.assertRaisesRegex(QualityGateError, "quality-verification-output-limit"):
                run_verification(root, tree_package, "tree")
            time.sleep(1.5)
            self.assertFalse((root / "child-survived.txt").exists())

            exited_child_code = (
                "import pathlib,time; time.sleep(1); "
                "pathlib.Path('exited-parent-child-survived.txt').write_text('bad'); "
                "time.sleep(20)"
            )
            exited_parent_code = (
                "import subprocess,sys; "
                f"subprocess.Popen([sys.executable,'-c',{exited_child_code!r}])"
            )
            exited_plan = self._plan(
                "exited-parent", [sys.executable, "-c", exited_parent_code],
            )
            exited_package = build_review_package(root, baseline, self._spec(), [exited_plan])
            with self.assertRaisesRegex(
                QualityGateError, "quality-verification-background-process",
            ):
                run_verification(root, exited_package, "exited-parent")
            time.sleep(1.5)
            self.assertFalse((root / "exited-parent-child-survived.txt").exists())

    def test_posix_tree_cleanup_reaps_group_leader_before_group_confirmation(self):
        class Process:
            pid = 12345
            returncode = None
            reaped = False

            def wait(self, timeout: int) -> int:
                self.reaped = True
                self.returncode = -9
                return self.returncode

            def poll(self) -> int | None:
                return self.returncode

        process = Process()

        def group_exists(_group_id: int) -> bool:
            if not process.reaped:
                raise AssertionError("group checked before leader was reaped")
            return False

        with (
            patch("selfworkflow.quality.os.name", "posix"),
            patch("selfworkflow.quality.os.killpg", create=True),
            patch("selfworkflow.quality.signal.SIGKILL", 9, create=True),
            patch("selfworkflow.quality._posix_group_exists", side_effect=group_exists),
        ):
            _terminate_process_tree(process, None)

        self.assertTrue(process.reaped)

    def test_quality_cli_captures_and_packages_review_input(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            self._repo(root)
            baseline_path = base / "baseline.json"
            package_path = base / "package.json"
            spec_path = root / "spec.json"
            plans_path = root / "plans.json"
            spec_path.write_text(json.dumps(self._spec()), encoding="utf-8")
            plans_path.write_text(json.dumps({"plans": [self._plan()]}), encoding="utf-8")
            self.assertEqual(cli_main([
                "quality", "capture", "--repository", str(root),
                "--path", "tracked.txt", "--output", str(baseline_path),
            ]), 0)
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            self.assertEqual(cli_main([
                "quality", "package", "--repository", str(root),
                "--baseline", str(baseline_path), "--specification", str(spec_path),
                "--verification-plans", str(plans_path), "--output", str(package_path),
            ]), 0)
            self.assertRegex(json.loads(package_path.read_text(encoding="utf-8"))["packageHash"], r"^sha256:")


if __name__ == "__main__":
    unittest.main()
