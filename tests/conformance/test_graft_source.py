import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from selfworkflow.v3.graft_source import GraftSourceError, verify_graft_source


ROOT = Path(__file__).resolve().parents[2]


class GraftSourceConformanceTests(unittest.TestCase):
    def test_official_graft_is_a_pinned_gitlink_with_verified_lock_and_build(self):
        listing = subprocess.run(
            ["git", "ls-files", "--stage", "--", "dependencies/upstream/graft"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertTrue(listing)
        self.assertEqual(listing.split()[0], "160000")
        result = verify_graft_source(ROOT)
        self.assertEqual(result["providerId"], "graft")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["commit"], "f9e65396e638e517aecae0d731017f53084d70ed")

    def test_dirty_or_branch_drift_fails_closed(self):
        original = subprocess.run

        def dirty(command, *args, **kwargs):
            if command[:2] == ["git", "-c"]:
                return original(command, *args, **kwargs)
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, " M package.json\n", "")
            return original(command, *args, **kwargs)

        with patch("selfworkflow.v3.graft_source.subprocess.run", side_effect=dirty):
            with self.assertRaisesRegex(GraftSourceError, "graft-source-drift"):
                verify_graft_source(ROOT)


if __name__ == "__main__":
    unittest.main()
