from pathlib import Path


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
