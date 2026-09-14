"""Command-line entry point for SelfWorkFlow."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unicodedata

from selfworkflow import __version__
from selfworkflow.catalog import compile_catalog
from selfworkflow.adapters import build_runtime
from selfworkflow.installer import (
    apply_install_plan,
    apply_rollback_plan,
    create_install_plan,
    create_rollback_plan,
    doctor,
    verify_install,
)
from selfworkflow.quality import (
    build_review_package,
    capture_review_baseline,
    run_verification,
    validate_completion,
)
from selfworkflow.resolver import resolve_task
from selfworkflow.ledger import validate_ledger
from selfworkflow.git_policy import check_repository
from selfworkflow.project_review import (
    ProjectReviewProfileError,
    load_project_review_profile,
)
from selfworkflow.review_models import (
    ReviewModelConfigError,
    resolve_review_model,
    save_review_model,
)
from selfworkflow.work_artifacts import WorkArtifactError, WorkArtifactManager
from selfworkflow.ponytail_source import PonytailSourceError, verify_ponytail_source
from selfworkflow.sources import (
    commit_superpowers_migration,
    recover_superpowers_migration,
    remove_staged_superpowers_source,
    SourceSelectionError,
    inspect_superpowers_source,
    stage_superpowers_source,
)
from selfworkflow.transactions import write_json_atomic


_REPARSE_POINT = 0x400


class _SubprocessCommandPort:
    """Shell-free process boundary used only by the explicit Provider CLI."""

    def run(self, argv, *, cwd=None):
        from selfworkflow.v3.providers.codegraph import CommandResult

        try:
            result = subprocess.run(
                list(argv), cwd=cwd, check=False, capture_output=True,
                text=True, timeout=120,
            )
        except Exception:
            return CommandResult(exit_code=9009)
        return CommandResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def _provider_config_file(value: str | None) -> Path:
    from selfworkflow.v3.provider_config import provider_config_path

    expected = provider_config_path().resolve(strict=False)
    if value is None:
        return expected
    candidate = _absolute_path(value).resolve(strict=False)
    if candidate != expected:
        raise ValueError("provider-config-path-outside-machine-root")
    return candidate


def _provider_manager(config_file: str | None):
    from selfworkflow.v3.provider_manager import MachineLocalPaths, ProviderManager

    return ProviderManager(
        paths=MachineLocalPaths(config_file=_provider_config_file(config_file)),
        command_port=_SubprocessCommandPort(),
        source_identity_resolver=_inspect_provider_source_identity,
    )


def _inspect_provider_source_identity(source_value: str):
    """Inspect only the explicitly configured provider checkout."""
    source = _absolute_path(source_value).resolve(strict=True)
    package = source / "package.json"
    if package.is_file() and not package.is_symlink():
        try:
            package_name = json.loads(package.read_text(encoding="utf-8")).get("name")
        except (OSError, UnicodeError, ValueError, AttributeError):
            package_name = None
        if package_name == "@nanonets/graft":
            from selfworkflow.v3.graft_source import inspect_graft_source_path
            return inspect_graft_source_path(str(source))
    return _inspect_codegraph_source_identity(str(source))


def _inspect_codegraph_source_identity(source_value: str) -> dict[str, object]:
    """Hash a CodeGraph checkout without executing code from that checkout."""
    source = _absolute_path(source_value).resolve(strict=True)
    script = source / "dist" / "bin" / "codegraph.js"
    path_chain = (source, source / "dist", source / "dist" / "bin", script)
    if (
        not script.is_file()
        or any(not item.exists() or _is_reparse(item) for item in path_chain)
    ):
        raise ValueError("codegraph-source-invalid")
    if script.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("codegraph-source-inspection-failed")

    def git_bytes(*arguments: str, limit: int = 16 * 1024 * 1024) -> bytes:
        environment = os.environ.copy()
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
        })
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", *arguments],
            cwd=source, check=False, capture_output=True, timeout=120,
            env=environment,
        )
        if result.returncode != 0 or len(result.stdout) > limit:
            raise ValueError("codegraph-source-inspection-failed")
        return result.stdout

    top = Path(git_bytes("rev-parse", "--show-toplevel").decode("utf-8").strip())
    if top.resolve(strict=True) != source:
        raise ValueError("codegraph-source-invalid")
    commit = git_bytes("rev-parse", "HEAD").decode("ascii").strip().lower()
    tree = git_bytes("rev-parse", "HEAD^{tree}").decode("ascii").strip().lower()
    status = git_bytes(
        "status", "--porcelain=v1", "-z", "--untracked-files=normal",
        limit=1024 * 1024,
    )
    relevant_diff = git_bytes(
        "diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--",
        "dist", "package.json",
        "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    )
    source_material = {
        "commit": commit,
        "tree": tree,
        "statusHash": "sha256:" + hashlib.sha256(status).hexdigest(),
        "relevantDiffHash": "sha256:" + hashlib.sha256(relevant_diff).hexdigest(),
        "entryHash": "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest(),
    }
    source_hash = "sha256:" + hashlib.sha256(
        json.dumps(source_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "source": source,
        "script": script,
        "report": {
            "providerId": "codegraph",
            "sourceType": "local-git",
            "commit": commit,
            "dirty": bool(status),
            "sourceHash": source_hash,
            "supportStatus": "unverified",
        },
    }


def _inspect_codegraph_source(source_value: str) -> dict[str, object]:
    """Inspect source identity without executing code from the checkout."""
    observation = _inspect_codegraph_source_identity(source_value)
    observation["report"]["version"] = "unverified"
    return observation


def _configure_codegraph(
    manager, source_value: str, *, replace_existing: bool = False,
    expected_source_hash: str | None = None,
    rollback_token: str | None = None,
) -> dict[str, object]:
    observation = _inspect_codegraph_source(source_value)
    report = observation["report"]
    if (
        expected_source_hash is not None
        and expected_source_hash != report["sourceHash"]
    ):
        raise ValueError("codegraph-source-drift")
    return manager.configure(
        provider_id="codegraph",
        source_path=str(observation["source"]),
        command_prefix=("node", str(observation["script"])),
        ownership="user-local",
        source_version=str(report["version"]),
        source_commit=str(report["commit"]),
        source_hash=str(report["sourceHash"]),
        dirty=bool(report["dirty"]),
        replace_existing=replace_existing,
        rollback_token=rollback_token,
    )


def _configure_graft(
    manager, source_value: str, *, replace_existing: bool = False,
    expected_source_hash: str | None = None,
    rollback_token: str | None = None,
) -> dict[str, object]:
    from selfworkflow.v3.graft_source import GraftSourceError, inspect_graft_source_path

    try:
        observation = inspect_graft_source_path(source_value)
    except GraftSourceError as error:
        raise ValueError(error.reason) from None
    report = observation["report"]
    if (
        expected_source_hash is not None
        and expected_source_hash != report["sourceHash"]
    ):
        raise ValueError("graft-source-drift")
    if report["dirty"]:
        raise ValueError("graft-source-dirty")
    source = Path(observation["source"])
    return manager.configure(
        provider_id="graft",
        source_path=str(source),
        command_prefix=("node", str(source / "dist" / "cli.js")),
        ownership="selfworkflow-managed",
        source_version=str(report["version"]),
        source_commit=str(report["commit"]),
        source_hash=str(report["sourceHash"]),
        dirty=False,
        replace_existing=replace_existing,
        rollback_token=rollback_token,
    )


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("json-input-invalid")
        result[key] = value
    return result


def _absolute_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def _is_reparse(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _validate_output_path(source: Path, output: Path) -> tuple[Path, Path]:
    lexical_candidates = (output, *output.parents)
    if any(
        _is_reparse(path)
        for path in lexical_candidates
        if path.exists() or path.is_symlink()
    ):
        raise ValueError("output-path-invalid")
    repository_root = source.parent.resolve(strict=True)
    resolved_source = source.resolve(strict=True)
    resolved_output = output.resolve(strict=False)
    if unicodedata.normalize("NFC", str(output)) != str(output):
        raise ValueError("output-path-invalid")
    try:
        resolved_output.relative_to(repository_root)
    except ValueError:
        raise ValueError("output-path-invalid") from None
    try:
        resolved_output.relative_to(resolved_source)
    except ValueError:
        pass
    else:
        raise ValueError("output-path-invalid")

    current = resolved_output
    existing: list[Path] = []
    while True:
        if current.exists() or current.is_symlink():
            existing.append(current)
        if current == repository_root:
            break
        parent = current.parent
        if parent == current:
            raise ValueError("output-path-invalid")
        current = parent
    if any(_is_reparse(path) for path in existing):
        raise ValueError("output-path-invalid")
    return repository_root, resolved_output


def _publish_catalog(source_value: str, output_value: str) -> str:
    source = _absolute_path(source_value)
    output = _absolute_path(output_value)
    _, resolved_output = _validate_output_path(source, output)
    compiled = compile_catalog(source)

    parent = resolved_output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=parent,
            prefix=".catalog-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(compiled.content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, resolved_output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return compiled.catalog_hash


def _resolve_by_version(
    catalog_content: bytes,
    request: dict[str, object],
    *,
    catalog_source: object = None,
    pipeline_source: object = None,
) -> dict[str, object]:
    """Dispatch only on an explicit request version; never downgrade unknown input."""

    version = request.get("schemaVersion")
    if version == 3:
        from selfworkflow.v3.resolver import resolve_request

        return resolve_request(
            request,
            catalog_source=catalog_source if catalog_source is not None else catalog_content,
            pipeline_source=pipeline_source,
        )
    if version in {1, 2}:
        return resolve_task(catalog_content, request)
    raise ValueError("unsupported-contract-version")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="selfworkflow")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    catalog = commands.add_parser("catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command")
    compile_parser = catalog_commands.add_parser("compile")
    compile_parser.add_argument("--source", required=True)
    compile_parser.add_argument("--output", required=True)
    doctor_parser = commands.add_parser("doctor")
    doctor_parser.add_argument("--agents-root", required=True)
    doctor_parser.add_argument("--codex-root", required=True)
    doctor_parser.add_argument("--state-root", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--repository", default=str(Path.cwd()))
    build_parser.add_argument("--output", required=True)
    build_parser.add_argument("--version", default=__version__)
    build_parser.add_argument(
        "--profile",
        choices=("core", "knowledge", "maintainer"),
        default="core",
    )
    build_parser.add_argument("--without-grill-me", action="store_true")
    resolve_parser = commands.add_parser("resolve")
    resolve_parser.add_argument("--catalog", required=True)
    resolve_parser.add_argument("--request", required=True)
    ledger_parser = commands.add_parser("ledger")
    ledger_commands = ledger_parser.add_subparsers(dest="ledger_command", required=True)
    ledger_validate = ledger_commands.add_parser("validate")
    ledger_validate.add_argument("--ledger", required=True)
    ledger_validate.add_argument("--plan", required=True)
    ledger_validate.add_argument("--capability-snapshot", required=True)
    git_policy_parser = commands.add_parser("git-policy")
    git_policy_commands = git_policy_parser.add_subparsers(dest="git_policy_command", required=True)
    git_policy_check = git_policy_commands.add_parser("check")
    git_policy_check.add_argument("--repo", required=True)
    git_policy_check.add_argument("--policy")
    source_parser = commands.add_parser("source")
    source_commands = source_parser.add_subparsers(
        dest="source_command", required=True
    )
    source_inspect = source_commands.add_parser("inspect")
    source_inspect.add_argument("--path", required=True)
    source_stage = source_commands.add_parser("stage")
    source_stage.add_argument("--path", required=True)
    source_stage.add_argument("--target", required=True)
    source_stage.add_argument("--expected-inventory-hash", required=True)
    source_stage.add_argument("--allow-compatible-link", action="store_true")
    source_stage.add_argument("--state-root")
    source_stage.add_argument("--migration-journal")
    source_stage.add_argument("--migration-backup")
    source_stage.add_argument("--protected-root", action="append", default=[])
    source_recover = source_commands.add_parser("recover-migration")
    source_recover.add_argument("--journal", required=True)
    source_recover.add_argument("--if-exists", action="store_true")
    source_commit = source_commands.add_parser("commit-migration")
    source_commit.add_argument("--journal", required=True)
    source_remove = source_commands.add_parser("remove-stage")
    source_remove.add_argument("--target", required=True)
    source_remove.add_argument("--expected-inventory-hash", required=True)
    source_ponytail = source_commands.add_parser("ponytail-verify")
    source_ponytail.add_argument("--repository", required=True)
    provider_parser = commands.add_parser("provider")
    provider_commands = provider_parser.add_subparsers(
        dest="provider_command", required=True,
    )
    provider_list = provider_commands.add_parser("list")
    provider_list.add_argument("--config-file")
    provider_inspect = provider_commands.add_parser("inspect")
    inspect_paths = provider_inspect.add_mutually_exclusive_group(required=True)
    inspect_paths.add_argument("--codegraph-path")
    inspect_paths.add_argument("--graft-path")
    provider_configure = provider_commands.add_parser("configure")
    provider_configure.add_argument("--config-file")
    configure_paths = provider_configure.add_mutually_exclusive_group(required=True)
    configure_paths.add_argument("--codegraph-path")
    configure_paths.add_argument("--graft-path")
    provider_configure.add_argument("--replace-existing", action="store_true")
    provider_configure.add_argument("--expected-source-hash")
    provider_configure.add_argument("--rollback-token")
    provider_rollback = provider_commands.add_parser("rollback-config")
    provider_rollback.add_argument("--config-file")
    provider_rollback.add_argument("--rollback-token", required=True)
    provider_rollback.add_argument("--if-issued", action="store_true")
    provider_commit = provider_commands.add_parser("commit-config")
    provider_commit.add_argument("--config-file")
    provider_commit.add_argument("--rollback-token", required=True)
    provider_doctor = provider_commands.add_parser("doctor")
    provider_doctor.add_argument("--config-file")
    provider_doctor.add_argument("--provider-id", default="codegraph")
    provider_status = provider_commands.add_parser("status")
    provider_status.add_argument("--config-file")
    provider_status.add_argument("--provider-id", default="graft")
    provider_status.add_argument("--project-root", required=True)
    provider_maintain = provider_commands.add_parser("maintain")
    provider_maintain.add_argument("--config-file")
    provider_maintain.add_argument("--provider-id", default="codegraph")
    provider_maintain.add_argument(
        "--action", required=True, choices=("initialize", "sync", "rebuild"),
    )
    provider_maintain.add_argument("--project-root", required=True)
    provider_maintain.add_argument("--plan-only", action="store_true")
    provider_maintain.add_argument("--confirm-plan-hash")
    provider_query = provider_commands.add_parser("query")
    provider_query.add_argument("--config-file")
    provider_query.add_argument("--provider-id", default="graft")
    provider_query.add_argument("--project-root", required=True)
    provider_query.add_argument("--query", required=True)
    provider_query.add_argument(
        "--query-kind", choices=("ask", "map", "grep", "callers", "skeleton"),
        default="ask",
    )
    graft_preflight = provider_commands.add_parser("graft-preflight")
    graft_preflight.add_argument("--config-file")
    graft_preflight.add_argument("--project-root", required=True)
    graft_event = provider_commands.add_parser("graft-event")
    graft_event.add_argument("--config-file")
    graft_event.add_argument("--project-root", required=True)
    graft_event.add_argument("--changed-path", action="append", required=True)
    graft_worker = provider_commands.add_parser("graft-worker")
    graft_worker.add_argument("--config-file")
    graft_worker.add_argument("--project-root", required=True)
    graft_deep = provider_commands.add_parser("graft-deep")
    graft_deep.add_argument("--config-file")
    graft_deep.add_argument("--project-root", required=True)
    graft_deep.add_argument("--model", required=True)
    graft_deep.add_argument("--reasoning-effort", required=True)
    graft_deep.add_argument("--topic-id", required=True)
    graft_deep.add_argument("--scope-file", action="append", required=True)
    install = commands.add_parser("install")
    install_commands = install.add_subparsers(dest="install_command", required=True)
    install_plan = install_commands.add_parser("plan")
    install_plan.add_argument("--artifact", required=True)
    install_plan.add_argument("--agents-root", required=True)
    install_plan.add_argument("--codex-root", required=True)
    install_plan.add_argument("--state-root", required=True)
    install_plan.add_argument("--version", required=True)
    install_plan.add_argument("--output", required=True)
    install_apply = install_commands.add_parser("apply")
    install_apply.add_argument("--plan", required=True)
    install_apply.add_argument("--confirm-plan-hash", required=True)
    install_verify = install_commands.add_parser("verify")
    install_verify.add_argument("--manifest", required=True)
    rollback_plan = install_commands.add_parser("rollback-plan")
    rollback_plan.add_argument("--transaction", required=True)
    rollback_plan.add_argument("--output", required=True)
    rollback_apply = install_commands.add_parser("rollback")
    rollback_apply.add_argument("--plan", required=True)
    rollback_apply.add_argument("--confirm-plan-hash", required=True)
    quality = commands.add_parser("quality")
    quality_commands = quality.add_subparsers(dest="quality_command", required=True)
    quality_capture = quality_commands.add_parser("capture")
    quality_capture.add_argument("--repository", required=True)
    quality_capture.add_argument("--path", action="append", required=True)
    quality_capture.add_argument("--output", required=True)
    quality_package = quality_commands.add_parser("package")
    quality_package.add_argument("--repository", required=True)
    quality_package.add_argument("--baseline", required=True)
    quality_package.add_argument("--specification", required=True)
    quality_package.add_argument("--verification-plans", required=True)
    quality_package.add_argument("--output", required=True)
    quality_verify = quality_commands.add_parser("verify")
    quality_verify.add_argument("--repository", required=True)
    quality_verify.add_argument("--package", required=True)
    quality_verify.add_argument("--plan-id", required=True)
    quality_verify.add_argument("--output", required=True)
    quality_complete = quality_commands.add_parser("complete")
    quality_complete.add_argument("--repository", required=True)
    quality_complete.add_argument("--baseline", required=True)
    quality_complete.add_argument("--specification", required=True)
    quality_complete.add_argument("--package", required=True)
    quality_complete.add_argument("--reviews", required=True)
    project_review = commands.add_parser("project-review")
    project_review_commands = project_review.add_subparsers(
        dest="project_review_command", required=True,
    )
    project_review_validate = project_review_commands.add_parser("validate")
    project_review_validate.add_argument("--project-root", required=True)
    review_model = commands.add_parser("review-model")
    review_model_commands = review_model.add_subparsers(
        dest="review_model_command", required=True,
    )
    review_model_status = review_model_commands.add_parser("status")
    review_model_status.add_argument("--agent", required=True)
    review_model_status.add_argument("--config-file")
    review_model_set = review_model_commands.add_parser("set")
    review_model_set.add_argument("--agent", required=True)
    review_model_set.add_argument("--model", required=True)
    review_model_set.add_argument("--reasoning-effort", required=True)
    review_model_set.add_argument("--config-file")
    review_model_set.add_argument(
        "--confirm", action="store_true",
        help="确认把该选择写入机器本地默认配置",
    )
    artifact = commands.add_parser("artifact")
    artifact_commands = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_transition = artifact_commands.add_parser("transition")
    artifact_transition.add_argument("--project-root", required=True)
    artifact_transition.add_argument("--task-id", required=True)
    artifact_transition.add_argument("--event", required=True)
    artifact_transition.add_argument("--expected-content-generation", type=int, required=True)
    artifact_transition.add_argument("--expected-state-revision", type=int, required=True)
    artifact_transition.add_argument("--expected-manifest-hash")
    artifact_transition.add_argument("--operation-nonce", required=True)
    artifact_transition.add_argument("--artifacts")
    artifact_transition.add_argument("--review")
    artifact_transition.add_argument("--verification")
    artifact_transition.add_argument("--publication")
    artifact_transition.add_argument("--confirmed-by-user", action="store_true")
    artifact_reconcile = artifact_commands.add_parser("reconcile")
    artifact_reconcile.add_argument("--project-root", required=True)
    artifact_reconcile.add_argument("--task-id", required=True)
    artifact_reconcile.add_argument("--mode", choices=("dry-run", "apply"), required=True)
    artifact_reconcile.add_argument("--expected-content-generation", type=int, required=True)
    artifact_reconcile.add_argument("--expected-state-revision", type=int, required=True)
    artifact_reconcile.add_argument("--expected-manifest-hash", required=True)
    artifact_reconcile.add_argument("--plan-hash")
    arguments = parser.parse_args(argv)
    if arguments.command == "project-review":
        try:
            result = load_project_review_profile(arguments.project_root).as_dict()
        except ProjectReviewProfileError:
            print("SelfWorkFlow: project-review-profile-invalid", file=sys.stderr)
            return 53
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 53 if result["status"] == "unverified" and result["blocking"] else 0
    if arguments.command == "review-model":
        try:
            if arguments.review_model_command == "status":
                result = resolve_review_model(
                    arguments.agent, arguments.config_file,
                ).as_dict()
            elif arguments.review_model_command == "set":
                result = save_review_model(
                    arguments.config_file,
                    arguments.agent,
                    arguments.model,
                    arguments.reasoning_effort,
                    confirmed=arguments.confirm,
                ).as_dict()
            else:
                raise ReviewModelConfigError("review-model-command-invalid")
        except ReviewModelConfigError as error:
            print(
                f"SelfWorkFlow: review-model-operation-failed:{error.reason}",
                file=sys.stderr,
            )
            return 54
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    if arguments.command == "artifact":
        try:
            manager = WorkArtifactManager(arguments.project_root, arguments.task_id)

            def optional_payload(path):
                if path is None:
                    return None
                return _read_json(path, reject_duplicates=True)

            if arguments.artifact_command == "transition":
                artifacts_payload = optional_payload(arguments.artifacts)
                artifacts = None if artifacts_payload is None else artifacts_payload.get("artifacts")
                result = manager.transition(
                    arguments.expected_content_generation,
                    arguments.expected_state_revision,
                    arguments.expected_manifest_hash,
                    arguments.event,
                    artifacts,
                    operation_nonce=arguments.operation_nonce,
                    review=optional_payload(arguments.review),
                    verification=optional_payload(arguments.verification),
                    publication=optional_payload(arguments.publication),
                    confirmed_by_user=arguments.confirmed_by_user,
                )
            elif arguments.artifact_command == "reconcile":
                result = manager.reconcile(
                    arguments.mode,
                    arguments.expected_content_generation,
                    arguments.expected_state_revision,
                    arguments.expected_manifest_hash,
                    arguments.plan_hash,
                )
            else:
                raise WorkArtifactError("artifact-command-invalid")
        except WorkArtifactError as error:
            payload = {"status": "error", "error": {"code": error.reason}}
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 70
        except Exception:
            print(json.dumps({"status": "error", "error": {"code": "artifact-operation-failed"}}, ensure_ascii=False, separators=(",", ":")))
            return 70
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    if arguments.command == "quality":
        try:
            if arguments.quality_command == "capture":
                result = capture_review_baseline(arguments.repository, arguments.path)
                write_json_atomic(_absolute_path(arguments.output), result)
            elif arguments.quality_command == "package":
                plans = _read_json(arguments.verification_plans, reject_duplicates=True)
                result = build_review_package(
                    arguments.repository,
                    _read_json(arguments.baseline, reject_duplicates=True),
                    _read_json(arguments.specification, reject_duplicates=True),
                    plans.get("plans"),
                )
                write_json_atomic(_absolute_path(arguments.output), result)
            elif arguments.quality_command == "verify":
                result = run_verification(
                    arguments.repository,
                    _read_json(arguments.package, reject_duplicates=True),
                    arguments.plan_id,
                )
                write_json_atomic(_absolute_path(arguments.output), result)
            elif arguments.quality_command == "complete":
                reviews = _read_json(arguments.reviews, reject_duplicates=True)
                result = validate_completion(
                    arguments.repository,
                    _read_json(arguments.baseline, reject_duplicates=True),
                    _read_json(arguments.specification, reject_duplicates=True),
                    _read_json(arguments.package, reject_duplicates=True),
                    reviews.get("reviews"),
                )
            else:
                raise ValueError("quality-command-invalid")
        except Exception as error:
            reason = getattr(error, "reason", "quality-operation-failed")
            print(f"SelfWorkFlow: quality-operation-failed:{reason}", file=sys.stderr)
            return 73
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    if arguments.command == "provider":
        try:
            if arguments.provider_command == "inspect":
                if arguments.graft_path:
                    from selfworkflow.v3.graft_source import inspect_graft_source_path
                    result = inspect_graft_source_path(arguments.graft_path)["report"]
                else:
                    result = _inspect_codegraph_source(arguments.codegraph_path)["report"]
            else:
                manager = _provider_manager(arguments.config_file)
            if arguments.provider_command == "list":
                result = manager.list_providers()
            elif arguments.provider_command == "configure":
                if arguments.graft_path:
                    result = _configure_graft(
                        manager, arguments.graft_path,
                        replace_existing=arguments.replace_existing,
                        expected_source_hash=arguments.expected_source_hash,
                        rollback_token=arguments.rollback_token,
                    )
                else:
                    result = _configure_codegraph(
                        manager, arguments.codegraph_path,
                        replace_existing=arguments.replace_existing,
                        expected_source_hash=arguments.expected_source_hash,
                        rollback_token=arguments.rollback_token,
                    )
            elif arguments.provider_command == "rollback-config":
                result = manager.rollback_config(
                    arguments.rollback_token, if_issued=arguments.if_issued,
                )
            elif arguments.provider_command == "commit-config":
                result = manager.commit_config(arguments.rollback_token)
            elif arguments.provider_command == "doctor":
                result = manager.doctor(arguments.provider_id)
            elif arguments.provider_command == "status":
                result = manager.status(arguments.provider_id, arguments.project_root)
            elif arguments.provider_command == "maintain":
                plan = manager.maintain(
                    arguments.provider_id, arguments.action,
                    arguments.project_root, plan_only=True,
                )
                if arguments.plan_only:
                    result = plan
                else:
                    if not arguments.confirm_plan_hash:
                        raise ValueError("provider-maintenance-confirmation-required")
                    result = manager.maintain(
                        arguments.provider_id, arguments.action,
                        arguments.project_root, plan_only=False,
                        confirmed_plan_hash=arguments.confirm_plan_hash,
                    )
            elif arguments.provider_command == "query":
                result = manager.query(
                    arguments.provider_id, arguments.project_root, arguments.query,
                    query_kind=arguments.query_kind,
                )
            elif arguments.provider_command == "graft-preflight":
                result = manager.graft_preflight(arguments.project_root)
            elif arguments.provider_command == "graft-event":
                result = manager.graft_enqueue(
                    arguments.project_root, arguments.changed_path,
                )
            elif arguments.provider_command == "graft-worker":
                result = manager.graft_worker(arguments.project_root)
            elif arguments.provider_command == "graft-deep":
                result = manager.graft_deep(
                    arguments.project_root, arguments.model,
                    arguments.reasoning_effort,
                    topic_id=arguments.topic_id,
                    scope_files=arguments.scope_file,
                )
            elif arguments.provider_command == "inspect":
                pass
            else:
                raise ValueError("provider-command-invalid")
        except Exception as error:
            reason = getattr(error, "reason", "provider-operation-failed")
            print(f"SelfWorkFlow: provider-operation-failed:{reason}", file=sys.stderr)
            return 70
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        if (
            arguments.provider_command == "graft-deep"
            and (not isinstance(result, dict) or result.get("status") != "succeeded")
        ):
            return 71
        return 0
    if arguments.command == "catalog" and arguments.catalog_command == "compile":
        try:
            catalog_hash = _publish_catalog(arguments.source, arguments.output)
        except Exception:
            print("SelfWorkFlow: catalog-compile-failed", file=sys.stderr)
            return 20
        print(catalog_hash)
        return 0
    if arguments.command == "resolve":
        try:
            catalog_path = _absolute_path(arguments.catalog)
            if (
                not catalog_path.is_file()
                or catalog_path.stat().st_size > 16 * 1024 * 1024
            ):
                raise ValueError("catalog-input-invalid")
            request = _read_json(arguments.request, reject_duplicates=True)
            result = _resolve_by_version(
                catalog_path.read_bytes(), request,
                catalog_source=catalog_path,
            )
        except Exception:
            print("SelfWorkFlow: resolve-failed", file=sys.stderr)
            return 50
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if arguments.command == "ledger" and arguments.ledger_command == "validate":
        try:
            plan = _read_json(arguments.plan, reject_duplicates=True)
            ledger_value = _read_json(arguments.ledger, reject_duplicates=True)
            capability_snapshot = _read_json(
                arguments.capability_snapshot, reject_duplicates=True
            )
            result = validate_ledger(
                ledger_value, plan, capability_snapshot
            )
        except Exception:
            print("SelfWorkFlow: ledger-validation-failed", file=sys.stderr)
            return 51
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if result["valid"] else 51
    if arguments.command == "git-policy" and arguments.git_policy_command == "check":
        try:
            repository = _absolute_path(arguments.repo).resolve(strict=True)
            policy = arguments.policy or str(repository / "workflow/git-policy.yaml")
            result = check_repository(repository, policy)
        except Exception:
            print("SelfWorkFlow: git-policy-check-failed", file=sys.stderr)
            return 52
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 52 if result["status"] == "failed" else 0
    if arguments.command == "source" and arguments.source_command == "inspect":
        try:
            result = inspect_superpowers_source(arguments.path)
        except SourceSelectionError as error:
            print(f"SelfWorkFlow: source-inspect-failed:{error}", file=sys.stderr)
            return 60
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if arguments.command == "source" and arguments.source_command == "ponytail-verify":
        try:
            result = verify_ponytail_source(arguments.repository)
        except PonytailSourceError as error:
            print(
                f"SelfWorkFlow: ponytail-source-verification-failed:{error}",
                file=sys.stderr,
            )
            return 63
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    if arguments.command == "source" and arguments.source_command == "stage":
        try:
            result = stage_superpowers_source(
                arguments.path,
                arguments.target,
                arguments.expected_inventory_hash,
                allow_compatible_link=arguments.allow_compatible_link,
                state_root=arguments.state_root,
                migration_journal=arguments.migration_journal,
                migration_backup=arguments.migration_backup,
                protected_roots=tuple(arguments.protected_root),
            )
        except SourceSelectionError as error:
            print(f"SelfWorkFlow: source-stage-failed:{error}", file=sys.stderr)
            return 61
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if arguments.command == "source" and arguments.source_command in {
        "recover-migration", "commit-migration", "remove-stage",
    }:
        try:
            if arguments.source_command == "recover-migration":
                result = recover_superpowers_migration(
                    arguments.journal, if_exists=arguments.if_exists
                )
            elif arguments.source_command == "commit-migration":
                result = commit_superpowers_migration(arguments.journal)
            else:
                result = remove_staged_superpowers_source(
                    arguments.target, arguments.expected_inventory_hash
                )
        except SourceSelectionError as error:
            print(f"SelfWorkFlow: source-migration-failed:{error}", file=sys.stderr)
            return 62
        print(
            json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        )
        return 0
    try:
        if arguments.command == "doctor":
            result = doctor(
                arguments.agents_root, arguments.codex_root, arguments.state_root
            )
        elif arguments.command == "build":
            result = build_runtime(
                arguments.repository,
                arguments.output,
                arguments.version,
                profile=arguments.profile,
                include_grill_me=not arguments.without_grill_me,
            )
        elif arguments.command == "install" and arguments.install_command == "plan":
            result = create_install_plan(
                arguments.artifact,
                arguments.agents_root,
                arguments.codex_root,
                arguments.state_root,
                arguments.version,
            )
            write_json_atomic(_absolute_path(arguments.output), result)
        elif arguments.command == "install" and arguments.install_command == "apply":
            result = apply_install_plan(
                _read_json(arguments.plan), arguments.confirm_plan_hash
            )
        elif arguments.command == "install" and arguments.install_command == "verify":
            result = verify_install(arguments.manifest)
        elif arguments.command == "install" and arguments.install_command == "rollback-plan":
            result = create_rollback_plan(arguments.transaction, arguments.output)
        elif arguments.command == "install" and arguments.install_command == "rollback":
            result = apply_rollback_plan(
                _read_json(arguments.plan), arguments.confirm_plan_hash
            )
        else:
            return 0
    except Exception:
        print("SelfWorkFlow: install-operation-failed", file=sys.stderr)
        return 40
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


def _read_json(value: str, *, reject_duplicates: bool = False) -> dict[str, object]:
    path = _absolute_path(value)
    if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("json-input-invalid")
    text = path.read_text(encoding="utf-8")
    result = (
        json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
        if reject_duplicates
        else json.loads(text)
    )
    if not isinstance(result, dict):
        raise ValueError("json-input-invalid")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
