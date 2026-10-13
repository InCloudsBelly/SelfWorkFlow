from pathlib import Path
import json
import csv
import os
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from selfworkflow.adapters import AdapterError, build_runtime
from selfworkflow.cli import main
from selfworkflow.v3.catalog import compile_catalog as compile_v3_catalog


class RuntimeSnapshotTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_tea_publishes_one_assessment_entry_and_complete_knowledge_index(self):
        import yaml

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = Path(temporary) / "runtime"
            build_runtime(self.ROOT, runtime, "0.1.0.dev0", profile="knowledge")
            names = [
                yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])["name"]
                for path in (runtime / "skills/tea-quality").rglob("SKILL.md")
            ]
            self.assertEqual(names.count("tea-ci-validation"), 1)
            self.assertEqual(names.count("tea-framework-assessment"), 1)
            references = runtime / "skills/tea-quality/references"
            knowledge = references / "bmod-tea/knowledge"
            with (knowledge / "tea-index.csv").open(encoding="utf-8", newline="") as handle:
                fragments = list(csv.DictReader(handle))
            self.assertTrue(fragments)
            for fragment in fragments:
                self.assertTrue((knowledge / fragment["fragment_file"]).is_file(), fragment)
            self.assertFalse((knowledge.parent / "SKILL.md").exists())
            for entry in references.glob("*/SKILL.md"):
                metadata = yaml.safe_load((entry.parent / "agents/openai.yaml").read_text(encoding="utf-8"))
                self.assertIs(metadata["policy"]["allow_implicit_invocation"], False)

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
            self.assertTrue((root / "first/dependencies/locks/ponytail.lock.yaml").is_file())
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
                "官方 CodeGraph MCP",
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
                    "ponytail-debt", "implement-spec", "tea-framework", "tea-ci",
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
            prompt_files = [
                path for path in runtime_root.rglob("*")
                if path.is_file() and path.relative_to(runtime_root).parts[0] not in {"src", "host"}
            ]
            content = b"".join(path.read_bytes() for path in prompt_files).lower()
            self.assertNotIn(b"caveman", content)
            # The runtime policy may name the pinned gitlink for its allowlist;
            # no upstream tree or source package is copied into the runtime.
            self.assertIn(b"dependencies/upstream/ponytail", policy_path.read_bytes())
            content_without_policy = b"".join(
                path.read_bytes()
                for path in prompt_files
                if (
                    path.is_file()
                    and path != policy_path
                    and path != runtime_root / "dependencies/locks/ponytail.lock.yaml"
                )
            ).lower()
            self.assertNotIn(b"dependencies/upstream/ponytail", content_without_policy)
            self.assertFalse((root / "first/hooks").exists())
            self.assertFalse((root / "first/.codex-plugin").exists())
            self.assertNotIn(b"e:\\", content)
            self.assertNotIn(b"d:\\openwikic7", content)
            for forbidden in ("provider-config.json", ".codegraph", "logs", "cache"):
                self.assertFalse(any(
                    forbidden in {part.casefold() for part in path.relative_to(root / "first").parts}
                    for path in (root / "first").rglob("*")
                ))

    def test_runtime_version_is_closed_before_building(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            for version in ("", " latest", "v1/unsafe", "x" * 65):
                with self.subTest(version=version):
                    with self.assertRaisesRegex(AdapterError, "runtime-version-invalid"):
                        build_runtime(self.ROOT, Path(temporary) / "runtime", version)

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
            for profile in ("knowledge", "maintainer"):
                catalog = compile_v3_catalog(root / profile / "catalog/v3/index.yaml")
                self.assertTrue(catalog.document["catalog"]["modules"])

    @unittest.skipUnless(os.name == "nt", "Windows sharing semantics")
    def test_maintainer_build_avoids_unpublished_upstream_git_sharing_conflicts(self):
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handles = []
        original_copy = shutil.copyfile

        def copy_with_git_reader(source, destination, *args, **kwargs):
            result = original_copy(source, destination, *args, **kwargs)
            if Path(destination).parts[-4:] == ("dependencies", "upstream", "ponytail", ".git"):
                handle = kernel.CreateFileW(str(destination), 0x80000000, 1, None, 3, 0x80, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.append(handle)
            return result

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = Path(temporary) / "runtime"
            try:
                with mock.patch("selfworkflow.adapters.shutil.copyfile", side_effect=copy_with_git_reader):
                    manifest = build_runtime(self.ROOT, runtime, "0.1.0.dev0", profile="maintainer")
                self.assertEqual(manifest["profile"], "maintainer")
                self.assertTrue((runtime / "skills/ponytail/SKILL.md").is_file())
                self.assertFalse((runtime / "dependencies/upstream/ponytail").exists())
            finally:
                for handle in handles:
                    kernel.CloseHandle(handle)

    def test_build_canonicalizes_clean_matt_checkouts_and_rejects_content_drift(self):
        import yaml

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "source"
            subprocess.run(["git", "clone", "-q", "--no-local", "--recurse-submodules", str(self.ROOT), str(source)], check=True)
            tracked = subprocess.run(["git", "ls-files"], cwd=self.ROOT,
                                     capture_output=True, text=True, check=True).stdout.splitlines()
            # Hold main-repository bytes fixed; only the real submodule checkout varies.
            for relative in tracked:
                original = self.ROOT / relative
                if relative.startswith("dependencies/upstream/") or not original.is_file():
                    continue
                destination = source / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(original.read_bytes())
            upstream = source / "dependencies/upstream/matt-pocock-skills"
            lock = yaml.safe_load((source / "dependencies/locks/matt-pocock-skills.lock.yaml").read_text(encoding="utf-8"))
            first = build_runtime(self.ROOT, root / "current", "0.1.0.dev0")
            clean = subprocess.run(["git", "status", "--porcelain"], cwd=upstream,
                                   capture_output=True, text=True, check=True)
            self.assertEqual(clean.stdout.strip(), "")
            second = build_runtime(source, root / "fresh", "0.1.0.dev0")
            self.assertEqual(first["runtimeHash"], second["runtimeHash"])
            import hashlib
            for item in lock["selectedSkills"]:
                published_entry = root / "fresh/skills/matt-pocock" / item["id"] / "SKILL.md"
                self.assertEqual("sha256:" + hashlib.sha256(published_entry.read_bytes()).hexdigest(), item["hash"])
            self.assertEqual("sha256:" + hashlib.sha256((root / "fresh/skills/matt-pocock/LICENSE").read_bytes()).hexdigest(), lock["license"]["hash"])
            ponytail_lock = yaml.safe_load((source / "dependencies/locks/ponytail.lock.yaml").read_text(encoding="utf-8"))
            self.assertEqual("sha256:" + hashlib.sha256((root / "fresh/skills/ponytail/LICENSE").read_bytes()).hexdigest(), ponytail_lock["license"]["hash"])
            for published in (root / "current/skills/matt-pocock").rglob("*"):
                if published.is_file():
                    self.assertEqual(published.read_bytes(), (root / "fresh" / published.relative_to(root / "current")).read_bytes())
            entry = upstream / lock["selectedSkills"][0]["path"] / "SKILL.md"
            entry.write_bytes(entry.read_bytes() + b"\r\nactual content drift\r\n")
            with self.assertRaisesRegex(AdapterError, "matt-skills-source-drift"):
                build_runtime(source, root / "drift", "0.1.0.dev0")

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
