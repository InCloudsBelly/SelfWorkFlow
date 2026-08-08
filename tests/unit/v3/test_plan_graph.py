import copy
import hashlib
import json
import unittest

from selfworkflow.v3.catalog import CompiledCatalog
from selfworkflow.v3.contracts import ContractError, validate_plan_graph
from selfworkflow.v3.pipeline import LoadedPipeline
from selfworkflow.v3.plan_graph import PlanGraphArtifact, PlanGraphError, build_plan_graph


def _hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _module(module_id, *, slot="review.primary", mode="bounded-runtime",
            dependencies=(), conflicts=(), support=None, context=10, execution=5,
            stage="reviewed"):
    return {
        "schemaVersion": 3,
        "id": module_id,
        "sourceHash": "sha256:" + ("a" * 64),
        "stage": stage,
        "slot": slot,
        "selectionMode": mode,
        "invocation": {"kind": "agent-native", "ref": module_id},
        "dependencies": list(dependencies),
        "conflicts": list(conflicts),
        "contextCost": {"estimatedContextCost": context, "estimatedExecutionCost": execution},
        "supportEvidence": support or {
            "sourceIntegrity": "supported",
            "adapterSupport": "supported",
            "runtimeCapability": "supported",
            "behaviorEvidence": "supported",
        },
    }


