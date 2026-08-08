from pathlib import Path
import subprocess
import tempfile
import unittest

from selfworkflow.sources import (
    SourceSelectionError,
    inspect_superpowers_source,
    lock_superpowers_source,
)


def _commit(root: Path):
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


class SuperpowersSourceTests(unittest.TestCase):
    def test_local_git_source_records_commit_dirty_inventory_and_hash_drift(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            skill = root / "skills" / "brainstorming" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("brainstorm v1\n", encoding="utf-8")
            _commit(root)

            clean = inspect_superpowers_source(root)
            self.assertEqual(clean["sourceType"], "local-git")
            self.assertEqual(clean["supportStatus"], "supported")
            self.assertEqual(clean["reproducibilityStatus"], "reproducible")
            self.assertFalse(clean["dirty"])
            self.assertEqual(len(clean["commit"]), 40)
            self.assertEqual(clean["dirtyFiles"], [])
            clean_hash = clean["inventoryHash"]

            skill.write_text("brainstorm v2\n", encoding="utf-8")
            dirty = inspect_superpowers_source(root)
            self.assertTrue(dirty["dirty"])
            self.assertEqual(dirty["reproducibilityStatus"], "dirty-snapshot")
            self.assertNotEqual(dirty["inventoryHash"], clean_hash)
            self.assertEqual(dirty["dirtyFiles"][0]["path"], "skills/brainstorming/SKILL.md")

    def test_missing_and_non_git_sources_are_truthfully_unsupported(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            non_git = inspect_superpowers_source(root)
            missing = inspect_superpowers_source(root / "missing")
        self.assertEqual(non_git["supportStatus"], "unsupported")
        self.assertEqual(non_git["reason"], "not-git")
        self.assertEqual(missing["supportStatus"], "unsupported")
        self.assertEqual(missing["reason"], "missing")

    def test_lock_requires_explicit_selection_and_dirty_authorization(self):
        candidate = {
            "sourceType": "local-git",
            "supportStatus": "supported",
            "reproducibilityStatus": "dirty-snapshot",
            "commit": "a" * 40,
            "dirty": True,
            "inventoryHash": "sha256:" + "b" * 64,
            "dirtyFiles": [{"path": "SKILL.md", "sha256": "c" * 64}],
        }
        with self.assertRaises(SourceSelectionError):
            lock_superpowers_source(candidate, selected_by_user=False, allow_dirty=False)
        with self.assertRaises(SourceSelectionError):
            lock_superpowers_source(candidate, selected_by_user=True, allow_dirty=False)

        locked = lock_superpowers_source(
            candidate, selected_by_user=True, allow_dirty=True
        )
        self.assertEqual(locked["selectionStatus"], "selected")
        self.assertTrue(locked["dirtyAuthorized"])

    def test_refused_or_unavailable_source_pauses_writes_but_allows_disclosed_readonly(self):
        unavailable = {
            "sourceType": "missing",
            "supportStatus": "unsupported",
            "reproducibilityStatus": "unavailable",
            "reason": "missing",
        }
        with self.assertRaises(SourceSelectionError):
            lock_superpowers_source(unavailable, selected_by_user=True, allow_dirty=False)
        self.assertEqual(
            lock_superpowers_source(
                unavailable,
                selected_by_user=False,
                allow_dirty=False,
                readonly_fallback=True,
            ),
            {
                "selectionStatus": "declined",
                "allowedMode": "read-only-analysis",
                "reason": "superpowers-unavailable-or-declined",
            },
        )


if __name__ == "__main__":
    unittest.main()
