import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from selfworkflow.v3.tea_adapter import TeaAdapterError, verify_tea_source


REPOSITORY = Path(__file__).resolve().parents[2]
TEA_PATH = REPOSITORY / "dependencies" / "upstream" / "tea"
LOCK_PATH = REPOSITORY / "dependencies" / "locks" / "tea.lock.yaml"


class TeaSourceConformanceTests(unittest.TestCase):
    def test_official_tea_is_a_pinned_gitlink_with_a_lock(self):
        listing = subprocess.run(
            ["git", "ls-files", "--stage", "--", "dependencies/upstream/tea"],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertTrue(listing, "tea-source-identity-invalid")
        self.assertEqual(listing.split()[0], "160000", "tea-source-identity-invalid")
        self.assertTrue(TEA_PATH.is_dir(), "tea-source-identity-invalid")
        self.assertTrue(LOCK_PATH.is_file(), "tea-source-identity-invalid")

    def test_lock_recomputes_official_source_and_adapter_identity(self):
        identity = verify_tea_source(REPOSITORY)
        self.assertEqual(
            identity["commit"],
            "04cf65b03620c07f63e6af8f90023ea56fa0348e",
        )
        self.assertEqual(identity["status"], "supported")

    def test_identity_is_fail_closed_for_branch_or_dirty_source(self):
        original = subprocess.run

        def branch(command, *args, **kwargs):
            if command[:3] == ["git", "config", "--file"]:
                return subprocess.CompletedProcess(command, 0, "main\n", "")
            return original(command, *args, **kwargs)

        with patch("selfworkflow.v3.tea_adapter.subprocess.run", side_effect=branch):
            with self.assertRaisesRegex(TeaAdapterError, "tea-source-identity-invalid"):
                verify_tea_source(REPOSITORY)

        def dirty(command, *args, **kwargs):
            if "status" in command:
                return subprocess.CompletedProcess(command, 0, " M tracked.md\n", "")
            return original(command, *args, **kwargs)

        with patch("selfworkflow.v3.tea_adapter.subprocess.run", side_effect=dirty):
            with self.assertRaisesRegex(TeaAdapterError, "tea-source-identity-invalid"):
                verify_tea_source(REPOSITORY)


if __name__ == "__main__":
    unittest.main()