class PlanGraphTests(unittest.TestCase):
    REQUEST = {
        "schemaVersion": 3,
        "operationType": "review",
        "complexity": "C2",
        "risk": "R2",
        "writeTask": False,
        "ambiguity": False,
        "explicitModuleIds": [],
        "projectDefaultModuleIds": [],
        "projectMinimums": {"strength": "Full"},
        "capabilityEvidenceSnapshot": {
            "schemaVersion": 1,
            "capturedAt": "2026-08-09T00:00:00Z",
            "evidence": [],
        },
        "taskArchetype": "bounded-feature",
        "requirementsMaturity": "approved",
        "scopeShape": "single-module",
        "durableSpec": True,
        "classificationConfidence": 1.0,
        "classificationEvidence": [{
            "evidenceRef": "classification-1",
            "evidenceHash": "sha256:" + "a" * 64,
            "classifierVersion": "classifier-v1",
            "classifierHash": "sha256:" + "b" * 64,
        }],
        "testLevelFloor": "T2",
    }

    def _artifacts(self, modules, *, cardinality="exactly-one", mode="bounded-runtime",
                   condition=None):
        catalog = {
            "schemaVersion": 3,
            "domains": [],
            "modules": modules,
        }
        catalog["catalogHash"] = _hash({**catalog})
        pipeline = {
            "schemaVersion": 3,
            "stages": [{"id": "reviewed", "slots": [{
                "id": "review.primary",
                "cardinality": cardinality,
                "allowedInvocationKinds": ["agent-native"],
                "selectionMode": mode,
                **({"condition": condition} if condition else {}),
            }]}],
        }
        envelope = {
            "schemaVersion": 3,
            "catalog": catalog,
            "catalogHash": catalog["catalogHash"],
        }
        return CompiledCatalog(
            envelope,
            _canonical(envelope),
            catalog["catalogHash"],
        ), LoadedPipeline(pipeline, _canonical(pipeline), _hash(pipeline))

    def test_builds_schema_valid_deterministic_plan_with_all_snapshot_hashes(self):
        catalog, pipeline = self._artifacts([
            _module("review-a"), _module("review-b"),
        ])
        first = build_plan_graph(
            self.REQUEST, catalog, pipeline,
            capability_snapshot=copy.deepcopy(self.REQUEST["capabilityEvidenceSnapshot"]),
            provider_preference_snapshot={"providers": ["builtin"]},
            provider_binding_snapshot={"bindings": []},
            execution_policy_snapshot={"network": "deny"},
        )
        second = build_plan_graph(
            copy.deepcopy(self.REQUEST), catalog, pipeline,
            capability_snapshot=copy.deepcopy(self.REQUEST["capabilityEvidenceSnapshot"]),
            provider_preference_snapshot={"providers": ["builtin"]},
            provider_binding_snapshot={"bindings": []},
            execution_policy_snapshot={"network": "deny"},
        )
        validate_plan_graph(first.document)
        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertEqual(first.document["planHash"], first.plan_hash)
        self.assertEqual(first.document["stages"][0]["ordinal"], 1)
        self.assertEqual(first.document["stages"][0]["slots"][0]["eligibleModules"], ["review-a", "review-b"])
        self.assertEqual(first.document["capabilitySnapshotHash"], second.document["capabilitySnapshotHash"])
        self.assertEqual(first.document["providerBindingHash"], second.document["providerBindingHash"])

    def test_static_selection_is_fixed_and_bounded_selection_starts_empty(self):
        static_catalog, static_pipeline = self._artifacts(
            [_module("review-a", mode="static")], mode="static"
        )
        static = build_plan_graph(self.REQUEST, static_catalog, static_pipeline)
        self.assertEqual(static.document["stages"][0]["slots"][0]["selectedModules"], ["review-a"])

        runtime_catalog, runtime_pipeline = self._artifacts([_module("review-a")])
        runtime = build_plan_graph(self.REQUEST, runtime_catalog, runtime_pipeline)
        self.assertEqual(runtime.document["stages"][0]["slots"][0]["selectedModules"], [])

    def test_explicit_unknown_duplicate_conflicting_or_unsupported_input_fails_closed(self):
        catalog, pipeline = self._artifacts([
            _module("review-a", conflicts=("review-b",)),
            _module("review-b", conflicts=("review-a",)),
        ])
        unknown = copy.deepcopy(self.REQUEST)
        unknown["explicitModuleIds"] = ["not-in-catalog"]
        with self.assertRaisesRegex(PlanGraphError, "unknown"):
            build_plan_graph(unknown, catalog, pipeline)

        duplicate = copy.deepcopy(self.REQUEST)
        duplicate["explicitModuleIds"] = ["review-a", "review-a"]
        with self.assertRaisesRegex(PlanGraphError, "duplicate"):
            build_plan_graph(duplicate, catalog, pipeline)

        conflicting = copy.deepcopy(self.REQUEST)
        conflicting["explicitModuleIds"] = ["review-a", "review-b"]
        with self.assertRaisesRegex(PlanGraphError, "conflict"):
            build_plan_graph(conflicting, catalog, pipeline)

        unsupported = copy.deepcopy(self.REQUEST)
        unsupported["explicitModuleIds"] = ["review-a"]
        unsupported_catalog, unsupported_pipeline = self._artifacts([
            _module("review-a", support={
                "sourceIntegrity": "supported", "adapterSupport": "unsupported",
                "runtimeCapability": "supported", "behaviorEvidence": "supported",
            })
        ])
        with self.assertRaisesRegex(PlanGraphError, "unsupported"):
            build_plan_graph(unsupported, unsupported_catalog, unsupported_pipeline)

    def test_dependencies_are_closed_and_inapplicable_slot_is_empty(self):
        catalog, pipeline = self._artifacts([
            _module("review-a", dependencies=("review-dependency",)),
            _module("review-dependency"),
        ])
        graph = build_plan_graph(self.REQUEST, catalog, pipeline)
        slot = graph.document["stages"][0]["slots"][0]
        self.assertEqual(slot["eligibleModules"], ["review-a", "review-dependency"])

        not_applicable_catalog, not_applicable_pipeline = self._artifacts(
            [_module("review-a")], condition={"eq": ["operationType", "implement"]}
        )
        graph = build_plan_graph(self.REQUEST, not_applicable_catalog, not_applicable_pipeline)
        slot = graph.document["stages"][0]["slots"][0]
        self.assertEqual(slot["applicability"], "not-applicable")
        self.assertEqual(slot["eligibleModules"], [])
        self.assertEqual(slot["selectedModules"], [])

    def test_explicit_module_in_an_inapplicable_slot_fails_closed(self):
        catalog, pipeline = self._artifacts(
            [_module("review-a")], condition={"eq": ["operationType", "implement"]}
        )
        request = copy.deepcopy(self.REQUEST)
        request["explicitModuleIds"] = ["review-a"]
        with self.assertRaisesRegex(PlanGraphError, "inapplicable"):
            build_plan_graph(request, catalog, pipeline)

    def test_required_module_without_eligible_provider_is_blocked_at_build(self):
        catalog, pipeline = self._artifacts([
            _module("review-a", support={
                "sourceIntegrity": "supported", "adapterSupport": "unverified",
                "runtimeCapability": "supported", "behaviorEvidence": "supported",
            })
        ])
        with self.assertRaisesRegex(PlanGraphError, "required-module"):
            build_plan_graph(self.REQUEST, catalog, pipeline)

    def test_rejects_mapping_and_forged_compiled_artifacts(self):
        catalog, pipeline = self._artifacts([_module("review-a")])
        with self.assertRaisesRegex(PlanGraphError, "compiled"):
            build_plan_graph(self.REQUEST, catalog.document, pipeline)
        with self.assertRaisesRegex(PlanGraphError, "loaded"):
            build_plan_graph(self.REQUEST, catalog, pipeline.document)

        forged_catalog = CompiledCatalog(
            copy.deepcopy(catalog.document), b"forged", catalog.catalog_hash,
        )
        with self.assertRaisesRegex(PlanGraphError, "content"):
            build_plan_graph(self.REQUEST, forged_catalog, pipeline)
        forged_pipeline = LoadedPipeline(
            copy.deepcopy(pipeline.document), b"forged", pipeline.pipeline_hash,
        )
        with self.assertRaisesRegex(PlanGraphError, "content"):
            build_plan_graph(self.REQUEST, catalog, forged_pipeline)

    def test_capability_snapshot_parameter_must_equal_request_snapshot(self):
        catalog, pipeline = self._artifacts([_module("review-a")])
        matching = copy.deepcopy(self.REQUEST["capabilityEvidenceSnapshot"])
        build_plan_graph(
            self.REQUEST, catalog, pipeline, capability_snapshot=matching,
        )
        mismatched = copy.deepcopy(matching)
        mismatched["capturedAt"] = "2026-08-09T00:00:01Z"
        with self.assertRaisesRegex(PlanGraphError, "capability-snapshot-mismatch"):
            build_plan_graph(
                self.REQUEST, catalog, pipeline,
                capability_snapshot=mismatched,
            )

    def test_plan_artifact_is_builder_only_and_document_access_is_a_copy(self):
        with self.assertRaises(TypeError):
            PlanGraphArtifact({}, ())
        catalog, pipeline = self._artifacts([_module("review-a")])
        graph = build_plan_graph(self.REQUEST, catalog, pipeline)
        exposed = graph.document
        exposed["stages"][0]["slots"][0]["eligibleModules"].clear()
        self.assertEqual(
            graph.document["stages"][0]["slots"][0]["eligibleModules"],
            ["review-a"],
        )

    def test_cross_slot_dependency_fails_closed(self):
        catalog, pipeline = self._artifacts([
            _module("review-a", dependencies=("review-dependency",)),
            _module(
                "review-dependency", stage="planned", slot="plan.primary",
            ),
        ])
        pipeline_document = {
            "schemaVersion": 3,
            "stages": [
                {"id": "planned", "slots": [{
                    "id": "plan.primary", "cardinality": "zero-or-many",
                    "allowedInvocationKinds": ["agent-native"],
                    "selectionMode": "bounded-runtime",
                }]},
                *pipeline.document["stages"],
            ],
        }
        loaded = LoadedPipeline(
            pipeline_document, _canonical(pipeline_document), _hash(pipeline_document),
        )
        with self.assertRaisesRegex(PlanGraphError, "cross-slot-dependency"):
            build_plan_graph(self.REQUEST, catalog, loaded)

    def test_static_selection_closes_dependencies_or_fails_cardinality(self):
        catalog, pipeline = self._artifacts(
            [
                _module(
                    "review-a", mode="static",
                    dependencies=("review-dependency",),
                ),
                _module("review-dependency", mode="static"),
            ],
            cardinality="zero-or-many",
            mode="static",
        )
        request = copy.deepcopy(self.REQUEST)
        request["explicitModuleIds"] = ["review-a"]
        graph = build_plan_graph(request, catalog, pipeline)
        self.assertEqual(
            graph.document["stages"][0]["slots"][0]["selectedModules"],
            ["review-a", "review-dependency"],
        )

        exactly_one_catalog, exactly_one_pipeline = self._artifacts(
            [
                _module(
                    "review-a", mode="static",
                    dependencies=("review-dependency",),
                ),
                _module("review-dependency", mode="static"),
            ],
            cardinality="exactly-one",
            mode="static",
        )
        with self.assertRaisesRegex(PlanGraphError, "static-selection"):
            build_plan_graph(request, exactly_one_catalog, exactly_one_pipeline)

    def test_dependency_closure_internal_conflict_fails_explicit_module(self):
        catalog, pipeline = self._artifacts([
            _module(
                "review-a", dependencies=("review-dependency",),
                conflicts=("review-dependency",),
            ),
            _module("review-dependency", conflicts=("review-a",)),
        ])
        request = copy.deepcopy(self.REQUEST)
        request["explicitModuleIds"] = ["review-a"]
        with self.assertRaisesRegex(PlanGraphError, "dependency-unavailable"):
            build_plan_graph(request, catalog, pipeline)


if __name__ == "__main__":
    unittest.main()
