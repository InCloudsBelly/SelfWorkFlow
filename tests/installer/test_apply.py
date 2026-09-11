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


class InstallApplyTests(unittest.TestCase):
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
                "已完成主阶段/总主阶段",
                "当前",
                "剩余",
                "预计",
                "粗略区间",
                "独立 SubAgent",
                "至少两份正式文档",
                "最终文档包 hash",
                "侵入性预算",
                "影响半径",
                "测试覆盖不能反向驱动生产架构",
                "代码实施契约",
                "第一次编辑测试或生产代码前",
                "明确实施确认",
                "Review → 用户确认 → TDD",
                "确认失效",
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
