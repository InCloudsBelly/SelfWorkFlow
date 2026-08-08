import json
from pathlib import Path
import unittest
from unittest.mock import patch


class VersionDispatchTests(unittest.TestCase):
    def test_v3_request_is_dispatched_to_v3_resolver(self):
        from selfworkflow.cli import _resolve_by_version

        request = {"schemaVersion": 3}
        expected = {"schemaVersion": 3, "status": "active"}
        with patch("selfworkflow.v3.resolver.resolve_request", return_value=expected) as resolver:
            result = _resolve_by_version(b"ignored", request)
        resolver.assert_called_once()
        self.assertIs(result, expected)

    def test_v2_request_is_dispatched_to_unchanged_v2_resolver(self):
        from selfworkflow.cli import _resolve_by_version

        request = {"schemaVersion": 2}
        expected = {"schemaVersion": 2}
        with patch("selfworkflow.cli.resolve_task", return_value=expected) as resolver:
            result = _resolve_by_version(b"catalog", request)
        resolver.assert_called_once_with(b"catalog", request)
        self.assertIs(result, expected)

    def test_unknown_version_fails_closed_without_fallback(self):
        from selfworkflow.cli import _resolve_by_version

        with self.assertRaisesRegex(ValueError, "unsupported-contract-version"):
            _resolve_by_version(b"catalog", {"schemaVersion": 99})


if __name__ == "__main__":
    unittest.main()
