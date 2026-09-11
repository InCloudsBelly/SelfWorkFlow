from __future__ import annotations

import configparser
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from selfworkflow.adapters import AdapterError, _copy_matt_skills


class MattSkillsFoundationTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    REQUIRED_SKILLS = {
        "grill-me",
        "grilling",
        "codebase-design",
        "implement",
        "tdd",
        "diagnosing-bugs",
        "code-review",
        "to-spec",
        "to-tickets",
        "grill-with-docs",
    }

    def _lock(self) -> dict[str, object]:
        return yaml.safe_load(
            (self.ROOT / "dependencies/locks/matt-pocock-skills.lock.yaml").read_text(
                encoding="utf-8"
            )
        )

    def test_submodule_and_selected_skills_are_commit_and_hash_bound(self):
        modules = configparser.ConfigParser()
        modules.read(self.ROOT / ".gitmodules", encoding="utf-8")
        section = 'submodule "dependencies/upstream/matt-pocock-skills"'
        self.assertTrue(modules.has_section(section))
        self.assertEqual(
            modules[section]["url"], "https://github.com/mattpocock/skills.git"
        )

        lock = self._lock()
        self.assertEqual(lock["schemaVersion"], 1)
        self.assertEqual(lock["canonicalUrl"], "https://github.com/mattpocock/skills.git")
        self.assertEqual(lock["path"], "dependencies/upstream/matt-pocock-skills")
        self.assertRegex(lock["gitlinkCommit"], r"^[0-9a-f]{40}$")
        source = self.ROOT / lock["path"]
        self.assertTrue(source.is_dir())
        head = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        self.assertEqual(head, lock["gitlinkCommit"])

        selected = {item["id"]: item for item in lock["selectedSkills"]}
        self.assertEqual(set(selected), self.REQUIRED_SKILLS)
        for skill_id, item in selected.items():
            skill = source / item["path"] / "SKILL.md"
            self.assertTrue(skill.is_file(), skill_id)
            digest = "sha256:" + hashlib.sha256(skill.read_bytes()).hexdigest()
            self.assertEqual(digest, item["hash"], skill_id)

    def test_runtime_contains_only_curated_matt_skills(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = Path(temporary) / "runtime"
            _copy_matt_skills(self.ROOT, runtime, include_grill_me=True)

            installed = {
                path.parent.name
                for path in (runtime / "skills/matt-pocock").glob("*/SKILL.md")
            }
            self.assertEqual(installed, self.REQUIRED_SKILLS)
            self.assertFalse((runtime / "skills/grill-me").exists())
            self.assertTrue(
                (self.ROOT / "dependencies/locks/matt-pocock-skills.lock.yaml").is_file()
            )

    def test_runtime_rejects_dirty_unlocked_matt_skill_support_files(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            source = Path(temporary) / "source"
            lock_target = source / "dependencies/locks/matt-pocock-skills.lock.yaml"
            lock_target.parent.mkdir(parents=True)
            lock_target.write_bytes(
                (self.ROOT / "dependencies/locks/matt-pocock-skills.lock.yaml").read_bytes()
            )
            upstream = source / "dependencies/upstream/matt-pocock-skills"
            upstream.parent.mkdir(parents=True)
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--no-local",
                    str(self.ROOT / "dependencies/upstream/matt-pocock-skills"),
                    str(upstream),
                ],
                check=True,
                capture_output=True,
            )
            support_file = upstream / "skills/engineering/tdd/tests.md"
            self.assertTrue(support_file.is_file())
            support_file.write_text("unlocked drift\n", encoding="utf-8")

            with self.assertRaisesRegex(AdapterError, "matt-skills-source-drift"):
                _copy_matt_skills(
                    source, Path(temporary) / "runtime", include_grill_me=True
                )

    def test_default_modules_use_matt_skills_and_native_verification(self):
        catalog = yaml.safe_load((self.ROOT / "catalog/modules.yaml").read_text("utf-8"))
        modules = {item["id"]: item for item in catalog["modules"]}
        expected = {
            "design-grilling": "matt-pocock:grilling",
            "design-codebase": "matt-pocock:codebase-design",
            "implement-matt": "matt-pocock:implement",
            "implement-tdd": "matt-pocock:tdd",
            "implement-diagnosing-bugs": "matt-pocock:diagnosing-bugs",
            "review-code-review": "matt-pocock:code-review",
            "verify-execution": "selfworkflow:testing-review-quality",
        }
        self.assertEqual(
            {module_id: modules[module_id]["invocation"]["ref"] for module_id in expected},
            expected,
        )
        default_refs = [
            item["invocation"]["ref"]
            for item in modules.values()
            if item["activation"] != "explicit"
        ]
        self.assertFalse(any(ref.startswith("superpowers:") for ref in default_refs))

    def test_v3_routes_matt_core_without_losing_adaptive_modules(self):
        index = yaml.safe_load((self.ROOT / "catalog/v3/index.yaml").read_text("utf-8"))
        module_ids = {item["id"] for item in index["modules"]}
        for expected in (
            "design-grilling",
            "design-codebase",
            "implement-matt",
            "implement-tdd",
            "implement-diagnosing-bugs",
            "review-code-review",
            "tea-test-design",
            "cpp-core",
            "knowledge-update",
        ):
            self.assertIn(expected, module_ids)

        workflow = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        self.assertIn("Full 和 Deep 必须加载 TEA", workflow)
        self.assertIn("CodeGraph", workflow)
        self.assertIn("过期", workflow)
        self.assertIn("Caveman lite 常驻", workflow)
        self.assertNotIn("只读取当前阶段需要的 Superpowers Skill", workflow)

        active_workflow = (self.ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        self.assertIn("primary code-reading", active_workflow)
        self.assertIn("保留 `rg` 做精确文本确认", active_workflow)
        cpp_skill = (self.ROOT / "skills/cpp-core/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("代码阅读优先级", cpp_skill)
        self.assertIn("CodeGraph 缺失、过期", cpp_skill)
        self.assertIn("新对话第一次命中代码任务", cpp_skill)
        self.assertIn("本对话偏好", cpp_skill)
        provider_doc = (self.ROOT / "docs/providers/codegraph.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Conversation preflight", provider_doc)

    def test_installer_defaults_to_matt_without_superpowers_or_duplicate_grill(self):
        installer = (self.ROOT / "scripts/install-selfworkflow.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('[string]$SuperpowersChoice = "Skip"', installer)
        self.assertNotIn('writeCapability = if ($SuperpowersChoice', installer)
        self.assertNotIn('$RequiredSuperpowersSkills', installer)
        self.assertNotIn('$GrillMeChoice', installer)
        self.assertIn('matt-pocock-skills.lock.yaml', installer)


if __name__ == "__main__":
    unittest.main()
