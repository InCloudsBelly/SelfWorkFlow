from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import unittest

from jsonschema import Draft202012Validator
import yaml

from selfworkflow.imports import (
    ImportGovernanceError,
    build_extraction_candidate,
    inspect_git_source,
    publish_candidate,
    validate_candidate,
)


class SkillImportTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_checked_in_registry_and_extraction_record_match_closed_schemas(self):
        pairs = (
            (
                "imports/source-registry.yaml",
                "schemas/source-registry.schema.json",
            ),
            (
                "imports/extraction-records/code-quality-v1.yaml",
                "schemas/extraction-record.schema.json",
            ),
        )
        for document_path, schema_path in pairs:
            with self.subTest(document=document_path):
                document = yaml.safe_load(
                    (self.ROOT / document_path).read_text(encoding="utf-8")
                )
                schema = json.loads(
                    (self.ROOT / schema_path).read_text(encoding="utf-8")
                )
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema).validate(document)
                self.assertFalse(self._open_objects(schema))

    @staticmethod
    def _open_objects(value):
        result = []
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                if item.get("type") == "object" and item.get("additionalProperties") is not False:
                    result.append(item)
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        return result

    def test_source_snapshot_binds_commit_dirty_state_and_selected_file_hashes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            selected = root / "skills" / "quality" / "SKILL.md"
            ignored = root / "skills" / "other" / "SKILL.md"
            selected.parent.mkdir(parents=True)
            ignored.parent.mkdir(parents=True)
            selected.write_text("selected\n", encoding="utf-8")
            ignored.write_text("ignored\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                [
                    "git", "-c", "user.name=SelfWorkFlow Tests",
                    "-c", "user.email=selfworkflow@example.invalid",
                    "commit", "-q", "-m", "fixture",
                ],
                cwd=root,
                check=True,
            )
            ignored.write_text("dirty but not selected\n", encoding="utf-8")
            expected_hash = hashlib.sha256(selected.read_bytes()).hexdigest()

            snapshot = inspect_git_source(
                root, "fixture-source", ["skills/quality/SKILL.md"]
            )

            self.assertEqual(snapshot["sourceId"], "fixture-source")
            self.assertEqual(len(snapshot["revision"]), 40)
            self.assertTrue(snapshot["repositoryDirty"])
            self.assertFalse(snapshot["selectedFilesDirty"])
            self.assertEqual(
                snapshot["selectedFiles"],
                [{
                    "path": "skills/quality/SKILL.md",
                    "sha256": expected_hash,
                    "dirty": False,
                }],
            )
            self.assertNotIn("other", str(snapshot))

    def test_source_snapshot_rejects_untracked_or_escaping_selection(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            (root / "tracked.md").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "tracked.md"], cwd=root, check=True)
            subprocess.run(
                [
                    "git", "-c", "user.name=SelfWorkFlow Tests",
                    "-c", "user.email=selfworkflow@example.invalid",
                    "commit", "-q", "-m", "fixture",
                ],
                cwd=root,
                check=True,
            )
            (root / "untracked.md").write_text("untracked\n", encoding="utf-8")
            for path in ("../outside.md", "untracked.md"):
                with self.subTest(path=path):
                    with self.assertRaises(ImportGovernanceError):
                        inspect_git_source(root, "fixture-source", [path])

    def test_candidate_quarantines_local_sensitive_and_project_specific_content(self):
        snapshot = {
            "sourceId": "fixture-source",
            "revision": "a" * 40,
            "repositoryDirty": False,
            "selectedFilesDirty": False,
            "selectedFiles": [
                {"path": "SKILL.md", "sha256": "b" * 64, "dirty": False}
            ],
        }
        candidate = build_extraction_candidate(
            snapshot,
            [
                {"stableId": "owner-first", "content": "Repair the owner layer."},
                {"stableId": "local-path", "content": "Read E:\\private\\SKILL.md."},
                {"stableId": "secret", "content": "PRIVATE KEY material"},
                {"stableId": "project", "content": "Use InternalProject gateway."},
            ],
            quarantine_terms=["InternalProject"],
        )

        self.assertEqual(
            [item["stableId"] for item in candidate["acceptedPrinciples"]],
            ["owner-first"],
        )
        self.assertEqual(
            {item["stableId"] for item in candidate["quarantined"]},
            {"local-path", "secret", "project"},
        )
        self.assertNotIn("PRIVATE KEY material", str(candidate["quarantined"]))
        self.assertEqual(candidate["publicationStatus"], "candidate")

    def test_candidate_requires_complete_evidence_and_current_source(self):
        snapshot = {
            "sourceId": "fixture-source",
            "revision": "a" * 40,
            "repositoryDirty": False,
            "selectedFilesDirty": False,
            "selectedFiles": [
                {"path": "SKILL.md", "sha256": "b" * 64, "dirty": False}
            ],
        }
        candidate = build_extraction_candidate(
            snapshot,
            [{"stableId": "owner-first", "content": "Repair the owner layer."}],
        )
        candidate["evidence"] = {
            "failureBaseline": "passed",
            "positiveTrigger": "passed",
            "negativeTrigger": "passed",
            "conflict": "passed",
            "independentReview": "passed",
        }
        self.assertEqual(validate_candidate(candidate, snapshot), ())

        changed = {**snapshot, "selectedFiles": [
            {"path": "SKILL.md", "sha256": "c" * 64, "dirty": False}
        ]}
        self.assertIn("source-evidence-stale", validate_candidate(candidate, changed))
        duplicate = build_extraction_candidate(
            snapshot,
            [
                {"stableId": "same", "content": "First."},
                {"stableId": "same", "content": "Second."},
            ],
        )
        self.assertIn("duplicate-principle", validate_candidate(duplicate, snapshot))
        self.assertIn("evidence-incomplete", validate_candidate(duplicate, snapshot))

    def test_publish_requires_confirmation_and_writes_only_generalized_knowledge(self):
        snapshot = {
            "sourceId": "fixture-source",
            "revision": "a" * 40,
            "repositoryDirty": False,
            "selectedFilesDirty": False,
            "selectedFiles": [
                {"path": "SKILL.md", "sha256": "b" * 64, "dirty": False}
            ],
        }
        candidate = build_extraction_candidate(
            snapshot,
            [{"stableId": "owner-first", "content": "Repair the owner layer."}],
        )
        candidate["evidence"] = {
            key: "passed" for key in (
                "failureBaseline", "positiveTrigger", "negativeTrigger",
                "conflict", "independentReview",
            )
        }
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            output = Path(temporary) / "published.md"
            with self.assertRaises(ImportGovernanceError):
                publish_candidate(candidate, snapshot, output, confirmed_by_user=False)
            self.assertFalse(output.exists())

            receipt = publish_candidate(
                candidate, snapshot, output, confirmed_by_user=True
            )

            self.assertEqual(receipt["publicationStatus"], "published")
            self.assertEqual(output.read_text(encoding="utf-8"), "Repair the owner layer.\n")
            self.assertNotIn("E:\\", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
