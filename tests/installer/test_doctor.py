from pathlib import Path
import unittest

import yaml

from selfworkflow.installer import doctor, tree_hash


class InstallerFixtureTests(unittest.TestCase):
    def test_layout_fixture_defines_all_transaction_boundaries(self):
        root = Path(__file__).resolve().parents[2]
        document = yaml.safe_load(
            (root / "tests/fixtures/installer/layouts.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(document["schemaVersion"], 1)
        self.assertEqual(
            {item["id"] for item in document["layouts"]},
            {
                "fresh", "unmanaged-content", "conflicting-managed-block",
                "drift-after-plan", "reparse-target", "interrupted-apply",
            },
        )

    def test_doctor_is_read_only_and_reports_environment(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            agents = root / "agents"
            codex = root / "codex"
            state = root / "state"
            agents.mkdir()
            (agents / "existing.txt").write_text("keep\n", encoding="utf-8")
            before = tree_hash(root)

            report = doctor(agents, codex, state)

            self.assertEqual(tree_hash(root), before)
            self.assertEqual(report["agentsRoot"]["status"], "present")
            self.assertEqual(report["codexRoot"]["status"], "missing")
            self.assertEqual(report["stateRoot"]["status"], "missing")
            self.assertEqual(report["incompleteTransactions"], [])


if __name__ == "__main__":
    unittest.main()
