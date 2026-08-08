"""Real loader-backed V3 artifacts for PlanGraph and selector tests."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from selfworkflow.v3.catalog import compile_catalog
from selfworkflow.v3.pipeline import load_pipeline


STAGES = (
    "discovered", "capability-checked", "classified", "designed", "planned",
    "implemented", "reviewed", "verified", "completed",
)


def _write_yaml(path: Path, document: object) -> str:
    content = yaml.safe_dump(
        document, sort_keys=False, allow_unicode=True,
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return "sha256:" + hashlib.sha256(content).hexdigest()


def load_test_artifacts(
    modules: list[dict],
    *,
    cardinality: str = "exactly-one",
    mode: str = "bounded-runtime",
    condition: dict | None = None,
):
    """Compile real files and load a complete nine-stage pipeline."""

    with TemporaryDirectory() as directory:
        root = Path(directory)
        module_refs = []
        for module in modules:
            module_id = module["id"]
            ref = f"modules/{module_id}.yaml"
            module_refs.append({
                "id": module_id,
                "ref": ref,
                "hash": _write_yaml(root / "catalog" / "v3" / ref, module),
            })
        index = {
            "schemaVersion": 3,
            "domains": [],
            "modules": module_refs,
        }
        index_path = root / "catalog" / "v3" / "index.yaml"
        _write_yaml(index_path, index)

        module_slots: dict[tuple[str, str], str] = {}
        for module in modules:
            key = (module["stage"], module["slot"])
            existing = module_slots.setdefault(key, module["selectionMode"])
            if existing != module["selectionMode"]:
                raise AssertionError("test modules disagree on slot selection mode")
        stages = []
        for stage_id in STAGES:
            slots = []
            for (module_stage, slot_id), selection_mode in sorted(
                module_slots.items(), key=lambda item: item[0][1],
            ):
                if module_stage != stage_id:
                    continue
                is_target = stage_id == "reviewed" and slot_id == "review.primary"
                slot = {
                    "id": slot_id,
                    "cardinality": cardinality if is_target else "zero-or-many",
                    "allowedInvocationKinds": ["agent-native"],
                    "selectionMode": mode if is_target else selection_mode,
                }
                if is_target and condition is not None:
                    slot["condition"] = condition
                slots.append(slot)
            if not slots:
                slots.append({
                    "id": f"{stage_id}.primary",
                    "cardinality": "zero-or-many",
                    "allowedInvocationKinds": ["agent-native"],
                    "selectionMode": "static",
                })
            stages.append({"id": stage_id, "slots": slots})
        pipeline_path = root / "workflow" / "v3" / "pipeline.yaml"
        _write_yaml(
            pipeline_path, {"schemaVersion": 3, "stages": stages},
        )
        return compile_catalog(index_path), load_pipeline(pipeline_path)
