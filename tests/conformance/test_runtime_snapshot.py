from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from selfworkflow.adapters import AdapterError, build_runtime
from selfworkflow.cli import main


class RuntimeSnapshotTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_default_runtime_is_deterministic_lightweight_core(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            first = build_runtime(self.ROOT, root / "first", "0.1.0.dev0")
            second = build_runtime(self.ROOT, root / "second", "0.1.0.dev0")
            self.assertEqual(first["runtimeHash"], second["runtimeHash"])
            self.assertEqual(first["profile"], "core")
            self.assertEqual(first["features"], {"grillMe": True})
            self.assertTrue((root / "first/WORKFLOW.md").is_file())
            self.assertTrue((root / "first/skills/code-quality/SKILL.md").is_file())
            self.assertTrue((root / "first/skills/ponytail/SKILL.md").is_file())
            self.assertTrue((root / "first/skills/ponytail-review/SKILL.md").is_file())
            self.assertTrue((root / "first/skills/ponytail-audit/SKILL.md").is_file())
            self.assertTrue((root / "first/skills/ponytail-help/SKILL.md").is_file())
            self.assertTrue((root / "first/skills/ponytail/LICENSE").is_file())
            self.assertFalse((root / "first/skills/caveman").exists())
            self.assertTrue((root / "first/skills/matt-pocock/grilling/SKILL.md").is_file())
            self.assertTrue((root / "first/skills/matt-pocock/tdd/SKILL.md").is_file())
            self.assertFalse((root / "first/skills/grill-me").exists())
            self.assertEqual(
                (root / "first/WORKFLOW.md").read_bytes(),
                (self.ROOT / "WORKFLOW.md").read_bytes(),
            )
            workflow_text = (root / "first/WORKFLOW.md").read_text(encoding="utf-8")
            for phrase in (
                "SelfWorkflow active: <profile>",
                "mode: <Light|Full|Deep>",
                "已完成主阶段/总主阶段",
                "独立 SubAgent",
                "至少两份正式文档",
                "侵入性预算",
                "影响半径",
                "测试覆盖不能反向驱动生产架构",
                "代码实施契约",
                "第一次编辑测试或生产代码前",
                "明确实施确认",
                "Review → 用户确认 → TDD",
                "确认失效",
                "非代码任务不自动加载",
                "不启用上游全局配置或 hooks",
            ):
                self.assertIn(phrase, workflow_text)
            self.assertFalse((root / "first/extensions").exists())
            self.assertTrue((root / "first/schemas/plan-graph.schema.json").is_file())
            self.assertTrue((root / "first/schemas/work-artifact-manifest.schema.json").is_file())
            self.assertTrue((root / "first/schemas/work-artifact-operation.schema.json").is_file())
            self.assertTrue((root / "first/schemas/work-artifact-publication-receipt.schema.json").is_file())
            self.assertTrue((root / "first/workflow/pipeline.yaml").is_file())
            self.assertTrue((root / "first/workflow/work-artifact-lifecycle.md").is_file())
            self.assertTrue((root / "first/schemas/v3/resolve-request.schema.json").is_file())
            self.assertTrue((root / "first/workflow/v3/pipeline.yaml").is_file())
            self.assertTrue((root / "first/catalog/v3/index.yaml").is_file())
            self.assertFalse((root / "first/catalog/v3/domains/knowledge.yaml").exists())
            self.assertFalse((root / "first/catalog/v3/modules/knowledge-update.yaml").exists())
            self.assertTrue((root / "first/skills/cpp-core/SKILL.md").is_file())
            self.assertTrue((root / "first/capabilities/cpp/core.yaml").is_file())
            self.assertFalse((root / "first/Manage_SelfWorkFlow_Providers.bat").exists())
            self.assertFalse((root / "first/scripts/manage-selfworkflow-providers.ps1").exists())
            self.assertFalse((root / "first/workflow/protected-rules.yaml").exists())
            core_catalog = json.loads((root / "first/catalog.json").read_text())
            self.assertEqual(
                {entry["id"] for entry in core_catalog["catalog"]["entries"]},
                {
                    "workflow-core", "workflow-quality", "code-quality",
                    "ponytail", "ponytail-review", "ponytail-audit", "ponytail-help",
                    "matt-skills-foundation", "testing-review-quality",
                    "tea-quality-foundation",
                },
            )
            core_ids = {entry["id"] for entry in core_catalog["catalog"]["entries"]}
            self.assertTrue(all(
                set(entry["dependencies"]) <= core_ids
                for entry in core_catalog["catalog"]["entries"]
            ))
            runtime_root = root / "first"
            policy_path = runtime_root / "workflow/git-policy.yaml"
            content = b"".join(
                path.read_bytes() for path in runtime_root.rglob("*") if path.is_file()
            ).lower()
            self.assertNotIn(b"caveman", content)
            # The runtime policy may name the pinned gitlink for its allowlist;
            # no upstream tree or source package is copied into the runtime.
            self.assertIn(b"dependencies/upstream/ponytail", policy_path.read_bytes())
            content_without_policy = b"".join(
                path.read_bytes()
                for path in runtime_root.rglob("*")
                if path.is_file() and path != policy_path
            ).lower()
            self.assertNotIn(b"dependencies/upstream/ponytail", content_without_policy)
            self.assertFalse((root / "first/hooks").exists())
            self.assertFalse((root / "first/.codex-plugin").exists())
            self.assertNotIn(b"e:\\", content)
            self.assertNotIn(b"d:\\openwikic7", content)
            for forbidden in ("provider-config.json", ".codegraph", "logs", "cache"):
                self.assertFalse(any(
                    forbidden in path.relative_to(root / "first").as_posix().casefold()
                    for path in (root / "first").rglob("*")
                ))

    def test_runtime_can_explicitly_exclude_grill_me_without_stale_catalog_metadata(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            manifest = build_runtime(
                self.ROOT,
                root / "runtime",
                "0.1.0.dev0",
                include_grill_me=False,
            )

            self.assertEqual(manifest["features"], {"grillMe": False})
            self.assertFalse((root / "runtime/skills/matt-pocock/grill-me").exists())
            self.assertTrue((root / "runtime/skills/matt-pocock/grilling/SKILL.md").is_file())
            catalog = json.loads((root / "runtime/catalog.json").read_text())
            self.assertIn(
                "matt-skills-foundation",
                {entry["id"] for entry in catalog["catalog"]["entries"]},
            )

    def test_explicit_profiles_add_only_their_intended_boundaries(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            knowledge = build_runtime(
                self.ROOT, root / "knowledge", "0.1.0.dev0", profile="knowledge"
            )
            maintainer = build_runtime(
                self.ROOT, root / "maintainer", "0.1.0.dev0", profile="maintainer"
            )
            self.assertEqual(knowledge["profile"], "knowledge")
            self.assertTrue((root / "knowledge/extensions/knowledge/contract.yaml").is_file())
            self.assertTrue((root / "knowledge/extensions/knowledge/selfopenwiki/tool-contract.json").is_file())
            self.assertTrue((root / "knowledge/skills/knowledge-backend/SKILL.md").is_file())
            self.assertTrue((root / "knowledge/skills/kg-selfopenwiki/SKILL.md").is_file())
            self.assertTrue((root / "knowledge/catalog/v3/domains/knowledge.yaml").is_file())
            self.assertTrue((root / "knowledge/catalog/v3/modules/knowledge-update.yaml").is_file())
            self.assertFalse((root / "knowledge/workflow/protected-rules.yaml").exists())
            knowledge_catalog = json.loads((root / "knowledge/catalog.json").read_text())
            self.assertIn(
                "knowledge-on-demand-loading",
                {entry["id"] for entry in knowledge_catalog["catalog"]["entries"]},
            )
            self.assertEqual(maintainer["profile"], "maintainer")
            self.assertTrue((root / "maintainer/workflow/protected-rules.yaml").is_file())
            self.assertTrue((root / "maintainer/extensions/knowledge/contract.yaml").is_file())
            self.assertEqual(
                (root / "maintainer/WORKFLOW.md").read_bytes(),
                (self.ROOT / "WORKFLOW.md").read_bytes(),
            )

    def test_unknown_runtime_profile_is_rejected(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            with self.assertRaises(AdapterError):
                build_runtime(
                    self.ROOT,
                    Path(temporary) / "runtime",
                    "0.1.0.dev0",
                    profile="unknown",
                )

    def test_profile_catalog_rejects_dangling_dependencies(self):
        from selfworkflow.catalog import compile_catalog

        compiled = json.loads(compile_catalog(self.ROOT / "catalog").content)
        next(
            entry
            for entry in compiled["catalog"]["entries"]
            if entry["id"] == "workflow-quality"
        )["dependencies"].append("missing-profile-entry")
        content = (json.dumps(compiled, separators=(",", ":"), sort_keys=True) + "\n").encode()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            with mock.patch(
                "selfworkflow.adapters.compile_catalog",
                return_value=SimpleNamespace(content=content),
            ):
                with self.assertRaisesRegex(
                    AdapterError, "runtime-profile-dependency-invalid"
                ):
                    build_runtime(
                        self.ROOT,
                        Path(temporary) / "runtime",
                        "0.1.0.dev0",
                    )

    def test_cli_build_publishes_runtime(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            output = Path(temporary) / "runtime"
            with mock.patch("sys.stdout"):
                result = main([
                    "build", "--repository", str(self.ROOT), "--output", str(output),
                    "--version", "0.1.0.dev0",
                ])
            self.assertEqual(result, 0)
            self.assertTrue((output / "artifact-manifest.json").is_file())
            manifest = json.loads((output / "artifact-manifest.json").read_text())
            self.assertEqual(manifest["profile"], "core")

    def test_cli_build_accepts_explicit_profile(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            output = Path(temporary) / "runtime"
            with mock.patch("sys.stdout"):
                result = main([
                    "build", "--repository", str(self.ROOT), "--output", str(output),
                    "--version", "0.1.0.dev0", "--profile", "knowledge",
                ])
            self.assertEqual(result, 0)
            manifest = json.loads((output / "artifact-manifest.json").read_text())
            self.assertEqual(manifest["profile"], "knowledge")

    def test_cli_build_can_exclude_grill_me(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            output = Path(temporary) / "runtime"
            with mock.patch("sys.stdout"):
                result = main([
                    "build", "--repository", str(self.ROOT), "--output", str(output),
                    "--version", "0.1.0.dev0", "--without-grill-me",
                ])
            self.assertEqual(result, 0)
            manifest = json.loads((output / "artifact-manifest.json").read_text())
            self.assertEqual(manifest["features"], {"grillMe": False})


if __name__ == "__main__":
    unittest.main()
