"""Public runtime/install consumers for the selected community Skills."""

import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

from selfworkflow.adapters import AdapterError, build_runtime
from selfworkflow.installer import (
    InstallerError, apply_install_plan, create_install_plan, verify_install,
    create_rollback_plan, apply_rollback_plan,
)


ROOT = Path(__file__).resolve().parents[2]
SKILLS = {"ui-ux-pro-max", "content-research-writer", "obsidian-markdown",
          "obsidian-bases", "json-canvas"}
SOURCES = ("ui-ux-pro-max", "composio-skills", "obsidian-skills")


def refresh_manifest(runtime):
    """Compose the reviewed additive package using the existing manifest format."""
    path = runtime / "artifact-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"] = [
        {"path": item.relative_to(runtime).as_posix(),
         "sha256": hashlib.sha256(item.read_bytes()).hexdigest()}
        for item in sorted(runtime.rglob("*"))
        if item.is_file() and item.name != "artifact-manifest.json"
    ]
    manifest["runtimeHash"] = "sha256:" + hashlib.sha256(
        json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8", newline="\n")
    return manifest


class CommunitySkillIntegrationTests(unittest.TestCase):
    def test_selected_reference_closure_is_available_to_real_consumers(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = Path(temporary) / "runtime"
            manifest = build_runtime(ROOT, runtime, "0.1.0.dev0")
            required = [
                "ui-ux-pro-max/LICENSE",
                "ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py",
                "ui-ux-pro-max/src/ui-ux-pro-max/scripts/reasoning_contract.py",
                "ui-ux-pro-max/src/ui-ux-pro-max/data/charts.csv",
                "composio-skills/content-research-writer/SKILL.md",
                "composio-skills/README.md",
                "obsidian-skills/LICENSE",
                "obsidian-skills/skills/obsidian-markdown/references/PROPERTIES.md",
                "obsidian-skills/skills/obsidian-bases/SKILL.md",
                "obsidian-skills/skills/json-canvas/SKILL.md",
            ]
            published = {item["path"] for item in manifest["files"]}
            for relative in required:
                path = "references/community-skills/" + relative
                self.assertTrue((runtime / path).is_file(), path)
                self.assertIn(path, published)
            script = runtime / "references/community-skills/ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py"
            result = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", str(script),
                 "dashboard", "--domain", "chart", "--json", "--max-results", "1"],
                cwd=temporary, check=True, capture_output=True, text=True, encoding="utf-8",
            )
            output = json.loads(result.stdout)
            self.assertGreater(output["count"], 0)
            self.assertEqual(len(output["results"]), 1)
            self.assertFalse(list(script.parent.rglob("__pycache__")))
            self.assertFalse((Path(temporary) / "design-system").exists())

    def test_core_runtime_publishes_five_bounded_entries(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = Path(temporary) / "runtime"
            build_runtime(ROOT, runtime, "0.1.0.dev0")
            discovered = {
                yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])["name"]
                for path in (runtime / "skills").rglob("SKILL.md")
            }
            self.assertTrue(SKILLS <= discovered, sorted(SKILLS - discovered))
            self.assertNotIn("skill-creator", discovered)
            self.assertNotIn("obsidian-cli", discovered)
            self.assertNotIn("defuddle", discovered)
            self.assertFalse((runtime / "dependencies/upstream/composio-skills").exists())

    def test_knowledge_and_maintainer_keep_the_selected_closure_outside_discovery(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            for profile in ("knowledge", "maintainer"):
                with self.subTest(profile=profile):
                    runtime = Path(temporary) / profile
                    build_runtime(ROOT, runtime, "0.1.0.dev0", profile=profile)
                    for source_id in SOURCES:
                        lock = yaml.safe_load((ROOT / f"dependencies/locks/{source_id}.lock.yaml").read_text(encoding="utf-8"))
                        reference = runtime / "references/community-skills" / source_id
                        actual = {path.relative_to(reference).as_posix():
                                  "sha256:" + hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                                  for path in reference.rglob("*") if path.is_file()}
                        self.assertEqual(actual, lock["files"])
                        self.assertFalse((runtime / "dependencies/upstream" / source_id).exists())
                    discovered = {
                        yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])["name"]
                        for path in (runtime / "skills").rglob("SKILL.md")
                    }
                    self.assertTrue(SKILLS <= discovered)
                    self.assertFalse({"obsidian-cli", "defuddle", "skill-creator"} & discovered)

    def test_parent_commit_tree_and_dirty_drift_cannot_publish_any_source(self):
        run = subprocess.run
        cases = (("gitlink",), ("rev-parse", "HEAD"), ("rev-parse", "HEAD^{tree}"),
                 ("status", "--porcelain=v1", "--untracked-files=all"))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            for source_id in SOURCES:
                relative = f"dependencies/upstream/{source_id}"
                for number, arguments in enumerate(cases):
                    with self.subTest(source=source_id, query=arguments):
                        def drift(command, *args, **kwargs):
                            if arguments == ("gitlink",):
                                if "ls-files" in command and command[-1] == relative:
                                    return subprocess.CompletedProcess(command, 0, f"160000 {'0' * 40} 0\t{relative}\n", "")
                            elif kwargs.get("cwd") == ROOT / relative and tuple(command[-len(arguments):]) == arguments:
                                output = " M changed.py\n" if arguments[0] == "status" else "0" * 40 + "\n"
                                return subprocess.CompletedProcess(command, 0, output, "")
                            return run(command, *args, **kwargs)
                        runtime = Path(temporary) / f"{source_id}-{number}"
                        with mock.patch("subprocess.run", side_effect=drift):
                            with self.assertRaisesRegex(AdapterError, "community-skills-source-drift"):
                                build_runtime(ROOT, runtime, "0.1.0.dev0")
                        self.assertFalse(runtime.exists())

    def test_malformed_and_unsafe_locks_fail_before_publication(self):
        read_text = Path.read_text
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            for source_id in SOURCES:
                lock_path = ROOT / f"dependencies/locks/{source_id}.lock.yaml"
                original = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
                variants = [None, {**original, "schemaVersion": True},
                            {**original, "path": "../outside"},
                            {**original, "files": {"../outside": "sha256:" + "0" * 64}}]
                for number, lock in enumerate(variants):
                    with self.subTest(source=source_id, variant=number):
                        def supplied(path, *args, **kwargs):
                            return yaml.safe_dump(lock) if path == lock_path else read_text(path, *args, **kwargs)
                        runtime = Path(temporary) / f"{source_id}-{number}"
                        with mock.patch.object(Path, "read_text", supplied):
                            with self.assertRaisesRegex(AdapterError, "community-skills-lock-invalid"):
                                build_runtime(ROOT, runtime, "0.1.0.dev0")
                        self.assertFalse(runtime.exists())

    def test_missing_source_and_support_file_hash_drift_fail_without_publication(self):
        run = subprocess.run
        read_text = Path.read_text
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            for source_id in SOURCES:
                upstream = ROOT / f"dependencies/upstream/{source_id}"
                lock_path = ROOT / f"dependencies/locks/{source_id}.lock.yaml"
                original = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
                support = next(name for name in original["files"] if name != original["license"]["path"])
                changed = {**original, "files": {**original["files"], support: "sha256:" + "0" * 64}}
                def supplied(path, *args, **kwargs):
                    return yaml.safe_dump(changed) if path == lock_path else read_text(path, *args, **kwargs)
                with self.subTest(source=source_id, fault="hash"):
                    runtime = Path(temporary) / f"{source_id}-hash"
                    with mock.patch.object(Path, "read_text", supplied):
                        with self.assertRaisesRegex(AdapterError, "community-skills-source-drift"):
                            build_runtime(ROOT, runtime, "0.1.0.dev0")
                    self.assertFalse(runtime.exists())
                def unavailable(command, *args, **kwargs):
                    if kwargs.get("cwd") == upstream:
                        return subprocess.CompletedProcess(command, 128, "", "source unavailable")
                    return run(command, *args, **kwargs)
                with self.subTest(source=source_id, fault="unavailable"):
                    runtime = Path(temporary) / f"{source_id}-missing"
                    with mock.patch("subprocess.run", side_effect=unavailable):
                        with self.assertRaisesRegex(AdapterError, "community-skills-source-invalid"):
                            build_runtime(ROOT, runtime, "0.1.0.dev0")
                    self.assertFalse(runtime.exists())

    def test_new_source_queries_use_the_isolated_git_transport(self):
        run = subprocess.run
        seen = set()
        locators = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}
        def boundary(command, *args, **kwargs):
            for source_id in SOURCES:
                relative = f"dependencies/upstream/{source_id}"
                if kwargs.get("cwd") == ROOT / relative or ("ls-files" in command and command[-1] == relative):
                    seen.add(source_id)
                    # A missing env inherits hostile locators; explicit transport must remove them.
                    if locators & set(kwargs.get("env", {name: "foreign" for name in locators})):
                        return subprocess.CompletedProcess(command, 1, "", "foreign repository locator")
            return run(command, *args, **kwargs)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            with mock.patch("subprocess.run", side_effect=boundary):
                runtime = Path(temporary) / "runtime"
                build_runtime(ROOT, runtime, "0.1.0.dev0")
            self.assertEqual(seen, set(SOURCES))
            self.assertTrue((runtime / "skills/json-canvas/SKILL.md").is_file())

    def test_additive_package_preserves_host_installs_references_and_rolls_back(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            selected = root / "selected"
            build_runtime(ROOT, selected, "0.1.0.dev0", profile="knowledge")
            baseline = root / "baseline"
            shutil.copytree(selected, baseline)
            for skill in SKILLS:
                shutil.rmtree(baseline / "skills" / skill)
            shutil.rmtree(baseline / "references/community-skills")
            for source_id in SOURCES:
                (baseline / f"dependencies/locks/{source_id}.lock.yaml").unlink()
            refresh_manifest(baseline)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            launcher = root / "bin/selfworkflow.cmd"
            first_plan = create_install_plan(baseline, agents, codex, state, "0.1.0.dev0",
                                             host_launcher=launcher, host_python=sys.executable)
            first = apply_install_plan(first_plan, first_plan["planHash"])
            self.assertEqual(verify_install(first["manifestPath"])["status"], "verified")
            old_pointer = (agents / "selfworkflow/current.json").read_bytes()
            old = json.loads(old_pointer)
            old_snapshot = Path(old["snapshot"])
            old_bytes = {path.relative_to(old_snapshot).as_posix(): path.read_bytes()
                         for path in old_snapshot.rglob("*") if path.is_file()}
            additive = root / "additive"
            shutil.copytree(old_snapshot, additive)
            for skill in SKILLS:
                shutil.copytree(selected / "skills" / skill, additive / "skills" / skill)
            shutil.copytree(selected / "references/community-skills", additive / "references/community-skills")
            for source_id in SOURCES:
                relative = f"dependencies/locks/{source_id}.lock.yaml"
                shutil.copyfile(selected / relative, additive / relative)
            manifest = refresh_manifest(additive)
            for relative, content in old_bytes.items():
                if relative != "artifact-manifest.json":
                    self.assertEqual((additive / relative).read_bytes(), content, relative)
            self.assertEqual(manifest["profile"], "knowledge")
            self.assertEqual(manifest["features"], json.loads(old_bytes["artifact-manifest.json"])["features"])
            second_plan = create_install_plan(additive, agents, codex, state, "0.1.0.dev0",
                                              host_launcher=launcher, host_python=sys.executable)
            second = apply_install_plan(second_plan, second_plan["planHash"])
            self.assertEqual(verify_install(second["manifestPath"])["status"], "verified")
            receipt = json.loads(Path(second["manifestPath"]).read_text(encoding="utf-8"))
            self.assertEqual(Path(receipt["hostLauncher"]["path"]), launcher.resolve())
            self.assertEqual(Path(receipt["hostLauncher"]["pythonExecutable"]), Path(sys.executable).resolve())
            current = json.loads((agents / "selfworkflow/current.json").read_text(encoding="utf-8"))
            snapshot = Path(current["snapshot"])
            self.assertNotEqual(current["artifactHash"], old["artifactHash"])
            self.assertIn(str(snapshot), (codex / "AGENTS.md").read_text(encoding="utf-8"))
            for skill in SKILLS:
                self.assertEqual((agents / "skills" / skill / "SKILL.md").read_bytes(),
                                 (snapshot / "skills" / skill / "SKILL.md").read_bytes())
            for source_id in SOURCES:
                lock = yaml.safe_load((snapshot / f"dependencies/locks/{source_id}.lock.yaml").read_text(encoding="utf-8"))
                for name, expected in lock["files"].items():
                    data = (snapshot / "references/community-skills" / source_id / name).read_bytes()
                    self.assertEqual("sha256:" + hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest(), expected)
            rollback = create_rollback_plan(second["transactionPath"])
            apply_rollback_plan(rollback, rollback["planHash"])
            self.assertEqual((agents / "selfworkflow/current.json").read_bytes(), old_pointer)
            self.assertEqual(verify_install(first["manifestPath"])["status"], "verified")
            self.assertFalse(any((agents / "skills" / skill / "SKILL.md").exists() for skill in SKILLS))
            for relative, content in old_bytes.items():
                self.assertEqual((old_snapshot / relative).read_bytes(), content, relative)

    def test_preexisting_managed_skill_edit_blocks_receipt_preflight(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            build_runtime(ROOT, artifact, "0.1.0.dev0", profile="knowledge")
            agents, codex, state = root / "agents", root / "codex", root / "state"
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0.dev0")
            result = apply_install_plan(plan, plan["planHash"])
            self.assertEqual(verify_install(result["manifestPath"])["status"], "verified")
            identity = (state / "current-manifest.json").read_bytes()
            entry = agents / "skills/workflow-skill-maintenance/SKILL.md"
            changed = entry.read_bytes() + b"\nUser local change\n"
            entry.write_bytes(changed)
            with self.assertRaisesRegex(InstallerError, "installed-file-drift"):
                verify_install(result["manifestPath"])
            self.assertEqual(entry.read_bytes(), changed)
            self.assertEqual((state / "current-manifest.json").read_bytes(), identity)


if __name__ == "__main__":
    unittest.main()
