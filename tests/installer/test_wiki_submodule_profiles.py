from selfworkflow.v3.submodule_profiles import apply_submodule_profile, commands_for_profile, SubmoduleProfileError
from pathlib import Path
import unittest
from unittest import mock


class WikiSubmoduleProfileTests(unittest.TestCase):
    def test_wiki_dependencies_are_prepared_only_for_knowledge(self):
        base = commands_for_profile("normal")
        self.assertEqual(base, commands_for_profile("normal", runtime_profile="core"))
        self.assertEqual(base, commands_for_profile("normal", runtime_profile="maintainer"))
        wiki = commands_for_profile("normal", runtime_profile="knowledge")
        extra = wiki[len(base):]
        self.assertEqual(extra, (
            ("git", "submodule", "sync", "--", "extensions/knowledge/selfopenwiki/upstream/openwiki"),
            ("git", "submodule", "update", "--init", "--", "extensions/knowledge/selfopenwiki/upstream/openwiki"),
            ("git", "submodule", "sync", "--", "extensions/knowledge/selfopenwiki/visualizer/zxh_wiki_viewer"),
            ("git", "submodule", "update", "--init", "--", "extensions/knowledge/selfopenwiki/visualizer/zxh_wiki_viewer"),
        ))
        self.assertNotIn("--remote", [part for command in wiki for part in command])

    def test_invalid_runtime_profile_is_rejected_before_git(self):
        with self.assertRaisesRegex(SubmoduleProfileError, "runtime-profile-invalid"):
            commands_for_profile("normal", runtime_profile="all")
        runner = mock.Mock()
        with self.assertRaisesRegex(SubmoduleProfileError, "runtime-profile-invalid"):
            apply_submodule_profile(Path.cwd(), runtime_profile="all", runner=runner)
        runner.assert_not_called()

    def test_installer_passes_the_selected_runtime_profile_to_preparation(self):
        root = Path(__file__).resolve().parents[2]
        script = (root / "scripts/install-selfworkflow.ps1").read_text(encoding="utf-8")
        self.assertIn('"--runtime-profile", $Profile', script)
