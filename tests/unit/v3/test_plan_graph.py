import copy
import unittest

from selfworkflow.v3.catalog import CompiledCatalog
from selfworkflow.v3.contracts import validate_plan_graph
from selfworkflow.v3.pipeline import LoadedPipeline
from selfworkflow.v3.plan_graph import PlanGraphArtifact, PlanGraphError, build_plan_graph
from tests.unit.v3.artifact_fixtures import STAGES, load_test_artifacts

def _review_slot(graph):
    document = graph.document
    stage = next(
        item for item in document["stages"] if item["stageId"] == "reviewed"
    )
    return next(
        item for item in stage["slots"] if item["slotId"] == "review.primary"
    )


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
        return load_test_artifacts(
            modules, cardinality=cardinality, mode=mode, condition=condition,
        )

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
        self.assertEqual(
            [stage["stageId"] for stage in first.document["stages"]],
            list(STAGES),
        )
        self.assertEqual(_review_slot(first)["eligibleModules"], ["review-a", "review-b"])
        self.assertEqual(first.document["capabilitySnapshotHash"], second.document["capabilitySnapshotHash"])
        self.assertEqual(first.document["providerBindingHash"], second.document["providerBindingHash"])
        self.assertEqual(
            first.document["moduleConstraints"],
            [
                {
                    "moduleId": "review-a",
                    "stageId": "reviewed",
                    "slotId": "review.primary",
                    "dependencies": [],
                    "conflicts": [],
                    "estimatedContextCost": 10,
                    "estimatedExecutionCost": 5,
                },
                {
                    "moduleId": "review-b",
                    "stageId": "reviewed",
                    "slotId": "review.primary",
                    "dependencies": [],
                    "conflicts": [],
                    "estimatedContextCost": 10,
                    "estimatedExecutionCost": 5,
                },
            ],
        )

    def test_static_selection_is_fixed_and_bounded_selection_starts_empty(self):
        static_catalog, static_pipeline = self._artifacts(
            [_module("review-a", mode="static")], mode="static"
        )
        static = build_plan_graph(self.REQUEST, static_catalog, static_pipeline)
        self.assertEqual(_review_slot(static)["selectedModules"], ["review-a"])

        runtime_catalog, runtime_pipeline = self._artifacts([_module("review-a")])
        runtime = build_plan_graph(self.REQUEST, runtime_catalog, runtime_pipeline)
        self.assertEqual(_review_slot(runtime)["selectedModules"], [])

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

    def test_grill_me_cannot_be_selected_as_a_project_default(self):
        catalog, pipeline = self._artifacts([_module("design-grill-me")])
        request = copy.deepcopy(self.REQUEST)
        request["projectDefaultModuleIds"] = ["design-grill-me"]
        with self.assertRaisesRegex(PlanGraphError, "explicit-only"):
            build_plan_graph(request, catalog, pipeline)

    def test_required_static_slot_cannot_auto_select_explicit_only_grill(self):
        catalog, pipeline = self._artifacts(
            [_module("design-grill-me", mode="static")],
            cardinality="exactly-one", mode="static",
        )
        with self.assertRaisesRegex(PlanGraphError, "explicit-only"):
            build_plan_graph(self.REQUEST, catalog, pipeline)

    def test_gate_cannot_auto_select_module_that_depends_on_explicit_only_grill(self):
        catalog, pipeline = self._artifacts(
            [
                _module("design-grill-me", mode="static"),
                _module(
                    "review-wrapper", mode="static",
                    dependencies=("design-grill-me",),
                ),
            ],
            cardinality="gate", mode="static",
        )
        with self.assertRaisesRegex(PlanGraphError, "explicit-only"):
            build_plan_graph(self.REQUEST, catalog, pipeline)

    def test_dependencies_are_closed_and_inapplicable_slot_is_empty(self):
        catalog, pipeline = self._artifacts([
            _module("review-a", dependencies=("review-dependency",)),
            _module("review-dependency"),
        ])
        graph = build_plan_graph(self.REQUEST, catalog, pipeline)
        slot = _review_slot(graph)
        self.assertEqual(slot["eligibleModules"], ["review-a", "review-dependency"])

        not_applicable_catalog, not_applicable_pipeline = self._artifacts(
            [_module("review-a")], condition={"eq": ["operationType", "implement"]}
        )
        graph = build_plan_graph(self.REQUEST, not_applicable_catalog, not_applicable_pipeline)
        slot = _review_slot(graph)
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

        forged_catalog = object.__new__(CompiledCatalog)
        for name, value in (
            ("_document", copy.deepcopy(catalog.document)),
            ("_content", bytes(catalog.content)),
            ("_catalog_hash", catalog.catalog_hash),
        ):
            object.__setattr__(forged_catalog, name, value)
        if hasattr(forged_catalog, "__dict__"):
            forged_catalog.__dict__.update(
                document=copy.deepcopy(catalog.document),
                content=bytes(catalog.content),
                catalog_hash=catalog.catalog_hash,
            )
        with self.assertRaisesRegex(PlanGraphError, "seal"):
            build_plan_graph(self.REQUEST, forged_catalog, pipeline)
        forged_pipeline = object.__new__(LoadedPipeline)
        for name, value in (
            ("_document", copy.deepcopy(pipeline.document)),
            ("_content", bytes(pipeline.content)),
            ("_pipeline_hash", pipeline.pipeline_hash),
        ):
            object.__setattr__(forged_pipeline, name, value)
        if hasattr(forged_pipeline, "__dict__"):
            forged_pipeline.__dict__.update(
                document=copy.deepcopy(pipeline.document),
                content=bytes(pipeline.content),
                pipeline_hash=pipeline.pipeline_hash,
            )
        with self.assertRaisesRegex(PlanGraphError, "seal"):
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
        next(
            item for item in exposed["stages"] if item["stageId"] == "reviewed"
        )["slots"][0]["eligibleModules"].clear()
        self.assertEqual(
            _review_slot(graph)["eligibleModules"],
            ["review-a"],
        )

    def test_cross_slot_dependency_fails_closed(self):
        catalog, pipeline = self._artifacts([
            _module("review-a", dependencies=("review-dependency",)),
            _module(
                "review-dependency", stage="planned", slot="plan.primary",
            ),
        ])
        with self.assertRaisesRegex(PlanGraphError, "cross-slot-dependency"):
            build_plan_graph(self.REQUEST, catalog, pipeline)

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
            _review_slot(graph)["selectedModules"],
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

    def test_explicit_modules_are_validated_only_against_their_own_slot(self):
        catalog, pipeline = self._artifacts([
            _module(
                "design-precheck", stage="designed", slot="design.precheck",
                mode="static",
            ),
            _module(
                "cpp-core", stage="designed", slot="code.reasoning",
                mode="bounded-runtime",
            ),
        ])
        request = copy.deepcopy(self.REQUEST)
        request["explicitModuleIds"] = ["design-precheck", "cpp-core"]

        graph = build_plan_graph(request, catalog, pipeline)

        designed = next(
            stage for stage in graph.document["stages"]
            if stage["stageId"] == "designed"
        )
        slots = {slot["slotId"]: slot for slot in designed["slots"]}
        self.assertEqual(slots["design.precheck"]["selectedModules"], ["design-precheck"])
        self.assertEqual(slots["code.reasoning"]["eligibleModules"], ["cpp-core"])


if __name__ == "__main__":
    unittest.main()
