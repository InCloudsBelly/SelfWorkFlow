"""Runtime and installation behavior for workflow-only Skill maintenance."""

from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml

from selfworkflow.adapters import AdapterError, build_runtime
from selfworkflow.installer import apply_install_plan, create_install_plan


ROOT = Path(__file__).resolve().parents[2]


class AnthropicIntegrationTests(unittest.TestCase):
    def test_source_queries_isolate_ambient_repository_locators(self):
        run = subprocess.run
        upstream = ROOT / "dependencies/upstream/anthropic-skills"
        locators = {"GIT_DIR": "foreign-git", "GIT_WORK_TREE": "foreign-tree", "GIT_INDEX_FILE": "foreign-index"}

        def git_boundary(command, *args, **kwargs):
            source_query = kwargs.get("cwd") == upstream or (
                "ls-files" in command and command[-1] == "dependencies/upstream/anthropic-skills"
            )
            if source_query and any(key in kwargs.get("env", locators) for key in locators):
                return subprocess.CompletedProcess(command, 1, "", "repository locator overrides cwd")
            return run(command, *args, **kwargs)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = Path(temporary) / "runtime"
            with mock.patch("subprocess.run", side_effect=git_boundary):
                build_runtime(ROOT, runtime, "0.1.0.dev0")
            self.assertTrue((runtime / "skills/workflow-skill-maintenance/SKILL.md").is_file())

    def test_parent_gitlink_drift_cannot_publish_a_runtime(self):
        run = subprocess.run

        def wrong_gitlink(command, *args, **kwargs):
            if "ls-files" in command and "--stage" in command and command[-1] == "dependencies/upstream/anthropic-skills":
                return subprocess.CompletedProcess(
                    command, 0,
                    "160000 " + "0" * 40 + " 0\tdependencies/upstream/anthropic-skills\n", "",
                )
            return run(command, *args, **kwargs)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = Path(temporary) / "runtime"
            with mock.patch("subprocess.run", side_effect=wrong_gitlink):
                with self.assertRaisesRegex(AdapterError, "anthropic-skills-source-drift"):
                    build_runtime(ROOT, runtime, "0.1.0.dev0")
            self.assertFalse(runtime.exists())

    def test_runtime_exposes_maintenance_without_discovering_upstream_creator(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = Path(temporary) / "runtime"
            manifest = build_runtime(ROOT, runtime, "0.1.0.dev0")
            entry = "skills/workflow-skill-maintenance/SKILL.md"
            self.assertTrue((runtime / entry).is_file())
            self.assertIn(entry, {item["path"] for item in manifest["files"]})
            reference = runtime / "references/anthropic-skills/skill-creator"
            self.assertTrue((reference / "SKILL.md").is_file())
            self.assertTrue((reference / "LICENSE.txt").is_file())
            self.assertFalse((runtime / "skills/skill-creator").exists())
            self.assertFalse((runtime / "dependencies/upstream/anthropic-skills").exists())

    def test_knowledge_and_maintainer_package_the_same_complete_reference(self):
        upstream = ROOT / "dependencies/upstream/anthropic-skills/skills/skill-creator"
        expected = {path.relative_to(upstream).as_posix(): path.read_bytes()
                    for path in upstream.rglob("*") if path.is_file()}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            for profile in ("knowledge", "maintainer"):
                with self.subTest(profile=profile):
                    runtime = Path(temporary) / profile
                    build_runtime(ROOT, runtime, "0.1.0.dev0", profile=profile)
                    reference = runtime / "references/anthropic-skills/skill-creator"
                    actual = {path.relative_to(reference).as_posix(): path.read_bytes()
                              for path in reference.rglob("*") if path.is_file()}
                    self.assertEqual(actual, expected)
                    self.assertFalse((runtime / "dependencies/upstream/anthropic-skills").exists())

    def test_install_bootstrap_locates_reference_outside_discovery(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            build_runtime(ROOT, artifact, "0.1.0.dev0", profile="knowledge")
            agents, codex, state = root / "agents", root / "codex", root / "state"
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0.dev0")
            self.assertEqual(apply_install_plan(plan, plan["planHash"])["status"], "applied")
            current = json.loads((agents / "selfworkflow/current.json").read_text(encoding="utf-8"))
            snapshot = Path(current["snapshot"])
            self.assertIn(str(snapshot), (codex / "AGENTS.md").read_text(encoding="utf-8"))
            reference = snapshot / "references/anthropic-skills/skill-creator"
            self.assertEqual((reference / "scripts/run_eval.py").read_bytes(),
                             (artifact / "references/anthropic-skills/skill-creator/scripts/run_eval.py").read_bytes())
            self.assertTrue((reference / "eval-viewer/generate_review.py").is_file())
            self.assertTrue((reference / "LICENSE.txt").is_file())
            self.assertFalse((agents / "references").exists())
            discovered = [yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])["name"]
                          for path in (agents / "skills").rglob("SKILL.md")]
            self.assertIn("workflow-skill-maintenance", discovered)
            self.assertNotIn("skill-creator", discovered)

    def test_commit_tree_and_dirty_source_cannot_publish_a_runtime(self):
        run = subprocess.run
        upstream = ROOT / "dependencies/upstream/anthropic-skills"
        cases = (("rev-parse", "HEAD"), ("rev-parse", "HEAD^{tree}"),
                 ("status", "--porcelain=v1", "--untracked-files=all"))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            for number, arguments in enumerate(cases):
                with self.subTest(arguments=arguments):
                    def drift(command, *args, **kwargs):
                        if kwargs.get("cwd") == upstream and tuple(command[-len(arguments):]) == arguments:
                            output = " M scripts/changed.py\n" if arguments[0] == "status" else "0" * 40 + "\n"
                            return subprocess.CompletedProcess(command, 0, output, "")
                        return run(command, *args, **kwargs)
                    runtime = Path(temporary) / str(number)
                    with mock.patch("subprocess.run", side_effect=drift):
                        with self.assertRaisesRegex(AdapterError, "anthropic-skills-source-drift"):
                            build_runtime(ROOT, runtime, "0.1.0.dev0")
                    self.assertFalse(runtime.exists())

    def test_malformed_lock_and_support_file_drift_cannot_publish_a_runtime(self):
        lock_path = ROOT / "dependencies/locks/anthropic-skills.lock.yaml"
        original = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
        read_text = Path.read_text
        variants = [None, {**original, "path": "../outside"}]
        changed = {**original, "selectedSkill": {**original["selectedSkill"],
                   "files": {**original["selectedSkill"]["files"], "agents/analyzer.md": "sha256:" + "0" * 64}}}
        variants.append(changed)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            for number, lock in enumerate(variants):
                with self.subTest(lock=number):
                    def supplied_lock(path, *args, **kwargs):
                        return yaml.safe_dump(lock) if path == lock_path else read_text(path, *args, **kwargs)
                    runtime = Path(temporary) / str(number)
                    error = "anthropic-skills-source-drift" if number == 2 else "anthropic-skills-lock-invalid"
                    with mock.patch.object(Path, "read_text", supplied_lock):
                        with self.assertRaisesRegex(AdapterError, error):
                            build_runtime(ROOT, runtime, "0.1.0.dev0")
                    self.assertFalse(runtime.exists())


if __name__ == "__main__":
    unittest.main()
