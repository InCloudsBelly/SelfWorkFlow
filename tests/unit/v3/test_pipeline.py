import importlib.util
import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


_STAGES = (
    "discovered", "capability-checked", "classified", "designed", "planned",
    "implemented", "reviewed", "verified", "completed",
)


@contextmanager
def _pipeline_workspace():
    temporary = TemporaryDirectory()
    root = Path(temporary.name)
    stages = [
        {
            "id": stage_id,
            "slots": [
                {
                    "id": f"{stage_id}.primary",
                    "cardinality": "exactly-one",
                    "allowedInvocationKinds": ["agent-native"],
                    "selectionMode": "static",
                }
            ],
        }
        for stage_id in _STAGES
    ]
    pipeline = {"schemaVersion": 3, "stages": stages}
    path = root / "workflow" / "v3" / "pipeline.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(__import__("yaml").safe_dump(pipeline, sort_keys=False), encoding="utf-8")
    try:
        yield temporary, root, path
    finally:
        temporary.cleanup()


def _loader():
    if importlib.util.find_spec("selfworkflow.v3.pipeline") is None:
        raise AssertionError("v3-pipeline-loader-not-found")
    from selfworkflow.v3.pipeline import PipelineError, load_pipeline

    return PipelineError, load_pipeline


class V3PipelineLoaderTests(unittest.TestCase):
    def test_v3_pipeline_loader_module_exists(self):
        spec = importlib.util.find_spec("selfworkflow.v3.pipeline")
        self.assertIsNotNone(spec, "v3-pipeline-loader-not-found")

    def test_loaded_pipeline_cannot_be_publicly_constructed(self):
        from selfworkflow.v3.pipeline import LoadedPipeline

        with self.assertRaises(TypeError):
            LoadedPipeline({}, b"{}", "sha256:" + "a" * 64)

    def test_public_api_loads_a_deterministic_v3_pipeline(self):
        PipelineError, load_pipeline = _loader()
        with _pipeline_workspace() as (_, _, path):
            loaded = load_pipeline(path)
        self.assertEqual(loaded.document["schemaVersion"], 3)
        self.assertRegex(loaded.pipeline_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(json.loads(loaded.content), loaded.document)

    def test_pipeline_rejects_a_handle_for_a_different_path_snapshot(self):
        PipelineError, load_pipeline = _loader()
        original_open = Path.open
        with _pipeline_workspace() as (_, _, path):
            replacement = path.with_name("replacement.yaml")
            replacement.write_bytes(path.read_bytes())

            def swapped_open(candidate, *args, **kwargs):
                if candidate == path:
                    return original_open(replacement, *args, **kwargs)
                return original_open(candidate, *args, **kwargs)

            with patch.object(Path, "open", new=swapped_open):
                try:
                    load_pipeline(path)
                except Exception as error:
                    self.assertIsInstance(error, PipelineError)
                    self.assertEqual(error.reason, "v3-yaml-path-changed")
                else:
                    self.fail("pipeline accepted bytes from a different path handle")

    def test_only_the_v3_pipeline_path_is_accepted(self):
        PipelineError, load_pipeline = _loader()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            v2 = root / "workflow" / "pipeline.yaml"
            v2.parent.mkdir(parents=True)
            v2.write_text("schemaVersion: 2\n", encoding="utf-8")
            with self.assertRaises(PipelineError) as raised:
                load_pipeline(v2)
        self.assertEqual(raised.exception.reason, "v3-pipeline-path-invalid")
        self.assertNotIn(str(root), str(raised.exception))

    def test_rejects_version_mixing_unknown_fields_duplicate_keys_and_aliases(self):
        PipelineError, load_pipeline = _loader()
        with _pipeline_workspace() as (_, _, path):
            path.write_text("schemaVersion: 2\nstages: []\n", encoding="utf-8")
            with self.assertRaises(PipelineError) as version_error:
                load_pipeline(path)
            self.assertEqual(version_error.exception.reason, "v3-pipeline-version-mismatch")
            path.write_text("schemaVersion: 3\nstages: []\nextra: true\n", encoding="utf-8")
            with self.assertRaises(PipelineError) as field_error:
                load_pipeline(path)
            self.assertEqual(field_error.exception.reason, "v3-pipeline-schema-invalid")
            path.write_text("schemaVersion: 3\nschemaVersion: 3\nstages: []\n", encoding="utf-8")
            with self.assertRaises(PipelineError) as duplicate_error:
                load_pipeline(path)
            self.assertEqual(duplicate_error.exception.reason, "v3-yaml-duplicate-key")
            path.write_text("schemaVersion: 3\nstages: &x []\nalias: *x\n", encoding="utf-8")
            with self.assertRaises(PipelineError) as alias_error:
                load_pipeline(path)
            self.assertEqual(alias_error.exception.reason, "v3-yaml-alias-forbidden")

    def test_rejects_non_utf8_and_multiple_documents(self):
        PipelineError, load_pipeline = _loader()
        with _pipeline_workspace() as (_, _, path):
            path.write_bytes(b"\xff")
            with self.assertRaises(PipelineError) as encoding_error:
                load_pipeline(path)
            self.assertEqual(encoding_error.exception.reason, "v3-yaml-invalid")
            path.write_text("schemaVersion: 3\nstages: []\n---\n{}\n", encoding="utf-8")
            with self.assertRaises(PipelineError) as document_error:
                load_pipeline(path)
            self.assertEqual(document_error.exception.reason, "v3-yaml-multiple-documents")

    def test_rejects_non_json_yaml_scalars_and_complex_mapping_keys(self):
        PipelineError, load_pipeline = _loader()
        with _pipeline_workspace() as (_, _, path):
            document = __import__("yaml").safe_load(path.read_text(encoding="utf-8"))
            document["stages"][0]["slots"][0]["condition"] = {
                "eq": ["operationType", date(2026, 8, 9)]
            }
            path.write_text(
                __import__("yaml").safe_dump(document, sort_keys=False),
                encoding="utf-8",
            )
            try:
                load_pipeline(path)
            except Exception as error:
                self.assertIsInstance(error, PipelineError)
                self.assertEqual(error.reason, "v3-yaml-non-json-compatible")
            else:
                self.fail("timestamp scalar was accepted")

            path.write_text(
                "schemaVersion: 3\nstages: []\n"
                "? [complex, key]\n: rejected\n",
                encoding="utf-8",
            )
            try:
                load_pipeline(path)
            except Exception as error:
                self.assertIsInstance(error, PipelineError)
                self.assertEqual(error.reason, "v3-yaml-non-json-compatible")
            else:
                self.fail("complex mapping key was accepted")

    def test_pipeline_wraps_json_serialization_type_errors(self):
        PipelineError, load_pipeline = _loader()
        with _pipeline_workspace() as (_, _, path):
            with patch(
                "selfworkflow.v3.catalog.json.dumps",
                side_effect=TypeError("injected serialization failure"),
            ):
                try:
                    load_pipeline(path)
                except Exception as error:
                    self.assertIsInstance(error, PipelineError)
                    self.assertEqual(error.reason, "v3-json-serialization-invalid")
                else:
                    self.fail("serialization failure escaped")

    def test_enforces_stage_order_slot_uniqueness_and_condition_contract(self):
        PipelineError, load_pipeline = _loader()
        with _pipeline_workspace() as (_, _, path):
            document = __import__("yaml").safe_load(path.read_text(encoding="utf-8"))
            document["stages"][0], document["stages"][1] = document["stages"][1], document["stages"][0]
            path.write_text(__import__("yaml").safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaises(PipelineError) as order_error:
                load_pipeline(path)
            self.assertEqual(order_error.exception.reason, "v3-pipeline-stage-order-invalid")
            document["stages"][0], document["stages"][1] = document["stages"][1], document["stages"][0]
            document["stages"][1]["slots"][0]["id"] = document["stages"][0]["slots"][0]["id"]
            path.write_text(__import__("yaml").safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaises(PipelineError) as slot_error:
                load_pipeline(path)
            self.assertEqual(slot_error.exception.reason, "v3-pipeline-slot-duplicate")
            document["stages"][1]["slots"][0]["id"] = "capability-checked.primary"
            document["stages"][0]["slots"][0]["condition"] = {"regex": ["operationType", ".*"]}
            path.write_text(__import__("yaml").safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaises(PipelineError) as condition_error:
                load_pipeline(path)
            self.assertEqual(condition_error.exception.reason, "v3-pipeline-schema-invalid")

    def test_hash_is_stable_for_mapping_order_but_pipeline_order_is_semantic(self):
        PipelineError, load_pipeline = _loader()
        with _pipeline_workspace() as (_, _, first_path):
            first = load_pipeline(first_path)
            document = __import__("yaml").safe_load(first_path.read_text(encoding="utf-8"))
            reordered = {"stages": document["stages"], "schemaVersion": document["schemaVersion"]}
            first_path.write_text(__import__("yaml").safe_dump(reordered, sort_keys=False), encoding="utf-8")
            second = load_pipeline(first_path)
            self.assertEqual(first.pipeline_hash, second.pipeline_hash)
            document["stages"][0], document["stages"][1] = document["stages"][1], document["stages"][0]
            first_path.write_text(__import__("yaml").safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaises(PipelineError):
                load_pipeline(first_path)

    def test_checked_in_v3_pipeline_is_the_small_supported_mainline(self):
        PipelineError, load_pipeline = _loader()
        root = Path(__file__).resolve().parents[3]
        loaded = load_pipeline(root / "workflow" / "v3" / "pipeline.yaml")
        self.assertEqual(
            [stage["id"] for stage in loaded.document["stages"]],
            list(_STAGES),
        )
        serialized = loaded.content.decode("utf-8")
        self.assertNotIn("provider", serialized.lower())
        self.assertIn("tea-framework", serialized.lower())
        self.assertIn("tea-ci", serialized.lower())
        self.assertNotIn("c++", serialized.lower())
        slots = {
            slot["id"]: slot
            for stage in loaded.document["stages"]
            for slot in stage["slots"]
        }
        self.assertEqual(slots["knowledge.read"]["cardinality"], "zero-or-one")
        self.assertEqual(slots["knowledge.propose"]["cardinality"], "zero-or-one")
        self.assertEqual(slots["knowledge.update"]["cardinality"], "zero-or-one")
        self.assertIn("mcp", slots["knowledge.update"]["allowedInvocationKinds"])
        test_quality = slots["test.quality.plan"]
        self.assertEqual(
            test_quality["condition"],
            {"all": [
                {"any": [
                    {"eq": ["operationType", "design"]},
                    {"eq": ["operationType", "plan"]},
                    {"eq": ["operationType", "implement"]},
                    {"eq": ["operationType", "debug"]},
                ]},
                {"gte": ["testLevelFloor", "T2"]},
            ]},
        )
        readiness = slots["plan.integrated-review"]
        self.assertEqual(readiness["cardinality"], "exactly-one")
        self.assertEqual(readiness["selectionMode"], "static")
        self.assertEqual(readiness["allowedInvocationKinds"], ["skill"])
        self.assertEqual(
            readiness["condition"],
            {"all": [
                {"any": [
                    {"eq": ["operationType", "design"]},
                    {"eq": ["operationType", "plan"]},
                    {"eq": ["operationType", "implement"]},
                    {"eq": ["operationType", "debug"]},
                ]},
                {"any": [
                    {"gte": ["complexity", "C2"]},
                    {"gte": ["risk", "R2"]},
                    {"gte": ["projectMinimums", "Full"]},
                ]},
            ]},
        )
        deep_grill = slots["design.deep-grill"]
        self.assertEqual(
            deep_grill["condition"],
            {"all": [
                {"any": [
                    {"eq": ["operationType", "design"]},
                    {"eq": ["operationType", "plan"]},
                    {"eq": ["operationType", "implement"]},
                    {"eq": ["operationType", "debug"]},
                ]},
                {"any": [
                    {"gte": ["complexity", "C3"]},
                    {"gte": ["risk", "R3"]},
                    {"gte": ["projectMinimums", "Deep"]},
                    {"contains": ["explicitModuleIds", "design-grill-me"]},
                ]},
            ]},
        )
        from selfworkflow.v3.plan_graph import _condition_matches
        self.assertFalse(_condition_matches(
            readiness["condition"],
            {
                "operationType": "analyze", "complexity": "C3",
                "risk": "R3", "projectMinimums": {"strength": "Deep"},
            },
        ))
        self.assertTrue(_condition_matches(
            readiness["condition"],
            {
                "operationType": "plan", "complexity": "C1",
                "risk": "R1", "projectMinimums": {"strength": "Full"},
            },
        ))
        self.assertFalse(_condition_matches(
            test_quality["condition"],
            {"operationType": "analyze", "testLevelFloor": "T3"},
        ))
        self.assertTrue(_condition_matches(
            test_quality["condition"],
            {"operationType": "plan", "testLevelFloor": "T2"},
        ))
        self.assertFalse(_condition_matches(
            deep_grill["condition"],
            {
                "operationType": "analyze", "complexity": "C3",
                "risk": "R3", "projectMinimums": {"strength": "Deep"},
            },
        ))
        self.assertTrue(_condition_matches(
            deep_grill["condition"],
            {
                "operationType": "plan", "complexity": "C1",
                "risk": "R1", "projectMinimums": {"strength": "Deep"},
            },
        ))
        self.assertEqual(
            slots["implement.orchestrator"]["condition"],
            {"all": [
                {"eq": ["writeTask", True]},
                {"eq": ["operationType", "implement"]},
                {"not": {"contains": ["explicitModuleIds", "implement-spec"]}},
            ]},
        )


if __name__ == "__main__":
    unittest.main()
