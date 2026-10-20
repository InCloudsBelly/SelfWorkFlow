from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]


def create_artifact(root: Path) -> Path:
    artifact = root / "artifact"
    skill = artifact / "skills" / "sample-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: sample-skill\ndescription: Use when testing installation.\n---\n",
        encoding="utf-8",
    )
    (artifact / "WORKFLOW.md").write_text("# Installed workflow\n", encoding="utf-8")
    return artifact


def write_adapter(artifact: Path, adapter_id: str, notes: str) -> Path:
    schema = artifact / "schemas/adapter.schema.json"
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_bytes((REPOSITORY / "schemas/adapter.schema.json").read_bytes())
    adapters = artifact / "adapters"
    (adapters / "shared").mkdir(parents=True, exist_ok=True)
    (adapters / "shared" / "policy.md").write_text(
        (REPOSITORY / "adapters/shared/policy.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    host = adapters / adapter_id
    host.mkdir(parents=True, exist_ok=True)
    (host / "adapter.yaml").write_text(
        "schemaVersion: 1\n"
        f"id: {adapter_id}\n"
        "supportStatus: experimental-unverified\n"
        "entryFile: AGENTS.managed.md\n"
        "capabilities: [global-instructions]\n"
        "coreOverride: forbidden\n"
        "overrideBehavior: managed-file\n",
        encoding="utf-8",
    )
    entry = host / "AGENTS.managed.md"
    entry.write_text(notes, encoding="utf-8")
    return entry
