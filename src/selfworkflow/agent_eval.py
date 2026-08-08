"""Isolated Agent-eval runner used by the PowerShell entry point."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

from jsonschema import Draft202012Validator


class AgentEvalError(RuntimeError):
    pass


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _read_bounded(path: Path, limit: int = 2 * 1024 * 1024) -> bytes:
    if not path.is_file() or path.stat().st_size > limit:
        raise AgentEvalError
    return path.read_bytes()


def _git(command: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *command], cwd=cwd, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise AgentEvalError
    return result.stdout


def run_eval(arguments: argparse.Namespace) -> Path:
    agent = Path(arguments.agent_command).resolve(strict=True)
    scenario = Path(arguments.scenario).resolve(strict=True)
    schema_path = Path(arguments.schema).resolve(strict=True)
    output_root = Path(arguments.output_root).resolve(strict=False)
    mode = arguments.mode
    if mode not in {"baseline", "skilled", "blind", "review"}:
        raise AgentEvalError
    if not 1 <= arguments.timeout_seconds <= 3600:
        raise AgentEvalError
    skill = Path(arguments.skill).resolve(strict=True) if arguments.skill else None
    input_run = (
        Path(arguments.input_run).resolve(strict=True) if arguments.input_run else None
    )
    if mode in {"skilled", "blind"} and skill is None:
        raise AgentEvalError
    if mode == "review" and input_run is None:
        raise AgentEvalError
    if mode == "baseline" and (skill is not None or input_run is not None):
        raise AgentEvalError

    scenario_bytes = _read_bounded(scenario)
    schema_bytes = _read_bounded(schema_path)
    schema = json.loads(schema_bytes)
    Draft202012Validator.check_schema(schema)
    run_id = f"{mode}-{uuid4().hex}"
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = output_root / run_id
    run_root.mkdir()
    last_message = run_root / "last-message.json"
    raw_stdout = run_root / "raw.jsonl"
    raw_stderr = run_root / "stderr.txt"

    with tempfile.TemporaryDirectory(
        prefix="selfworkflow-agent-eval-", ignore_cleanup_errors=True
    ) as temporary:
        sandbox = Path(temporary)
        scenario_copy = sandbox / "scenario.yaml"
        schema_copy = sandbox / "schema.json"
        scenario_copy.write_bytes(scenario_bytes)
        schema_copy.write_bytes(schema_bytes)
        prompt_parts = [
            "Evaluate the supplied scenario. Return only JSON matching schema.json.",
            f"Mode: {mode}",
            f"Model: {arguments.model}",
            f"Reasoning effort: {arguments.reasoning_effort}",
            scenario_bytes.decode("utf-8"),
        ]
        skill_hash = None
        if skill is not None:
            skill_bytes = _read_bounded(skill)
            skill_target = sandbox / ".agents" / "skills" / "code-quality" / "SKILL.md"
            skill_target.parent.mkdir(parents=True)
            skill_target.write_bytes(skill_bytes)
            skill_hash = _hash_bytes(skill_bytes)
            prompt_parts.append("Read and apply .agents/skills/code-quality/SKILL.md.")
        input_hash = None
        if input_run is not None:
            input_bytes = _read_bounded(input_run)
            input_hash = _hash_bytes(input_bytes)
            prompt_parts.append(input_bytes.decode("utf-8"))

        _git(["init", "-q"], sandbox)
        _git(["add", "."], sandbox)
        _git(
            [
                "-c",
                "user.name=SelfWorkFlow Eval",
                "-c",
                "user.email=selfworkflow-eval@example.invalid",
                "commit",
                "-q",
                "-m",
                "eval input",
            ],
            sandbox,
        )
        before_tree = _git(["rev-parse", "HEAD^{tree}"], sandbox).strip()
        command = [str(agent)]
        if agent.suffix.casefold() == ".py":
            command = [sys.executable, str(agent)]
        command.extend(
            [
                "exec",
                "--ephemeral",
                "--json",
                "--sandbox",
                "read-only",
                "--ask-for-approval",
                "never",
                "--output-schema",
                str(schema_copy),
                "--output-last-message",
                str(last_message),
                "--model",
                arguments.model,
                "-c",
                f"model_reasoning_effort={arguments.reasoning_effort}",
                "\n\n".join(prompt_parts),
            ]
        )
        try:
            completed = subprocess.run(
                command,
                cwd=sandbox,
                check=False,
                capture_output=True,
                timeout=arguments.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raw_stdout.write_bytes(error.stdout or b"")
            raw_stderr.write_bytes(error.stderr or b"")
            raise AgentEvalError from None
        raw_stdout.write_bytes(completed.stdout)
        raw_stderr.write_bytes(completed.stderr)
        if completed.returncode != 0 or not last_message.is_file():
            raise AgentEvalError
        status = _git(["status", "--porcelain=v1"], sandbox)
        after_tree = _git(["write-tree"], sandbox).strip()
        if status or after_tree != before_tree:
            raise AgentEvalError

    result_bytes = _read_bounded(last_message)
    result = json.loads(result_bytes)
    Draft202012Validator(schema).validate(result)
    if (
        result["model"] != arguments.model
        or result["reasoningEffort"] != arguments.reasoning_effort
    ):
        raise AgentEvalError
    evidence = {
        "schemaVersion": 1,
        "runId": run_id,
        "mode": mode,
        "model": arguments.model,
        "reasoningEffort": arguments.reasoning_effort,
        "agentHash": _hash_bytes(_read_bounded(agent, 64 * 1024 * 1024)),
        "scenarioHash": _hash_bytes(scenario_bytes),
        "schemaHash": _hash_bytes(schema_bytes),
        "skillHash": skill_hash,
        "inputRunHash": input_hash,
        "resultHash": _hash_bytes(result_bytes),
        "sandboxTreeHash": before_tree,
    }
    evidence_path = run_root / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return evidence_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="selfworkflow-agent-eval")
    parser.add_argument("--agent-command", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--timeout-seconds", required=True, type=int)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--skill")
    parser.add_argument("--input-run")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        path = run_eval(_parser().parse_args(argv))
    except (AgentEvalError, OSError, ValueError, json.JSONDecodeError):
        print("SelfWorkFlow: agent-eval-failed", file=sys.stderr)
        return 30
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
