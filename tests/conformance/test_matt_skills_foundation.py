from __future__ import annotations

import configparser
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from selfworkflow.adapters import AdapterError, _copy_matt_skills
from selfworkflow.implement_spec import ticket_dag_hash


class MattSkillsFoundationTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    REQUIRED_SKILLS = {
        "grill-me",
        "grilling",
        "codebase-design",
        "implement",
        "implement-spec",
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

    def test_optional_extensions_are_explicit_and_hash_bound(self):
        expected = {
            "tea-framework": ("planned", "plan.assessment", "test-quality", "skills/tea-quality/assessments/framework/SKILL.md"),
            "tea-ci": ("verified", "verify.ci", "test-quality", "skills/tea-quality/assessments/ci/SKILL.md"),
            "ponytail-debt": ("reviewed", "review.debt", "code", "skills/ponytail-debt/SKILL.md"),
            "implement-spec": ("implemented", "implement.spec", "workflow", "skills/implement-spec/SKILL.md"),
        }
        v2 = yaml.safe_load((self.ROOT / "catalog/modules.yaml").read_text("utf-8"))
        modules = {item["id"]: item for item in v2["modules"]}
        entries = {}
        for path in (self.ROOT / "catalog/domains").glob("*.yaml"):
            entries.update({item["id"]: item for item in yaml.safe_load(path.read_text("utf-8"))["entries"]})
        index = yaml.safe_load((self.ROOT / "catalog/v3/index.yaml").read_text("utf-8"))
        refs = {item["id"]: item for item in index["modules"]}
        debt_lock = yaml.safe_load((self.ROOT / "dependencies/locks/ponytail.lock.yaml").read_text("utf-8"))
        debt_hash = next(item["runtimeHash"] for item in debt_lock["selectedSkills"] if item["id"] == "ponytail-debt")
        for module_id, (stage, slot, domain, source) in expected.items():
            with self.subTest(module=module_id):
                self.assertIn(module_id, modules)
                module = modules[module_id]
                self.assertEqual(set(module["supportEvidence"].values()), {"supported"})
                self.assertEqual(module["activation"], "explicit")
                self.assertEqual((module["stage"], module["slot"]), (stage, slot))
                entry = entries[module["sourceEntryId"]]
                self.assertEqual(entry["supportStatus"], "supported")
                self.assertFalse(entry["mandatory"])
                self.assertTrue(all(not value for value in entry["selectors"].values()))
                self.assertEqual(entry["triggers"], [])
                self.assertIn(module_id, refs)
                path = self.ROOT / "catalog/v3" / refs[module_id]["ref"]
                self.assertEqual(refs[module_id]["hash"], "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
                v3 = yaml.safe_load(path.read_text("utf-8"))
                self.assertEqual((v3["stage"], v3["slot"]), (stage, slot))
                self.assertEqual(v3["selectionMode"], "static")
                self.assertEqual(set(v3["supportEvidence"].values()), {"supported"})
                self.assertEqual(v3["invocation"], module["invocation"])
                source_hash = debt_hash if module_id == "ponytail-debt" else "sha256:" + hashlib.sha256((self.ROOT / source).read_bytes()).hexdigest()
                self.assertEqual(v3["sourceHash"], source_hash)
                domain_ref = next(item for item in index["domains"] if item["id"] == domain)
                domain_path = self.ROOT / "catalog/v3" / domain_ref["ref"]
                self.assertEqual(domain_ref["hash"], "sha256:" + hashlib.sha256(domain_path.read_bytes()).hexdigest())
                self.assertIn(module_id, yaml.safe_load(domain_path.read_text("utf-8"))["modules"])

    def test_v2_optional_routes_require_explicit_selection_and_host_capabilities(self):
        from selfworkflow.router import ModuleRouteRequest, route_modules

        # Exercise the router with current module bytes; Git revision provenance
        # is checked separately by the catalog compiler after integration.
        catalog = yaml.safe_load((self.ROOT / "catalog/modules.yaml").read_text("utf-8"))
        payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        envelope = {"schemaVersion": 2, "catalog": catalog,
                    "catalogHash": "sha256:" + hashlib.sha256(payload).hexdigest()}
        ids = {"tea-framework", "tea-ci", "ponytail-debt", "implement-spec"}
        for module in catalog["modules"]:
            if module["id"] not in ids:
                continue
            with self.subTest(module=module["id"]):
                common = dict(slot_id=module["slot"], cardinality="zero-or-one",
                              operation_type=module["when"]["operationTypes"][0],
                              strength="Light", write_task=module["id"] == "implement-spec")
                capabilities = {name: "supported" for name in module["requiredCapabilities"]}
                implicit = route_modules(envelope, ModuleRouteRequest(**common, capability_states=capabilities))
                self.assertEqual(implicit.selected_modules, ())
                if module["id"] == "implement-spec":
                    tickets = [
                        {"id": "ticket-a", "dependencies": [], "acceptanceHash": "sha256:" + "a" * 64},
                        {"id": "ticket-b", "dependencies": ["ticket-a"], "acceptanceHash": "sha256:" + "b" * 64},
                    ]
                    common.update(
                        implement_spec_evidence={
                            "specHash": "sha256:" + "c" * 64,
                            "tickets": tickets,
                            "ticketDagHash": ticket_dag_hash(tickets),
                            "planReviewHash": "sha256:" + "d" * 64,
                            "implementationConfirmationHash": "sha256:" + "e" * 64,
                            "independentAgentsHash": "sha256:" + "f" * 64,
                            "independentReviewHash": "sha256:" + "1" * 64,
                            "gitPermissionsHash": "sha256:" + "2" * 64,
                            "planReviewStatus": "passed",
                            "implementationConfirmationStatus": "confirmed",
                            "independentAgentsStatus": "supported",
                            "independentReviewStatus": "supported",
                            "gitPermissionsStatus": "confirmed",
                        },
                        durable_spec=True,
                        requirements_maturity="approved",
                    )
                explicit = route_modules(envelope, ModuleRouteRequest(
                    **common, explicit_module_ids=(module["id"],), capability_states=capabilities))
                self.assertEqual(explicit.status, "routed")
                self.assertEqual(explicit.selected_modules, (module["id"],))
                missing = route_modules(envelope, ModuleRouteRequest(
                    **common, explicit_module_ids=(module["id"],), capability_states={}))
                self.assertEqual(missing.status, "paused")
                self.assertIn("required-capability-unavailable", missing.reason_codes)

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
            "design-grill-me": "matt-pocock:grilling",
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
        self.assertIn("Ponytail", workflow)
        self.assertIn("非代码任务不自动加载", workflow)
        self.assertNotIn("Caveman", workflow)
        self.assertNotIn("只读取当前阶段需要的 Superpowers Skill", workflow)

        active_workflow = (self.ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        self.assertIn("代码/C++/UE/跨层行为", active_workflow)
        self.assertIn("codegraph-read.md", active_workflow)
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
        self.assertIn("CodeGraph 是 SelfWorkFlow 唯一的代码图 Provider", provider_doc)
        self.assertIn("`rg` 不是默认阅读入口", provider_doc)
        self.assertIn("CodeGraph", provider_doc)

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
