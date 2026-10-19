from pathlib import Path
from contextlib import contextmanager
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

from selfworkflow.adapters import build_runtime
from selfworkflow.installer import (
    InstallerError,
    apply_install_plan,
    create_install_plan,
    verify_install,
)
from tests.installer.support import create_artifact


@contextmanager
def _hold_file_without_delete_sharing(path):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


class InstallApplyTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows file sharing")
    def test_unchanged_write_preserves_a_delete_locked_file(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "SKILL.md"
            target.write_bytes(b"unchanged skill")
            before = target.stat()
            with _hold_file_without_delete_sharing(target):
                installer._atomic_write(
                    target, b"unchanged skill",
                    expected_state=(True, installer._path_hash(target)),
                )
                self.assertEqual(target.read_bytes(), b"unchanged skill")
                self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)
                self.assertEqual(target.stat().st_ino, before.st_ino)

    @unittest.skipUnless(os.name == "nt", "Windows file sharing")
    def test_changed_write_keeps_the_delete_locked_file_and_reports_failure(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "SKILL.md"
            target.write_bytes(b"original skill")
            with _hold_file_without_delete_sharing(target):
                with self.assertRaises(PermissionError):
                    installer._atomic_write(
                        target, b"changed skill",
                        expected_state=(True, installer._path_hash(target)),
                    )
                self.assertEqual(target.read_bytes(), b"original skill")

    def test_unchanged_desired_hash_still_rejects_a_concurrent_preimage(self):
        import hashlib
        from selfworkflow import installer

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "SKILL.md"
            target.write_bytes(b"concurrent user skill")
            desired = b"planned skill"
            expected = "sha256:" + hashlib.sha256(desired).hexdigest()
            with self.assertRaisesRegex(InstallerError, "operation-preimage-drift"):
                installer._atomic_write(target, desired, expected_state=(True, expected))
            self.assertEqual(target.read_bytes(), b"concurrent user skill")

    def test_committed_install_reports_pending_lock_cleanup_without_losing_result(self):
        from contextlib import redirect_stdout, redirect_stderr
        from io import StringIO
        from selfworkflow.cli import main

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            state = root / "state"
            plan = create_install_plan(artifact, root / "agents", root / "codex", state, "0.1.0")
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            unlink = Path.unlink

            def busy_lock(path, *args, **kwargs):
                if path.name == "install.lock":
                    raise PermissionError("busy")
                return unlink(path, *args, **kwargs)

            stdout, stderr = StringIO(), StringIO()
            with mock.patch.object(Path, "unlink", busy_lock), redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["install", "apply", "--plan", str(plan_path), "--confirm-plan-hash", plan["planHash"]])
            self.assertEqual(code, 0, stderr.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["cleanupPending"], ["installer-lock-release-failed"])
            self.assertEqual(verify_install(result["manifestPath"])["status"], "verified")
            transaction = json.loads(Path(result["transactionPath"]).read_text(encoding="utf-8"))
            self.assertEqual(transaction["state"], "completed")
            self.assertTrue((state / "install.lock").is_file())
            same = create_install_plan(artifact, root / "agents", root / "codex", state, "0.1.0")
            self.assertEqual(same["status"], "already-installed")
            with self.assertRaisesRegex(InstallerError, "installer-locked"):
                apply_install_plan(same, same["planHash"])
            with self.assertRaisesRegex(InstallerError, "installer-locked"):
                other = create_install_plan(artifact, root / "other-agents", root / "other-codex", state, "0.1.1")
                apply_install_plan(other, other["planHash"])

    def test_prepare_operation_binds_backup_bytes_to_the_recorded_preimage(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            target = root / "target.txt"
            backup_root = root / "backups"
            target.write_bytes(b"original-a")
            real_copyfile = shutil.copyfile

            def copy_during_aba(source, destination):
                Path(source).write_bytes(b"intermediate-b")
                result = real_copyfile(source, destination)
                Path(source).write_bytes(b"original-a")
                return result

            with mock.patch(
                "shutil.copyfile",
                side_effect=copy_during_aba,
            ):
                operation = installer._prepare_operation(
                    target, b"replacement", backup_root,
                )

            backup = Path(operation["backupPath"])
            self.assertEqual(target.read_bytes(), b"original-a")
            self.assertEqual(installer._path_hash(backup), operation["beforeHash"])

    def test_real_knowledge_runtime_installs_progress_and_integrated_review_policy(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            repository = Path(__file__).resolve().parents[2]
            artifact = root / "runtime"
            build_runtime(
                repository, artifact, "0.1.0.dev0", profile="knowledge",
            )
            agents, codex, state = root / "agents", root / "codex", root / "state"
            plan = create_install_plan(
                artifact, agents, codex, state, "0.1.0.dev0",
            )

            result = apply_install_plan(plan, plan["planHash"])

            self.assertEqual(result["status"], "applied")
            installed = (codex / "AGENTS.md").read_text(encoding="utf-8")
            for phrase in (
                "SelfWorkflow active: <profile>",
                "mode: <Light|Full|Deep>",
                "阶段/总阶段",
                "当前",
                "剩余",
                "预计",
                "粗略进度区间",
                "独立 SubAgent",
                "所有模式禁止双 Reviewer",
                "侵入预算",
                "测试不能反向扩张生产架构",
                "实施契约",
                "首次编辑测试/生产代码前",
                "已有同范围授权复用",
                "关键风险变化需重新确认",
            ):
                self.assertIn(phrase, installed)

    def test_apply_preserves_unmanaged_content_and_verify_is_idempotent(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            existing = agents / "skills" / "existing" / "SKILL.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("existing\n", encoding="utf-8")
            codex.mkdir()
            (codex / "AGENTS.md").write_text("user content\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")

            result = apply_install_plan(plan, plan["planHash"])

            self.assertEqual(result["status"], "applied")
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing\n")
            agents_text = (codex / "AGENTS.md").read_text(encoding="utf-8")
            self.assertTrue(agents_text.startswith("user content\n"))
            self.assertEqual(agents_text.count("<!-- selfworkflow:begin -->"), 1)
            self.assertIn("# Installed workflow", agents_text)
            self.assertIn(plan["artifactHash"], agents_text)
            self.assertIn("profile: `custom-unverified`", agents_text)
            self.assertIn(str(
                Path(plan["agentsRoot"])
                / "selfworkflow"
                / "versions"
                / "0.1.0"
                / plan["artifactHash"].removeprefix("sha256:")
            ), agents_text)
            self.assertIn("普通任务", agents_text)
            self.assertIn("不创建 PlanGraph 或 RunLedger", agents_text)
            self.assertIn("显式 contract-managed", agents_text)
            self.assertNotIn("Read the vendor-neutral workflow at", agents_text)
            self.assertNotIn("run `selfworkflow resolve", agents_text)
            self.assertTrue(
                (agents / "skills/sample-skill/SKILL.md").is_file()
            )
            self.assertEqual(verify_install(Path(result["manifestPath"]))["status"], "verified")
            manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
            schema = json.loads(
                (Path(__file__).resolve().parents[2] / "schemas/install-manifest.schema.json")
                .read_text(encoding="utf-8")
            )
            Draft202012Validator(schema).validate(manifest)
            self.assertEqual(manifest["profile"], "custom-unverified")
            second = create_install_plan(artifact, agents, codex, state, "0.1.0")
            self.assertEqual(second["status"], "already-installed")

    def test_upgrade_refreshes_inlined_workflow_without_touching_user_content(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            workflow = artifact / "WORKFLOW.md"
            workflow.write_text("# Installed workflow\n\ncore-rule-v1\n", encoding="utf-8")
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            agents_file = codex / "AGENTS.md"
            agents_file.write_text("user-owned-prefix\n", encoding="utf-8")

            first = create_install_plan(artifact, agents, codex, state, "0.1.0")
            apply_install_plan(first, first["planHash"])
            self.assertIn("core-rule-v1", agents_file.read_text(encoding="utf-8"))

            workflow.write_text("# Installed workflow\n\ncore-rule-v2\n", encoding="utf-8")
            second = create_install_plan(artifact, agents, codex, state, "0.1.0")
            self.assertEqual(second["status"], "ready")
            apply_install_plan(second, second["planHash"])

            installed = agents_file.read_text(encoding="utf-8")
            self.assertTrue(installed.startswith("user-owned-prefix\n"))
            self.assertNotIn("core-rule-v1", installed)
            self.assertIn("core-rule-v2", installed)
            self.assertIn(second["artifactHash"], installed)

    def test_bootstrap_deduplicates_only_identical_unmanaged_build_policy(self):
        policy = "## 编译缓存保护\n\n- 保留 PCH；禁止未经授权 Clean/Rebuild。\n"
        old = "<!-- selfworkflow:begin -->\nold rules\n<!-- selfworkflow:end -->\n"
        for label, outside, expected_count in (
            ("missing", "user-owned-prefix\n", 1),
            ("suffix", "user-owned-prefix\n" + old + "\n" + policy, 1),
            ("prefix", policy + "\n" + old + "\nuser-owned-suffix\n", 1),
            ("different", policy.replace("PCH", "DDC"), 2),
            ("quoted", "```markdown\n" + policy + "```\n", 2),
            ("html", "以下仅为引用示例：\n<pre>\n" + policy + "\n## 示例结束\n</pre>\n", 2),
            ("managed-only", old.replace("old rules", policy.strip()), 1),
        ):
            with self.subTest(case=label), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                root = Path(temporary)
                artifact = create_artifact(root)
                workflow = "# Installed workflow\n\n" + policy + "\n## Other\n\nKeep this rule.\n"
                (artifact / "WORKFLOW.md").write_text(workflow, encoding="utf-8")
                agents, codex, state = root / "agents", root / "codex", root / "state"
                codex.mkdir()
                agents_file = codex / "AGENTS.md"
                original = outside.replace("\n", "\r\n").encode("utf-8")
                agents_file.write_bytes(original)
                plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
                self.assertEqual(plan["status"], "ready")
                applied = apply_install_plan(plan, plan["planHash"])
                installed = agents_file.read_bytes()
                text = installed.decode("utf-8").replace("\r\n", "\n")
                self.assertEqual(text.count("## 编译缓存保护"), expected_count)
                self.assertIn("Keep this rule.", text)
                # Replacement may change only the managed span, never user bytes.
                if b"<!-- selfworkflow:begin -->" in original:
                    prefix, _, tail = original.partition(b"<!-- selfworkflow:begin -->")
                    _, _, suffix = tail.partition(b"<!-- selfworkflow:end -->")
                    self.assertTrue(installed.startswith(prefix))
                    self.assertTrue(installed.endswith(suffix))
                else:
                    self.assertTrue(installed.startswith(original))
                self.assertEqual((artifact / "WORKFLOW.md").read_text("utf-8"), workflow)
                self.assertEqual(verify_install(Path(applied["manifestPath"]))["status"], "verified")
                self.assertEqual(create_install_plan(artifact, agents, codex, state, "0.1.0")["status"], "already-installed")

    def test_already_installed_is_bound_to_the_exact_target_roots(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            state = root / "state"
            first = create_install_plan(
                artifact, root / "agents-a", root / "codex-a", state, "0.1.0"
            )
            apply_install_plan(first, first["planHash"])

            second = create_install_plan(
                artifact, root / "agents-b", root / "codex-b", state, "0.1.0"
            )
            self.assertEqual(second["status"], "ready")
            applied = apply_install_plan(second, second["planHash"])
            self.assertEqual(applied["status"], "applied")
            self.assertTrue((root / "agents-b/skills/sample-skill/SKILL.md").is_file())

    def test_apply_rejects_wrong_confirmation_and_managed_target_or_artifact_drift(self):
        for drift in ("target", "state", "artifact"):
            with self.subTest(drift=drift):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                    root = Path(temporary)
                    artifact = create_artifact(root)
                    agents, codex, state = root / "agents", root / "codex", root / "state"
                    plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
                    with self.assertRaises(InstallerError):
                        apply_install_plan(plan, "sha256:" + "0" * 64)
                    if drift == "target":
                        managed = agents / "skills/sample-skill/SKILL.md"
                        managed.parent.mkdir(parents=True)
                        managed.write_text("drift\n", encoding="utf-8")
                    elif drift == "state":
                        state.mkdir()
                        (state / "current-manifest.json").write_text(
                            "{}\n", encoding="utf-8"
                        )
                    else:
                        (artifact / "WORKFLOW.md").write_text("drift\n", encoding="utf-8")
                    with self.assertRaises(InstallerError):
                        apply_install_plan(plan, plan["planHash"])

    def test_apply_allows_unmanaged_target_drift(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            codex.mkdir()
            (codex / "session.jsonl").write_bytes(b"x" * (8 * 1024 * 1024 + 1))

            result = apply_install_plan(plan, plan["planHash"])

            self.assertEqual(result["status"], "applied")
            self.assertTrue((codex / "session.jsonl").is_file())

    def test_apply_rechecks_artifact_and_target_after_lock_acquisition(self):
        from selfworkflow import installer

        for drift in ("target", "artifact"):
            with self.subTest(drift=drift):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                    root = Path(temporary)
                    artifact = create_artifact(root)
                    agents, codex, state = (
                        root / "agents", root / "codex", root / "state"
                    )
                    plan = create_install_plan(
                        artifact, agents, codex, state, "0.1.0"
                    )

                    @contextmanager
                    def drift_while_waiting(_state):
                        if drift == "target":
                            managed = agents / "skills/sample-skill/SKILL.md"
                            managed.parent.mkdir(parents=True, exist_ok=True)
                            managed.write_text(
                                "concurrent\n", encoding="utf-8"
                            )
                        else:
                            (artifact / "WORKFLOW.md").write_text(
                                "concurrent artifact\n", encoding="utf-8"
                            )
                        yield

                    with mock.patch(
                        "selfworkflow.installer.exclusive_install_lock",
                        side_effect=drift_while_waiting,
                    ):
                        with self.assertRaisesRegex(
                            InstallerError,
                            "target-drift" if drift == "target" else "artifact-drift",
                        ):
                            apply_install_plan(plan, plan["planHash"])

                    managed = agents / "skills/sample-skill/SKILL.md"
                    if drift == "target":
                        self.assertEqual(
                            managed.read_text(encoding="utf-8"), "concurrent\n"
                        )
                    else:
                        self.assertFalse(managed.exists())

    def test_apply_failure_after_first_write_automatically_restores_targets(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            agents_file = codex / "AGENTS.md"
            agents_file.write_text("user content\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            real_operation = installer._publish_operation
            calls = 0

            def fail_second_operation(*arguments, **keywords):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected-operation-failure")
                return real_operation(*arguments, **keywords)

            with mock.patch(
                "selfworkflow.installer._publish_operation",
                side_effect=fail_second_operation,
            ):
                with self.assertRaises(InstallerError):
                    apply_install_plan(plan, plan["planHash"])

            self.assertEqual(
                agents_file.read_text(encoding="utf-8"), "user content\n"
            )
            self.assertFalse((agents / "skills/sample-skill/SKILL.md").exists())
            transactions = list((state / "transactions").glob("*.json"))
            self.assertEqual(len(transactions), 1)
            transaction = json.loads(transactions[0].read_text(encoding="utf-8"))
            self.assertEqual(transaction["state"], "rolled-back")

    def test_apply_failure_after_retired_skill_delete_restores_deleted_skill(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            first = create_install_plan(artifact, agents, codex, state, "0.1.0")
            apply_install_plan(first, first["planHash"])
            retired = agents / "skills/sample-skill/SKILL.md"
            original = retired.read_bytes()

            replacement = root / "replacement"
            replacement.mkdir()
            (replacement / "WORKFLOW.md").write_text(
                "# Replacement workflow\n", encoding="utf-8"
            )
            second = create_install_plan(
                replacement, agents, codex, state, "0.1.1"
            )
            real_delete = installer._publish_delete

            def delete_then_fail(operation):
                real_delete(operation)
                raise OSError("injected-post-delete-failure")

            with mock.patch(
                "selfworkflow.installer._publish_delete",
                side_effect=delete_then_fail,
            ):
                with self.assertRaisesRegex(InstallerError, "apply-failed"):
                    apply_install_plan(second, second["planHash"])

            self.assertEqual(retired.read_bytes(), original)
            transactions = list((state / "transactions").glob("*.json"))
            latest = max(transactions, key=lambda path: path.stat().st_mtime_ns)
            transaction = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(transaction["state"], "rolled-back")

    def test_apply_preserves_target_changed_after_operation_is_prepared(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            real_prepare = installer._prepare_operation
            injected_target = None

            def prepare_then_change(target, content, backup_root):
                nonlocal injected_target
                operation = real_prepare(target, content, backup_root)
                if injected_target is None:
                    injected_target = target
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("concurrent user edit\n", encoding="utf-8")
                return operation

            with mock.patch(
                "selfworkflow.installer._prepare_operation",
                side_effect=prepare_then_change,
            ):
                with self.assertRaises(InstallerError):
                    apply_install_plan(plan, plan["planHash"])

            self.assertIsNotNone(injected_target)
            self.assertEqual(
                injected_target.read_text(encoding="utf-8"),
                "concurrent user edit\n",
            )

    @unittest.skipUnless(os.name == "nt", "Windows reparse boundary")
    def test_apply_rejects_parent_link_swapped_after_operation_is_prepared(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            foreign = root / "foreign"
            foreign.mkdir()
            sentinel = foreign / "sentinel.txt"
            sentinel.write_text("foreign\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            real_prepare = installer._prepare_operation
            swapped = False

            def prepare_then_swap_parent(target, content, backup_root):
                nonlocal swapped
                operation = real_prepare(target, content, backup_root)
                if not swapped:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.parent.rmdir()
                    os.symlink(foreign, target.parent, target_is_directory=True)
                    swapped = True
                return operation

            with mock.patch(
                "selfworkflow.installer._prepare_operation",
                side_effect=prepare_then_swap_parent,
            ):
                with self.assertRaises(InstallerError):
                    apply_install_plan(plan, plan["planHash"])

            self.assertTrue(swapped)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "foreign\n")
            self.assertEqual(sorted(item.name for item in foreign.iterdir()), ["sentinel.txt"])

    def test_interrupt_after_publish_has_a_persisted_intent_and_rolls_back(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            real_write = installer._atomic_write
            interrupted = False

            def publish_then_interrupt(path, content, *, expected_state=None):
                nonlocal interrupted
                real_write(path, content, expected_state=expected_state)
                if not interrupted:
                    interrupted = True
                    raise SystemExit("injected-interrupt")

            with mock.patch(
                "selfworkflow.installer._atomic_write",
                side_effect=publish_then_interrupt,
            ):
                with self.assertRaises(SystemExit):
                    apply_install_plan(plan, plan["planHash"])

            transactions = list((state / "transactions").glob("*.json"))
            self.assertEqual(len(transactions), 1)
            transaction = json.loads(transactions[0].read_text(encoding="utf-8"))
            self.assertEqual(transaction["state"], "rolled-back")
            self.assertGreaterEqual(len(transaction["operations"]), 1)
            self.assertFalse((agents / "skills/sample-skill/SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
