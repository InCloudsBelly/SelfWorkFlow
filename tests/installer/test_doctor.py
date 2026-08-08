from pathlib import Path
import unittest

import yaml


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


if __name__ == "__main__":
    unittest.main()
