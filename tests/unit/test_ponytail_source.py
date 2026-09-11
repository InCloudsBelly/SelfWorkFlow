from pathlib import Path
import tempfile
import unittest
from unittest import mock
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout

from selfworkflow.ponytail_source import (
    PonytailSourceError,
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
            ["ponytail", "ponytail-review", "ponytail-audit"],
        )

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
            "selfworkflow.ponytail_source._git", side_effect=["a" * 40, "b" * 40, ""]
        ):
            with self.assertRaisesRegex(PonytailSourceError, "ponytail-gitlink-mismatch"):
                verify_ponytail_source(self.ROOT)


if __name__ == "__main__":
    unittest.main()
