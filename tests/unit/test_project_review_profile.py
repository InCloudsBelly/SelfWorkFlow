import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def _profile(skill_path: str, content_hash: str, *, required=True):
    return {
        "schemaVersion": 1,
        "additionalReviewSkills": [{
            "id": "project.review",
            "path": skill_path,
            "contentHash": content_hash,
            "required": required,
        }],
    }


class ProjectReviewProfileTests(unittest.TestCase):
    @staticmethod
    def _run_cli(*arguments):
        from selfworkflow.cli import main

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(list(arguments))
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_missing_profile_is_absent_without_scanning(self):
        from selfworkflow.project_review import load_project_review_profile

        with tempfile.TemporaryDirectory() as directory:
            result = load_project_review_profile(directory)
        self.assertEqual(result.status, "absent")
        self.assertEqual(result.skills, ())

    def test_unsealed_profile_cannot_issue_review_context(self):
        from selfworkflow.project_review import (
            ProjectReviewProfile, ProjectReviewProfileError, build_code_review_context,
        )

        profile = ProjectReviewProfile(
            status="loaded", project_root="C:\\project", profile_path=None,
            profile_hash=None, schema_hash=None, binding_hash="sha256:" + "a" * 64,
            skills=(), issues=(), blocking=False,
        )
        with self.assertRaises(ProjectReviewProfileError):
            build_code_review_context(
                profile, strength="Full", is_code_task=True,
                conversation_id="unsealed-profile",
            )

    def test_valid_profile_preserves_order_and_binds_content_hash(self):
        from selfworkflow.project_review import load_project_review_profile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / ".agents" / "skills" / "project" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            content = b"---\nname: project-review\n---\nReview project behavior.\n"
            skill.write_bytes(content)
            digest = "sha256:" + hashlib.sha256(content).hexdigest()
            profile = _profile(".agents/skills/project/SKILL.md", digest)
            (root / ".selfworkflow").mkdir()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps(profile), encoding="utf-8"
            )

            result = load_project_review_profile(root)

        self.assertEqual(result.status, "loaded")
        self.assertEqual(result.skills[0].id, "project.review")
        self.assertEqual(result.skills[0].content_hash, digest)

    def test_both_review_axes_receive_the_same_ordered_manifest(self):
        from selfworkflow.project_review import build_code_review_context, load_project_review_profile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "skills"
            skill_dir.mkdir()
            first = b"first"
            second = b"second"
            (skill_dir / "first.md").write_bytes(first)
            (skill_dir / "second.md").write_bytes(second)
            profile = {
                "schemaVersion": 1,
                "additionalReviewSkills": [
                    {"id": "project.first", "path": "skills/first.md", "contentHash": "sha256:" + hashlib.sha256(first).hexdigest(), "required": True},
                    {"id": "project.second", "path": "skills/second.md", "contentHash": "sha256:" + hashlib.sha256(second).hexdigest(), "required": False},
                ],
            }
            (root / ".selfworkflow").mkdir()
            (root / ".selfworkflow" / "review.yaml").write_text(json.dumps(profile), encoding="utf-8")
            result = load_project_review_profile(root)

        manifests = result.reviewer_manifests()
        self.assertEqual(result.status, "loaded")
        self.assertEqual(manifests["standards"], manifests["spec"])
        self.assertEqual([item["id"] for item in manifests["standards"]], ["project.first", "project.second"])
        self.assertEqual(result.reviewer_skill_bytes()["standards"], result.reviewer_skill_bytes()["spec"])
        self.assertEqual(result.reviewer_skill_bytes()["standards"], (first, second))
        context = build_code_review_context(
            result, strength="Full", is_code_task=True, conversation_id="conversation-1"
        )
        self.assertEqual(
            context["reviewers"]["standards"], context["reviewers"]["spec"]
        )
        self.assertEqual(context["status"], "loaded")

    def test_light_and_non_code_review_do_not_load_project_skills(self):
        from selfworkflow.project_review import build_code_review_context, load_project_review_profile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "review.md").write_text("review", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            digest = "sha256:" + hashlib.sha256(b"review").hexdigest()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps(_profile("review.md", digest)), encoding="utf-8"
            )
            profile = load_project_review_profile(root)

        for strength, is_code_task in (("Light", True), ("Full", False)):
            with self.subTest(strength=strength, is_code_task=is_code_task):
                context = build_code_review_context(
                    profile, strength=strength, is_code_task=is_code_task, conversation_id=None
                )
                self.assertEqual(context["status"], "not-applicable")
                self.assertEqual(context["reviewers"]["standards"]["manifest"], ())

    def test_binding_changes_for_all_semantic_profile_inputs(self):
        from selfworkflow.project_review import load_project_review_profile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / ".agents" / "skills" / "project"
            skill_dir.mkdir(parents=True)
            first = b"first"
            second = b"second"
            (skill_dir / "first.md").write_bytes(first)
            (skill_dir / "second.md").write_bytes(second)
            digest_first = "sha256:" + hashlib.sha256(first).hexdigest()
            digest_second = "sha256:" + hashlib.sha256(second).hexdigest()
            profile_dir = root / ".selfworkflow"
            profile_dir.mkdir()
            profile = {
                "schemaVersion": 1,
                "additionalReviewSkills": [
                    {"id": "project.first", "path": ".agents/skills/project/first.md", "contentHash": digest_first, "required": True},
                    {"id": "project.second", "path": ".agents/skills/project/second.md", "contentHash": digest_second, "required": False},
                ],
            }
            profile_path = profile_dir / "review.yaml"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            original = load_project_review_profile(root)
            variants = []
            reordered = json.loads(json.dumps(profile))
            reordered["additionalReviewSkills"].reverse()
            variants.append(reordered)
            required_changed = json.loads(json.dumps(profile))
            required_changed["additionalReviewSkills"][0]["required"] = False
            variants.append(required_changed)
            path_changed = json.loads(json.dumps(profile))
            path_changed["additionalReviewSkills"][0]["path"] = ".agents/skills/project/second.md"
            variants.append(path_changed)
            hash_changed = json.loads(json.dumps(profile))
            hash_changed["additionalReviewSkills"][0]["contentHash"] = digest_second
            variants.append(hash_changed)
            changed = []
            for variant in variants:
                profile_path.write_text(json.dumps(variant), encoding="utf-8")
                changed.append(load_project_review_profile(root))

        self.assertTrue(all(item.status == "loaded" for item in changed[:2]))
        self.assertTrue(all(item.profile_hash != original.profile_hash for item in changed))
        self.assertTrue(all(item.binding_hash != original.binding_hash for item in changed))

    def test_duplicate_ids_and_protected_rule_fields_fail_closed(self):
        from selfworkflow.project_review import ProjectReviewProfileError, load_project_review_profile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".selfworkflow").mkdir()
            duplicate = {
                "schemaVersion": 1,
                "additionalReviewSkills": [
                    {"id": "project.same", "path": "one.md", "contentHash": "sha256:" + "0" * 64, "required": True},
                    {"id": "project.same", "path": "two.md", "contentHash": "sha256:" + "1" * 64, "required": True},
                ],
            }
            profile_path = root / ".selfworkflow" / "review.yaml"
            profile_path.write_text(json.dumps(duplicate), encoding="utf-8")
            with self.assertRaises(ProjectReviewProfileError):
                load_project_review_profile(root)

            protected = _profile("one.md", "sha256:" + "0" * 64)
            protected["protectedRules"] = {"allow": True}
            profile_path.write_text(json.dumps(protected), encoding="utf-8")
            with self.assertRaises(ProjectReviewProfileError):
                load_project_review_profile(root)

    def test_unsafe_paths_fail_closed(self):
        from selfworkflow.project_review import ProjectReviewProfileError, load_project_review_profile

        invalid_paths = (
            "../secret.md", "a/..", "C:/secret.md", "\\secret.md", "a\\b.md",
            "CON.md", "folder/file. ", "folder/a?b.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".selfworkflow").mkdir()
            profile_path = root / ".selfworkflow" / "review.yaml"
            for unsafe_path in invalid_paths:
                profile_path.write_text(
                    json.dumps(_profile(unsafe_path, "sha256:" + "0" * 64)), encoding="utf-8"
                )
                with self.subTest(path=unsafe_path), self.assertRaises(ProjectReviewProfileError):
                    load_project_review_profile(root)

    def test_schema_rejects_unsafe_paths_before_loader(self):
        schema = json.loads(
            (ROOT / "schemas" / "project-review-profile.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        base = _profile("review.md", "sha256:" + "0" * 64)
        for unsafe_path in ("../secret.md", "a/..", "C:/secret.md", "\\secret.md", "a\\b.md"):
            base["additionalReviewSkills"][0]["path"] = unsafe_path
            with self.subTest(path=unsafe_path):
                self.assertTrue(list(validator.iter_errors(base)))

    @unittest.skipUnless(os.name == "nt", "Windows reparse-point semantics required")
    def test_reparse_skill_path_fails_closed(self):
        from selfworkflow.project_review import ProjectReviewProfileError, load_project_review_profile

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            outside_path = Path(outside)
            (outside_path / "SKILL.md").write_text("outside", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            try:
                os.symlink(str(outside_path), str(root / "linked"), target_is_directory=True)
            except OSError:
                self.skipTest("creating a Windows symlink requires unavailable privilege")
            profile_path = root / ".selfworkflow" / "review.yaml"
            profile_path.write_text(
                json.dumps(_profile("linked/SKILL.md", "sha256:" + "0" * 64)), encoding="utf-8"
            )
            with self.assertRaises(ProjectReviewProfileError):
                load_project_review_profile(root)

            root_link = root.parent / (root.name + "-link")
            try:
                os.symlink(str(root), str(root_link), target_is_directory=True)
            except OSError:
                self.skipTest("creating a Windows symlink requires unavailable privilege")
            with self.assertRaises(ProjectReviewProfileError):
                load_project_review_profile(root_link)

    def test_hash_drift_is_unverified_and_redacted(self):
        from selfworkflow.project_review import build_code_review_context, load_project_review_profile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "review.md"
            skill.write_text("actual", encoding="utf-8")
            profile_dir = root / ".selfworkflow"
            profile_dir.mkdir()
            profile_dir.joinpath("review.yaml").write_text(
                json.dumps(_profile("review.md", "sha256:" + "0" * 64)), encoding="utf-8"
            )
            result = load_project_review_profile(root)

        self.assertEqual(result.status, "unverified")
        self.assertTrue(result.blocking)
        self.assertEqual(result.issues, ("skill-hash-mismatch:project.review",))
        self.assertNotIn("actual", json.dumps(result.as_dict()))
        context = build_code_review_context(
            result, strength="Full", is_code_task=True, conversation_id="conversation-required"
        )
        self.assertTrue(context["blocking"])
        self.assertEqual(context["reviewers"]["standards"]["manifest"], ())

    def test_optional_skill_drift_keeps_verified_skills_and_does_not_block(self):
        from selfworkflow.project_review import build_code_review_context, load_project_review_profile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "valid.md").write_text("valid", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            profile = {
                "schemaVersion": 1,
                "additionalReviewSkills": [
                    {"id": "project.valid", "path": "valid.md", "contentHash": "sha256:" + hashlib.sha256(b"valid").hexdigest(), "required": True},
                    {"id": "project.optional", "path": "missing.md", "contentHash": "sha256:" + "0" * 64, "required": False},
                ],
            }
            (root / ".selfworkflow" / "review.yaml").write_text(json.dumps(profile), encoding="utf-8")
            result = load_project_review_profile(root)

        self.assertEqual(result.status, "unverified")
        self.assertFalse(result.blocking)
        self.assertEqual([item["id"] for item in result.reviewer_manifest()], ["project.valid"])
        context = build_code_review_context(
            result, strength="Deep", is_code_task=True, conversation_id="conversation-optional"
        )
        self.assertFalse(context["blocking"])
        self.assertEqual(
            context["reviewers"]["standards"], context["reviewers"]["spec"]
        )

    def test_session_binding_changes_with_conversation_identity(self):
        from selfworkflow.project_review import load_project_review_profile, session_binding_hash

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".selfworkflow").mkdir()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps(_profile("missing.md", "sha256:" + "0" * 64, required=False)), encoding="utf-8"
            )
            profile = load_project_review_profile(root)

        self.assertNotEqual(
            session_binding_hash(profile, "conversation-a"),
            session_binding_hash(profile, "conversation-b"),
        )

    def test_project_review_session_rejects_skill_drift(self):
        from selfworkflow.project_review import ProjectReviewProfileError, start_project_review_session

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "review.md"
            skill.write_text("original", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            digest = "sha256:" + hashlib.sha256(b"original").hexdigest()
            profile_path = root / ".selfworkflow" / "review.yaml"
            profile_path.write_text(
                json.dumps(_profile("review.md", digest)), encoding="utf-8"
            )
            session = start_project_review_session(root, "conversation-once")
            skill.write_text("changed", encoding="utf-8")
            with self.assertRaises(ProjectReviewProfileError):
                session.code_review_context(strength="Full", is_code_task=True)
            skill.write_text("changed-again", encoding="utf-8")
            with self.assertRaises(ProjectReviewProfileError):
                session.code_review_context(strength="Full", is_code_task=True)

    def test_project_review_session_rejects_profile_drift(self):
        from selfworkflow.project_review import ProjectReviewProfileError, start_project_review_session

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "review.md"
            skill.write_text("original", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            digest = "sha256:" + hashlib.sha256(b"original").hexdigest()
            profile_path = root / ".selfworkflow" / "review.yaml"
            profile_path.write_text(
                json.dumps(_profile("review.md", digest)), encoding="utf-8"
            )
            session = start_project_review_session(root, "conversation-profile-drift")
            profile_path.write_text(
                json.dumps(_profile("review.md", digest, required=False)), encoding="utf-8"
            )
            with self.assertRaises(ProjectReviewProfileError):
                session.code_review_context(strength="Deep", is_code_task=True)

    def test_project_review_session_rejects_root_identity_drift(self):
        from selfworkflow.project_review import ProjectReviewProfileError, start_project_review_session

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "project"
            root.mkdir()
            skill = root / "review.md"
            skill.write_text("project review", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            digest = "sha256:" + hashlib.sha256(b"project review").hexdigest()
            profile = json.dumps(_profile("review.md", digest))
            (root / ".selfworkflow" / "review.yaml").write_text(profile, encoding="utf-8")
            session = start_project_review_session(root, "conversation-root-drift")
            old_root = parent / "old-project"
            root.rename(old_root)
            root.mkdir()
            (root / ".selfworkflow").mkdir()
            (root / "review.md").write_text("project review", encoding="utf-8")
            (root / ".selfworkflow" / "review.yaml").write_text(profile, encoding="utf-8")
            with self.assertRaises(ProjectReviewProfileError):
                session.code_review_context(strength="Full", is_code_task=True)

    def test_cli_reports_unverified_without_skill_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "review.md"
            skill.write_text("PRIVATE-SKILL-CONTENT", encoding="utf-8")
            (root / ".selfworkflow").mkdir()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps(_profile("review.md", "sha256:" + "0" * 64)), encoding="utf-8"
            )
            exit_code, stdout, stderr = self._run_cli(
                "project-review", "validate", "--project-root", str(root)
            )

        self.assertEqual(exit_code, 53)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["status"], "unverified")
        self.assertNotIn("PRIVATE-SKILL-CONTENT", stdout)

    def test_cli_optional_drift_is_reported_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".selfworkflow").mkdir()
            (root / ".selfworkflow" / "review.yaml").write_text(
                json.dumps(_profile("missing.md", "sha256:" + "0" * 64, required=False)),
                encoding="utf-8",
            )
            exit_code, stdout, stderr = self._run_cli(
                "project-review", "validate", "--project-root", str(root)
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["blocking"], False)

    def test_cli_missing_profile_is_successful_and_does_not_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, stdout, stderr = self._run_cli(
                "project-review", "validate", "--project-root", directory
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["status"], "absent")

    def test_core_runtime_copy_includes_the_profile_schema(self):
        from selfworkflow.adapters import _copy_runtime_path

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "runtime"
            _copy_runtime_path(ROOT, destination, "schemas/project-review-profile.schema.json")
            copied = destination / "schemas/project-review-profile.schema.json"
            self.assertEqual(copied.read_bytes(), (ROOT / "schemas/project-review-profile.schema.json").read_bytes())

    def test_invalid_profile_redacts_content_and_fails_closed(self):
        from selfworkflow.project_review import ProjectReviewProfileError, load_project_review_profile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".selfworkflow").mkdir()
            secret = "../PRIVATE-REVIEW-SKILL"
            (root / ".selfworkflow" / "review.yaml").write_text(
                f"schemaVersion: 1\nadditionalReviewSkills:\n"
                f"  - id: project.review\n    path: {secret}\n"
                "    contentHash: sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
                "    required: true\n",
                encoding="utf-8",
            )

            with self.assertRaises(ProjectReviewProfileError) as raised:
                load_project_review_profile(root)

        self.assertEqual(str(raised.exception), "project-review-profile-invalid")
        self.assertNotIn(secret, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
