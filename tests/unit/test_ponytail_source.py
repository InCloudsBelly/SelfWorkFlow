from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest import mock
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout

import yaml

from selfworkflow.ponytail_source import (
    PonytailSourceError,
    _adapt_ponytail_skill,
    copy_ponytail_skills,
    load_ponytail_lock,
    validate_ponytail_lock,
    verify_ponytail_source,
)


class PonytailSourceTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_pinned_upstream_and_selected_skills_are_verified(self):
        report = verify_ponytail_source(self.ROOT)

        self.assertEqual(report["sourceId"], "ponytail")
        self.assertEqual(report["canonicalUrl"], "https://github.com/DietrichGebert/ponytail.git")
        self.assertEqual(
            [item["id"] for item in report["selectedSkills"]],
            ["ponytail", "ponytail-review", "ponytail-audit", "ponytail-help", "ponytail-debt"],
        )

    def test_copy_recovers_locked_license_endings_and_rejects_content_drift(self):
        license_path = self.ROOT / "dependencies/upstream/ponytail/LICENSE"
        original_read = Path.read_bytes
        original = original_read(license_path)
        crlf = original.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        lock = load_ponytail_lock(self.ROOT)
        for changed in (False, True):
            content = crlf + (b"actual license content drift\r\n" if changed else b"")
            def checkout_read(path):
                return content if path == license_path else original_read(path)
            with self.subTest(content_drift=changed), mock.patch.object(Path, "read_bytes", checkout_read):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                    if changed:
                        with self.assertRaisesRegex(PonytailSourceError, "ponytail-source-drift"):
                            copy_ponytail_skills(self.ROOT, temporary)
                    else:
                        copy_ponytail_skills(self.ROOT, temporary)
                        published = Path(temporary) / "skills/ponytail/LICENSE"
                        self.assertEqual("sha256:" + hashlib.sha256(published.read_bytes()).hexdigest(), lock["license"]["hash"])

    def test_debt_runtime_preserves_scan_and_requires_separate_write_authorization(self):
        source = (self.ROOT / "dependencies/upstream/ponytail/skills/ponytail-debt/SKILL.md").read_bytes()
        adapted = _adapt_ponytail_skill(source, "ponytail-debt")
        text = adapted.decode("utf-8")
        self.assertEqual(text.split("## Boundaries")[0], source.decode("utf-8").replace("\r\n", "\n").split("## Boundaries")[0])
        self.assertIn("explicit one-shot", text)
        self.assertIn("does not activate Ponytail coding or session mode", text)
        self.assertIn("separate explicit user authorization", text)
        self.assertNotIn("To persist it, ask and it writes", text)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            copy_ponytail_skills(self.ROOT, temporary)
            runtime = Path(temporary) / "skills/ponytail-debt/SKILL.md"
            self.assertEqual(runtime.read_bytes(), adapted)
            self.assertFalse((Path(temporary) / "skills/ponytail-gain").exists())
        selected = load_ponytail_lock(self.ROOT)["selectedSkills"]
        debt = next(item for item in selected if item["id"] == "ponytail-debt")
        self.assertEqual(debt["hash"], "sha256:" + hashlib.sha256(source).hexdigest())
        self.assertEqual(debt["runtimeHash"], "sha256:" + hashlib.sha256(adapted).hexdigest())

    def test_debt_adaptation_fails_closed_when_boundary_changes(self):
        with self.assertRaisesRegex(PonytailSourceError, "ponytail-source-adaptation-invalid"):
            _adapt_ponytail_skill(b"## Boundaries\nChanged upstream policy.\n", "ponytail-debt")

    def test_debt_hash_drift_fails_closed(self):
        for field, reason in (("hash", "ponytail-source-drift"), ("runtimeHash", "ponytail-runtime-hash-mismatch")):
            with self.subTest(field=field):
                lock = load_ponytail_lock(self.ROOT)
                debt = next(item for item in lock["selectedSkills"] if item["id"] == "ponytail-debt")
                debt[field] = "sha256:" + "0" * 64
                with mock.patch("selfworkflow.ponytail_source.load_ponytail_lock", return_value=lock):
                    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                        with self.assertRaisesRegex(PonytailSourceError, reason):
                            copy_ponytail_skills(self.ROOT, temporary)

    def test_catalog_hashes_match_adapted_runtime_skill_bytes(self):
        catalog = yaml.safe_load(
            (self.ROOT / "catalog/v3/index.yaml").read_text(encoding="utf-8")
        )
        modules = {
            item["id"]: yaml.safe_load(
                (self.ROOT / "catalog/v3" / item["ref"]).read_text(encoding="utf-8")
            )
            for item in catalog["modules"]
            if item["id"] in {"ponytail-coding", "ponytail-help"}
        }
        for module_id, skill_id in {
            "ponytail-coding": "ponytail",
            "ponytail-help": "ponytail-help",
        }.items():
            source = (
                self.ROOT / f"dependencies/upstream/ponytail/skills/{skill_id}/SKILL.md"
            ).read_bytes()
            expected = "sha256:" + __import__("hashlib").sha256(
                _adapt_ponytail_skill(source, skill_id)
            ).hexdigest()
            self.assertEqual(modules[module_id]["sourceHash"], expected)

    def test_missing_or_invalid_lock_fails_closed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(PonytailSourceError, "ponytail-lock-missing"):
                load_ponytail_lock(root)

            lock_path = root / "dependencies/locks/ponytail.lock.yaml"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text("schemaVersion: 1\nsourceId: ponytail\n", encoding="utf-8")
            with self.assertRaisesRegex(PonytailSourceError, "ponytail-lock-invalid"):
                load_ponytail_lock(root)

    def test_selected_skill_path_and_hash_are_bound(self):
        lock = {
            "schemaVersion": 1,
            "sourceId": "ponytail",
            "canonicalUrl": "https://github.com/DietrichGebert/ponytail.git",
            "path": "dependencies/upstream/ponytail",
            "gitlinkCommit": "a" * 40,
            "gitTree": "b" * 40,
            "upstreamVersion": "4.9.0",
            "license": {"path": "LICENSE", "spdx": "MIT", "hash": "sha256:" + "c" * 64},
            "selectedSkills": [
                {"id": "ponytail", "path": "skills/../escape", "hash": "sha256:" + "d" * 64},
            ],
        }
        with self.assertRaisesRegex(PonytailSourceError, "ponytail-lock-invalid"):
            validate_ponytail_lock(lock)

    def test_cli_verification_exposes_source_failure_without_fallback(self):
        from selfworkflow.cli import main

        stdout, stderr = StringIO(), StringIO()
        with mock.patch(
            "selfworkflow.cli.verify_ponytail_source",
            side_effect=PonytailSourceError("ponytail-source-drift"),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["source", "ponytail-verify", "--repository", str(self.ROOT)])
        self.assertEqual(result, 63)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("ponytail-source-verification-failed:ponytail-source-drift", stderr.getvalue())

    def test_gitlink_or_source_drift_is_not_accepted(self):
        with mock.patch(
            "selfworkflow.ponytail_source._git",
            side_effect=["https://github.com/DietrichGebert/ponytail.git", "a" * 40, "b" * 40, ""],
        ):
            with self.assertRaisesRegex(PonytailSourceError, "ponytail-gitlink-mismatch"):
                verify_ponytail_source(self.ROOT)


if __name__ == "__main__":
    unittest.main()
