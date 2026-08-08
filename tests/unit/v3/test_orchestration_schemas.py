import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, ValidationError


class OrchestrationSchemaTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[3]

    MODULE = {
        "schemaVersion": 3,
        "id": "review-independent",
        "sourceHash": "sha256:" + "a" * 64,
        "stage": "reviewed",
        "slot": "review.independent",
        "selectionMode": "static",
        "invocation": {"kind": "skill", "ref": "superpowers:requesting-code-review"},
        "dependencies": [],
        "conflicts": [],
        "contextCost": {"estimatedContextCost": 256, "estimatedExecutionCost": 128},
        "supportEvidence": {
            "sourceIntegrity": "supported",
            "adapterSupport": "supported",
            "runtimeCapability": "unverified",
            "behaviorEvidence": "supported",
        },
    }
    CATALOG = {
        "schemaVersion": 3,
        "catalogHash": "sha256:" + "b" * 64,
        "domains": [
            {"id": "code-quality", "ref": "domains/code-quality.yaml", "hash": "sha256:" + "c" * 64}
        ],
        "modules": [MODULE],
    }
    PIPELINE = {
        "schemaVersion": 3,
        "stages": [
            {
                "id": "reviewed",
                "slots": [
                    {
                        "id": "review.independent",
                        "cardinality": "exactly-one",
                        "allowedInvocationKinds": ["skill"],
                        "selectionMode": "static",
                        "condition": {"eq": ["operationType", "review"]},
                    }
                ],
            }
        ],
    }

    def _validator(self, filename):
        schema_path = self.ROOT / "schemas" / "v3" / filename
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)

    def test_v3_resolve_request_schema_is_available(self):
        schema_path = self.ROOT / "schemas" / "v3" / "resolve-request.schema.json"

        self.assertTrue(schema_path.is_file(), "v3-schema-not-found")

    def test_v3_module_schema_is_available(self):
        schema_path = self.ROOT / "schemas" / "v3" / "module.schema.json"

        self.assertTrue(schema_path.is_file(), "v3-module-schema-not-found")

    def test_v3_catalog_schema_is_available(self):
        schema_path = self.ROOT / "schemas" / "v3" / "catalog.schema.json"

        self.assertTrue(schema_path.is_file(), "v3-catalog-schema-not-found")

    def test_v3_pipeline_schema_is_available(self):
        schema_path = self.ROOT / "schemas" / "v3" / "pipeline.schema.json"

        self.assertTrue(schema_path.is_file(), "v3-pipeline-schema-not-found")

    def test_module_schema_accepts_minimal_module(self):
        self._validator("module.schema.json").validate(self.MODULE)

    def test_module_schema_rejects_unknown_field(self):
        invalid = {**self.MODULE, "unexpected": True}

        with self.assertRaises(ValidationError):
            self._validator("module.schema.json").validate(invalid)

    def test_module_schema_rejects_wrong_version(self):
        invalid = {**self.MODULE, "schemaVersion": 2}

        with self.assertRaises(ValidationError):
            self._validator("module.schema.json").validate(invalid)

    def test_module_schema_rejects_negative_context_cost(self):
        invalid = {**self.MODULE, "contextCost": {"estimatedContextCost": -1, "estimatedExecutionCost": 128}}

        with self.assertRaises(ValidationError):
            self._validator("module.schema.json").validate(invalid)

    def test_catalog_schema_accepts_minimal_catalog(self):
        self._validator("catalog.schema.json").validate(self.CATALOG)

    def test_catalog_schema_rejects_unknown_field(self):
        invalid = {**self.CATALOG, "unexpected": True}

        with self.assertRaises(ValidationError):
            self._validator("catalog.schema.json").validate(invalid)

    def test_catalog_schema_rejects_wrong_version(self):
        invalid = {**self.CATALOG, "schemaVersion": 2}

        with self.assertRaises(ValidationError):
            self._validator("catalog.schema.json").validate(invalid)

    def test_catalog_schema_rejects_invalid_domain_hash(self):
        invalid = {
            **self.CATALOG,
            "domains": [{**self.CATALOG["domains"][0], "hash": "not-a-sha256"}],
        }

        with self.assertRaises(ValidationError):
            self._validator("catalog.schema.json").validate(invalid)

    def test_pipeline_schema_accepts_minimal_pipeline(self):
        self._validator("pipeline.schema.json").validate(self.PIPELINE)

    def test_pipeline_schema_rejects_unknown_field(self):
        invalid = {**self.PIPELINE, "unexpected": True}

        with self.assertRaises(ValidationError):
            self._validator("pipeline.schema.json").validate(invalid)

    def test_pipeline_schema_rejects_wrong_version(self):
        invalid = {**self.PIPELINE, "schemaVersion": 2}

        with self.assertRaises(ValidationError):
            self._validator("pipeline.schema.json").validate(invalid)

    def test_pipeline_schema_rejects_unknown_condition_operator(self):
        invalid = {
            **self.PIPELINE,
            "stages": [
                {
                    **self.PIPELINE["stages"][0],
                    "slots": [{**self.PIPELINE["stages"][0]["slots"][0], "condition": {"xor": []}}],
                }
            ],
        }

        with self.assertRaises(ValidationError):
            self._validator("pipeline.schema.json").validate(invalid)


if __name__ == "__main__":
    unittest.main()
