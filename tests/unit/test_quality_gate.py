from __future__ import annotations

from datetime import datetime, timezone
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


class QualityGateTests(unittest.TestCase):
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
                    "axis": "standards", "executionId": "standards-1",
                    "attestation": "host_attested",
                    "workflowMode": "Full",
                    "packageHash": package_hash, "findings": [],
                },
                {
                    "axis": "spec", "executionId": "spec-1",
                    "attestation": "host_attested",
                    "workflowMode": "Full",
                    "packageHash": package_hash,
                    "findings": [{"severity": "low", "status": "accepted", "disposition": "non-blocking"}],
                },
            ]
            verifications = [run_verification(root, package, "green")]

            completed = validate_completion(
                root, baseline, self._spec(), package, reviews,
            )
            self.assertEqual(completed["status"], "complete")
            self.assertEqual(len(completed["verifications"]), 1)

            cases = {
                "quality-review-missing": reviews[:1],
                "quality-review-not-independent": [reviews[0], {**reviews[1], "executionId": "standards-1"}],
                "quality-review-open-blocker": [reviews[0], {**reviews[1], "findings": [{"severity": "medium", "status": "open", "disposition": ""}]}],
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
                        "axis": "standards",
                        "executionId": f"{workflow_mode}-standards",
                        "attestation": "host_attested",
                        "workflowMode": workflow_mode,
                        "packageHash": package["packageHash"],
                        "findings": [],
                    },
                    {
                        "axis": "spec",
                        "executionId": f"{workflow_mode}-spec",
                        "attestation": "host_attested",
                        "workflowMode": workflow_mode,
                        "packageHash": package["packageHash"],
                        "findings": [],
                    },
                ]
                self.assertEqual(
                    validate_completion(root, baseline, spec, package, reviews)[
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
                        [{**reviews[0], "workflowMode": "Light"}, reviews[1]],
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
