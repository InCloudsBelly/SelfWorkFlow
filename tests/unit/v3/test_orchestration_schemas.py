from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


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
    RESOLVE_REQUEST = {
        "schemaVersion": 3,
        "operationType": "implement",
        "complexity": "C1",
        "risk": "R1",
        "writeTask": True,
        "ambiguity": False,
        "explicitModuleIds": [],
        "projectDefaultModuleIds": [],
        "projectMinimums": {"strength": "Light"},
        "capabilityEvidenceSnapshot": {
            "schemaVersion": 1,
            "capturedAt": "2026-08-09T00:00:00Z",
            "evidence": [],
        },
        "taskArchetype": "bounded-feature",
        "requirementsMaturity": "defined",
        "scopeShape": "single-module",
        "durableSpec": True,
        "classificationConfidence": 0.9,
        "classificationEvidence": [
            {
                "evidenceRef": "classification-1",
                "evidenceHash": "sha256:" + "d" * 64,
                "classifierVersion": "classifier-v1",
                "classifierHash": "sha256:" + "e" * 64,
            }
        ],
        "testLevelFloor": "T1",
    }

    def _validator(self, filename):
        schema_root = self.ROOT / "schemas" / "v3"
        schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in schema_root.glob("*.schema.json")
        }
        resources = []
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)
            resources.append((schema["$id"], Resource.from_contents(schema)))
        return Draft202012Validator(
            schemas[filename],
            registry=Registry().with_resources(resources),
            format_checker=FormatChecker(),
        )

    def _pipeline_with_condition(self, condition):
        return {
            **self.PIPELINE,
            "stages": [
                {
                    **self.PIPELINE["stages"][0],
                    "slots": [
                        {
                            **self.PIPELINE["stages"][0]["slots"][0],
                            "condition": condition,
                        }
                    ],
                }
            ],
        }

    def _assert_condition_error(self, condition):
        errors = list(
            self._validator("pipeline.schema.json").iter_errors(
                self._pipeline_with_condition(condition)
            )
        )

        self.assertEqual(len(errors), 1)
        self.assertEqual(
            list(errors[0].absolute_path),
            ["stages", 0, "slots", 0, "condition"],
        )
        self.assertEqual(errors[0].validator, "oneOf")

    def _assert_schema_error(self, filename, document, path, validator):
        errors = list(self._validator(filename).iter_errors(document))

        self.assertEqual(len(errors), 1)
        self.assertEqual(tuple(errors[0].absolute_path), path)
        self.assertEqual(errors[0].validator, validator)

    def _resolve_request_with_evidence(self, observed_at, captured_at, valid_until):
        request = deepcopy(self.RESOLVE_REQUEST)
        request["capabilityEvidenceSnapshot"] = {
            "schemaVersion": 1,
            "capturedAt": captured_at,
            "evidence": [
                {
                    "name": "filesystem-read",
                    "provider": "codex",
                    "subject": {
                        "kind": "agent",
                        "id": "codex",
                        "version": None,
                        "build": None,
                        "sourceLock": None,
                    },
                    "state": "supported",
                    "observedAt": observed_at,
                    "validUntil": valid_until,
                    "evidenceRef": "capability-evidence-1",
                    "evidenceHash": "sha256:" + "f" * 64,
                }
            ],
        }
        return request

    def _assert_contract_error(
        self,
        schema_name,
        text,
        reason,
        path,
        validator,
    ):
        from selfworkflow.v3.contracts import ContractError, load_contract

        with self.assertRaises(ContractError) as raised:
            load_contract(schema_name, text)

        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(raised.exception.path, path)
        self.assertEqual(raised.exception.validator, validator)
        self.assertNotIn(str(self.ROOT), str(raised.exception))

    def _assert_catalog_pipeline_error(
        self,
        catalog,
        pipeline,
        reason,
        path,
    ):
        from selfworkflow.v3.contracts import (
            ContractError,
            validate_catalog_pipeline,
        )

        with self.assertRaises(ContractError) as raised:
            validate_catalog_pipeline(catalog, pipeline)

        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(raised.exception.path, path)
        self.assertEqual(raised.exception.validator, "semantic")

    def test_v3_resolve_request_schema_is_available(self):
        schema_path = self.ROOT / "schemas" / "v3" / "resolve-request.schema.json"

        self.assertTrue(schema_path.is_file(), "v3-schema-not-found")

    def test_resolve_request_schema_accepts_minimal_request(self):
        errors = list(
            self._validator("resolve-request.schema.json").iter_errors(self.RESOLVE_REQUEST)
        )

        self.assertEqual(errors, [])

    def test_resolve_request_schema_rejects_only_unknown_field(self):
        invalid = {**self.RESOLVE_REQUEST, "unexpected": True}

        errors = list(
            self._validator("resolve-request.schema.json").iter_errors(invalid)
        )

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].validator, "additionalProperties")
        self.assertIn("'unexpected'", errors[0].message)
        self.assertNotIn("'operationType'", errors[0].message)

    def test_resolve_request_schema_rejects_only_wrong_version(self):
        invalid = {**self.RESOLVE_REQUEST, "schemaVersion": 2}

        errors = list(
            self._validator("resolve-request.schema.json").iter_errors(invalid)
        )

        self.assertEqual(len(errors), 1)
        self.assertEqual(list(errors[0].absolute_path), ["schemaVersion"])
        self.assertEqual(errors[0].validator, "const")

    def test_resolve_request_schema_rejects_confidence_above_one(self):
        invalid = {**self.RESOLVE_REQUEST, "classificationConfidence": 1.01}

        errors = list(
            self._validator("resolve-request.schema.json").iter_errors(invalid)
        )

        self.assertEqual(len(errors), 1)
        self.assertEqual(list(errors[0].absolute_path), ["classificationConfidence"])
        self.assertEqual(errors[0].validator, "maximum")

    def test_v3_module_schema_is_available(self):
        schema_path = self.ROOT / "schemas" / "v3" / "module.schema.json"

        self.assertTrue(schema_path.is_file(), "v3-module-schema-not-found")

    def test_v3_catalog_schema_is_available(self):
        schema_path = self.ROOT / "schemas" / "v3" / "catalog.schema.json"

        self.assertTrue(schema_path.is_file(), "v3-catalog-schema-not-found")

    def test_v3_pipeline_schema_is_available(self):
        schema_path = self.ROOT / "schemas" / "v3" / "pipeline.schema.json"

        self.assertTrue(schema_path.is_file(), "v3-pipeline-schema-not-found")

    def test_v3_contract_loader_is_available(self):
        contracts_path = self.ROOT / "src" / "selfworkflow" / "v3" / "contracts.py"

        self.assertTrue(contracts_path.is_file(), "v3-contract-loader-not-found")

    def test_v3_contract_loader_exposes_strict_entrypoint(self):
        from selfworkflow.v3 import contracts

        self.assertTrue(hasattr(contracts, "ContractError"))
        self.assertTrue(callable(getattr(contracts, "load_contract", None)))

    def test_v3_contract_loader_exposes_catalog_pipeline_semantic_entrypoint(self):
        from selfworkflow.v3 import contracts

        self.assertTrue(
            callable(getattr(contracts, "validate_catalog_pipeline", None))
        )

    def test_contract_loader_accepts_registered_json_object(self):
        from selfworkflow.v3.contracts import load_contract

        loaded = load_contract("module.schema.json", json.dumps(self.MODULE))

        self.assertEqual(loaded, self.MODULE)

    def test_contract_loader_rejects_non_object_root(self):
        self._assert_contract_error(
            "module.schema.json",
            "[]",
            "contract-root-not-object",
            (),
            "type",
        )

    def test_contract_loader_rejects_unknown_and_traversal_schema_names(self):
        schema_names = (
            "unknown.schema.json",
            "../module.schema.json",
            str(self.ROOT / "schemas" / "v3" / "module.schema.json"),
        )

        for schema_name in schema_names:
            with self.subTest(schema_name=schema_name):
                self._assert_contract_error(
                    schema_name,
                    "{}",
                    "contract-schema-not-registered",
                    (),
                    "schemaName",
                )

    def test_contract_loader_rejects_duplicate_json_key_with_stable_diagnostic(self):
        self._assert_contract_error(
            "module.schema.json",
            '{"schemaVersion":3,"schemaVersion":3}',
            "contract-json-duplicate-key",
            (),
            "uniqueKeys",
        )

    def test_contract_loader_reports_hash_failures_exactly(self):
        invalid_module = {**self.MODULE, "sourceHash": "not-a-hash"}
        invalid_catalog = {**self.CATALOG, "catalogHash": "not-a-hash"}
        invalid_capability = self._resolve_request_with_evidence(
            "2026-08-08T00:00:00Z",
            "2026-08-09T00:00:00Z",
            "2026-08-10T00:00:00Z",
        )
        invalid_capability["capabilityEvidenceSnapshot"]["evidence"][0][
            "evidenceHash"
        ] = "not-a-hash"
        invalid_classification_evidence = deepcopy(self.RESOLVE_REQUEST)
        invalid_classification_evidence["classificationEvidence"][0][
            "evidenceHash"
        ] = "not-a-hash"
        invalid_classifier = deepcopy(self.RESOLVE_REQUEST)
        invalid_classifier["classificationEvidence"][0]["classifierHash"] = (
            "not-a-hash"
        )
        cases = (
            (
                "module.schema.json",
                invalid_module,
                ("sourceHash",),
            ),
            (
                "catalog.schema.json",
                invalid_catalog,
                ("catalogHash",),
            ),
            (
                "resolve-request.schema.json",
                invalid_capability,
                ("capabilityEvidenceSnapshot", "evidence", 0, "evidenceHash"),
            ),
            (
                "resolve-request.schema.json",
                invalid_classification_evidence,
                ("classificationEvidence", 0, "evidenceHash"),
            ),
            (
                "resolve-request.schema.json",
                invalid_classifier,
                ("classificationEvidence", 0, "classifierHash"),
            ),
        )

        for schema_name, document, path in cases:
            with self.subTest(schema_name=schema_name, path=path):
                self._assert_contract_error(
                    schema_name,
                    json.dumps(document),
                    "contract-schema-invalid",
                    path,
                    "pattern",
                )

    def test_contract_loader_reports_nested_unknown_field_path(self):
        invalid = deepcopy(self.MODULE)
        invalid["invocation"]["unexpected"] = True

        self._assert_contract_error(
            "module.schema.json",
            json.dumps(invalid),
            "contract-schema-invalid",
            ("invocation", "unexpected"),
            "additionalProperties",
        )

    def test_contract_loader_reports_one_of_branch_failures(self):
        invalid_resolve = self._resolve_request_with_evidence(
            "2026-08-08T00:00:00Z",
            "2026-08-09T00:00:00Z",
            "2026-08-10T00:00:00Z",
        )
        invalid_resolve["capabilityEvidenceSnapshot"]["evidence"][0]["subject"][
            "sourceLock"
        ] = 7
        invalid_catalog = {
            **self.CATALOG,
            "modules": [
                {
                    "schemaVersion": 3,
                    "id": "review-independent",
                    "ref": "modules/review-independent.json",
                    "hash": "sha256:" + "3" * 64,
                }
            ],
        }
        cases = (
            (
                "resolve-request.schema.json",
                invalid_resolve,
                (
                    "capabilityEvidenceSnapshot",
                    "evidence",
                    0,
                    "subject",
                    "sourceLock",
                ),
            ),
            (
                "catalog.schema.json",
                invalid_catalog,
                ("modules", 0),
            ),
        )

        for schema_name, document, path in cases:
            with self.subTest(schema_name=schema_name):
                self._assert_contract_error(
                    schema_name,
                    json.dumps(document),
                    "contract-schema-invalid",
                    path,
                    "oneOf",
                )

    def test_catalog_pipeline_semantics_accept_matching_contracts(self):
        from selfworkflow.v3.contracts import validate_catalog_pipeline

        result = validate_catalog_pipeline(
            deepcopy(self.CATALOG),
            deepcopy(self.PIPELINE),
        )

        self.assertIsNone(result)

    def test_catalog_pipeline_semantics_reject_duplicate_ids(self):
        duplicate_domain = deepcopy(self.CATALOG)
        duplicate_domain["domains"].append(
            {
                "id": "code-quality",
                "ref": "domains/code-quality-duplicate.yaml",
                "hash": "sha256:" + "1" * 64,
            }
        )
        duplicate_module = deepcopy(self.CATALOG)
        second_module = deepcopy(self.MODULE)
        second_module["sourceHash"] = "sha256:" + "2" * 64
        duplicate_module["modules"].append(second_module)
        duplicate_stage = deepcopy(self.PIPELINE)
        second_stage = deepcopy(self.PIPELINE["stages"][0])
        second_stage["slots"][0]["id"] = "review.secondary"
        duplicate_stage["stages"].append(second_stage)
        duplicate_slot = deepcopy(self.PIPELINE)
        second_slot = deepcopy(self.PIPELINE["stages"][0]["slots"][0])
        second_slot["cardinality"] = "zero-or-one"
        duplicate_slot["stages"][0]["slots"].append(second_slot)
        cases = (
            (
                duplicate_domain,
                self.PIPELINE,
                "catalog-domain-id-duplicate",
                ("domains", 1, "id"),
            ),
            (
                duplicate_module,
                self.PIPELINE,
                "catalog-module-id-duplicate",
                ("modules", 1, "id"),
            ),
            (
                self.CATALOG,
                duplicate_stage,
                "pipeline-stage-id-duplicate",
                ("stages", 1, "id"),
            ),
            (
                self.CATALOG,
                duplicate_slot,
                "pipeline-slot-id-duplicate",
                ("stages", 0, "slots", 1, "id"),
            ),
        )

        for catalog, pipeline, reason, path in cases:
            with self.subTest(reason=reason):
                self._assert_catalog_pipeline_error(
                    catalog,
                    pipeline,
                    reason,
                    path,
                )

    def test_catalog_pipeline_semantics_reject_unknown_module_stage(self):
        catalog = deepcopy(self.CATALOG)
        catalog["modules"][0]["stage"] = "implemented"

        self._assert_catalog_pipeline_error(
            catalog,
            self.PIPELINE,
            "catalog-module-stage-unknown",
            ("modules", 0, "stage"),
        )

    def test_catalog_pipeline_semantics_reject_unknown_module_slot(self):
        catalog = deepcopy(self.CATALOG)
        catalog["modules"][0]["slot"] = "review.unknown"

        self._assert_catalog_pipeline_error(
            catalog,
            self.PIPELINE,
            "catalog-module-slot-unknown",
            ("modules", 0, "slot"),
        )

    def test_catalog_pipeline_semantics_reject_disallowed_invocation_kind(self):
        catalog = deepcopy(self.CATALOG)
        catalog["modules"][0]["invocation"]["kind"] = "mcp"

        self._assert_catalog_pipeline_error(
            catalog,
            self.PIPELINE,
            "catalog-module-invocation-kind-not-allowed",
            ("modules", 0, "invocation", "kind"),
        )

    def test_catalog_pipeline_semantics_reject_selection_mode_mismatch(self):
        catalog = deepcopy(self.CATALOG)
        catalog["modules"][0]["selectionMode"] = "bounded-runtime"

        self._assert_catalog_pipeline_error(
            catalog,
            self.PIPELINE,
            "catalog-module-selection-mode-mismatch",
            ("modules", 0, "selectionMode"),
        )

    def test_resolve_request_rejects_invalid_calendar_timestamp(self):
        request = self._resolve_request_with_evidence(
            "2026-02-30T00:00:00Z",
            "2026-03-01T00:00:00Z",
            "2026-03-02T00:00:00Z",
        )

        self._assert_contract_error(
            "resolve-request.schema.json",
            json.dumps(request),
            "contract-schema-invalid",
            ("capabilityEvidenceSnapshot", "evidence", 0, "observedAt"),
            "format",
        )

    def test_resolve_request_rejects_non_utc_timestamp(self):
        request = self._resolve_request_with_evidence(
            "2026-08-08T23:00:00+00:00",
            "2026-08-09T00:00:00Z",
            "2026-08-10T00:00:00Z",
        )

        self._assert_contract_error(
            "resolve-request.schema.json",
            json.dumps(request),
            "contract-schema-invalid",
            ("capabilityEvidenceSnapshot", "evidence", 0, "observedAt"),
            "pattern",
        )

    def test_resolve_request_rejects_evidence_observed_after_capture(self):
        request = self._resolve_request_with_evidence(
            "2026-08-10T00:00:00Z",
            "2026-08-09T00:00:00Z",
            "2026-08-11T00:00:00Z",
        )

        self._assert_contract_error(
            "resolve-request.schema.json",
            json.dumps(request),
            "resolve-evidence-observed-after-capture",
            ("capabilityEvidenceSnapshot", "evidence", 0, "observedAt"),
            "semantic",
        )

    def test_resolve_request_rejects_evidence_expired_at_capture(self):
        request = self._resolve_request_with_evidence(
            "2026-08-07T00:00:00Z",
            "2026-08-09T00:00:00Z",
            "2026-08-08T00:00:00Z",
        )

        self._assert_contract_error(
            "resolve-request.schema.json",
            json.dumps(request),
            "resolve-evidence-expired-at-capture",
            ("capabilityEvidenceSnapshot", "evidence", 0, "validUntil"),
            "semantic",
        )

    def test_resolve_request_accepts_ordered_evidence_window(self):
        from selfworkflow.v3.contracts import load_contract

        request = self._resolve_request_with_evidence(
            "2026-08-08T00:00:00Z",
            "2026-08-09T00:00:00Z",
            "2026-08-10T00:00:00Z",
        )

        loaded = load_contract("resolve-request.schema.json", json.dumps(request))

        self.assertEqual(loaded, request)

    def test_module_schema_accepts_minimal_module(self):
        self._validator("module.schema.json").validate(self.MODULE)

    def test_module_schema_rejects_unknown_field(self):
        invalid = {**self.MODULE, "unexpected": True}

        self._assert_schema_error(
            "module.schema.json",
            invalid,
            (),
            "additionalProperties",
        )

    def test_module_schema_rejects_wrong_version(self):
        invalid = {**self.MODULE, "schemaVersion": 2}

        self._assert_schema_error(
            "module.schema.json",
            invalid,
            ("schemaVersion",),
            "const",
        )

    def test_module_schema_rejects_negative_context_cost(self):
        invalid = {**self.MODULE, "contextCost": {"estimatedContextCost": -1, "estimatedExecutionCost": 128}}

        self._assert_schema_error(
            "module.schema.json",
            invalid,
            ("contextCost", "estimatedContextCost"),
            "minimum",
        )

    def test_catalog_schema_accepts_minimal_catalog(self):
        self._validator("catalog.schema.json").validate(self.CATALOG)

    def test_catalog_schema_references_standalone_module_contract(self):
        from selfworkflow.v3.contracts import load_contract

        catalog_schema = json.loads(
            (self.ROOT / "schemas" / "v3" / "catalog.schema.json").read_text(
                encoding="utf-8"
            )
        )
        module_schema = json.loads(
            (self.ROOT / "schemas" / "v3" / "module.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertNotIn("module", catalog_schema["$defs"])
        self.assertEqual(
            catalog_schema["properties"]["modules"]["items"]["oneOf"][0]["$ref"],
            module_schema["$id"],
        )
        standalone = load_contract("module.schema.json", json.dumps(self.MODULE))
        catalog = load_contract("catalog.schema.json", json.dumps(self.CATALOG))
        self.assertEqual(catalog["modules"][0], standalone)

    def test_catalog_schema_rejects_unknown_field(self):
        invalid = {**self.CATALOG, "unexpected": True}

        self._assert_schema_error(
            "catalog.schema.json",
            invalid,
            (),
            "additionalProperties",
        )

    def test_catalog_schema_rejects_wrong_version(self):
        invalid = {**self.CATALOG, "schemaVersion": 2}

        self._assert_schema_error(
            "catalog.schema.json",
            invalid,
            ("schemaVersion",),
            "const",
        )

    def test_catalog_schema_rejects_invalid_domain_hash(self):
        invalid = {
            **self.CATALOG,
            "domains": [{**self.CATALOG["domains"][0], "hash": "not-a-sha256"}],
        }

        self._assert_schema_error(
            "catalog.schema.json",
            invalid,
            ("domains", 0, "hash"),
            "pattern",
        )

    def test_pipeline_schema_accepts_minimal_pipeline(self):
        self._validator("pipeline.schema.json").validate(self.PIPELINE)

    def test_pipeline_schema_rejects_unknown_field(self):
        invalid = {**self.PIPELINE, "unexpected": True}

        self._assert_schema_error(
            "pipeline.schema.json",
            invalid,
            (),
            "additionalProperties",
        )

    def test_pipeline_schema_rejects_wrong_version(self):
        invalid = {**self.PIPELINE, "schemaVersion": 2}

        self._assert_schema_error(
            "pipeline.schema.json",
            invalid,
            ("schemaVersion",),
            "const",
        )

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

        self._assert_schema_error(
            "pipeline.schema.json",
            invalid,
            ("stages", 0, "slots", 0, "condition"),
            "oneOf",
        )

    def test_pipeline_conditions_accept_operator_specific_fields_and_values(self):
        conditions = (
            {"eq": ["writeTask", True]},
            {"eq": ["operationType", "review"]},
            {"eq": ["taskArchetype", "bugfix"]},
            {"eq": ["scopeShape", "cross-module"]},
            {"gte": ["complexity", "C2"]},
            {"gte": ["risk", "R2"]},
            {"gte": ["projectMinimums", "Full"]},
            {"gte": ["requirementsMaturity", "defined"]},
            {"gte": ["classificationConfidence", 0.75]},
            {"gte": ["testLevelFloor", "T2"]},
            {"contains": ["explicitModuleIds", "review-independent"]},
            {"contains": ["capabilityStates", "supported"]},
        )

        for condition in conditions:
            with self.subTest(condition=condition):
                errors = list(
                    self._validator("pipeline.schema.json").iter_errors(
                        self._pipeline_with_condition(condition)
                    )
                )
                self.assertEqual(errors, [])

    def test_pipeline_conditions_reject_fields_not_supported_by_operator(self):
        for condition in (
            {"eq": ["explicitModuleIds", "review-independent"]},
            {"gte": ["writeTask", True]},
            {"contains": ["risk", "R1"]},
        ):
            with self.subTest(condition=condition):
                self._assert_condition_error(condition)

    def test_pipeline_conditions_reject_values_with_wrong_type(self):
        for condition in (
            {"eq": ["writeTask", "true"]},
            {"gte": ["classificationConfidence", "high"]},
            {"contains": ["explicitModuleIds", False]},
        ):
            with self.subTest(condition=condition):
                self._assert_condition_error(condition)

    def test_pipeline_conditions_reject_known_type_bypasses(self):
        for condition in (
            {"gte": ["writeTask", None]},
            {"contains": ["risk", False]},
        ):
            with self.subTest(condition=condition):
                self._assert_condition_error(condition)


if __name__ == "__main__":
    unittest.main()
