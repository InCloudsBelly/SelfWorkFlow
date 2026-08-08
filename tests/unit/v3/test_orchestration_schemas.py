from pathlib import Path
import unittest


class OrchestrationSchemaTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[3]

    def test_v3_resolve_request_schema_is_available(self):
        schema_path = self.ROOT / "schemas" / "v3" / "resolve-request.schema.json"

        self.assertTrue(schema_path.is_file(), "v3-schema-not-found")


if __name__ == "__main__":
    unittest.main()
