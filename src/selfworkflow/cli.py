"""Command-line entry point for SelfWorkFlow."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

from selfworkflow import __version__
from selfworkflow.catalog import compile_catalog
from selfworkflow.adapters import build_runtime
from selfworkflow.documents import DocumentError, publish_documents, document_binding, render_document_instruction
from selfworkflow.installer import (
    InstallerError,
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


class _SourceInspectionError(ValueError):
    def __init__(self, cause: str, operation: str, exit_code: int | None = None):
        self.reason = "provider-source-inspection-failed"
        self.diagnostics = {"failureStage": "source-inspection", "cause": cause, "operation": operation}
        if exit_code is not None:
            self.diagnostics["exitCode"] = exit_code
        super().__init__(self.reason)


class _SubprocessCommandPort:
    """Shell-free process boundary used only by the explicit Provider CLI."""

    def run(self, argv, *, cwd=None):
        from selfworkflow.v3.providers.codegraph import CommandResult

        started = time.monotonic()
        try:
            entry = Path(argv[0])
            if entry.suffix.casefold() in {".cmd", ".bat"} or entry.name.casefold() in {"cmd", "cmd.exe"}:
                raise OSError("Batch provider entries are not supported; rebind the native runtime.")
            result = subprocess.run(
                list(argv), cwd=cwd, check=False, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=3600,
            )
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                if isinstance(value, bytes):
                    return value.decode("utf-8", errors="replace")
                return value or ""

            return CommandResult(
                exit_code=9009, stdout=decoded(error.stdout), stderr=decoded(error.stderr),
                failure_kind="timeout", duration_ms=int((time.monotonic() - started) * 1000),
                timeout_ms=3600000, exception_type=type(error).__name__,
            )
        except OSError as error:
            return CommandResult(
                exit_code=9009, failure_kind="start-failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                timeout_ms=3600000, exception_type=type(error).__name__,
            )
        return CommandResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=int((time.monotonic() - started) * 1000),
            timeout_ms=3600000,
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
    """Inspect only the explicitly configured CodeGraph source or runtime."""
    try:
        return _inspect_codegraph_source_identity(str(source_value))
    except _SourceInspectionError:
        raise
    except OSError:
        raise _SourceInspectionError("read-failed", "metadata") from None
    except ValueError:
        raise _SourceInspectionError("invalid-source", "metadata") from None


def _codegraph_runtime_material(source: Path, node: Path, trees: tuple[Path, ...]) -> dict[str, object]:
    digests = {}

    def digest(path: Path) -> str:
        if path in digests:
            return digests[path]
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
        digests[path] = value.hexdigest()
        return digests[path]

    def link_target(path: Path) -> Path:
        target = path.resolve(strict=True)
        if not any(target.is_relative_to(root) for root in trees):
            raise ValueError("codegraph-source-invalid")
        return target

    files = {}
    for root in trees:
        if not root.exists():
            continue
        if not root.is_dir() or _is_reparse(root):
            raise ValueError("codegraph-source-invalid")
        for parent, directories, names in os.walk(root, followlinks=False):
            for name in directories[:]:
                path = Path(parent) / name
                if _is_reparse(path):
                    target = link_target(path)
                    files[path.relative_to(source).as_posix()] = "link:" + target.relative_to(source).as_posix()
                    directories.remove(name)
            for name in names:
                path = Path(parent) / name
                if _is_reparse(path):
                    target = link_target(path)
                    files[path.relative_to(source).as_posix()] = "link:" + target.relative_to(source).as_posix()
                    path = target
                if not path.is_file():
                    raise ValueError("codegraph-source-invalid")
                files[path.relative_to(source).as_posix()] = digest(path)
    for name in ("package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "VERSION", "version.txt"):
        path = source / name
        if path.is_file() and name not in files:
            if _is_reparse(path):
                raise ValueError("codegraph-source-invalid")
            files[name] = digest(path)
    return {"nodePath": str(node), "nodeHash": digest(node), "files": files}


def _inspect_codegraph_source_identity(source_value: str) -> dict[str, object]:
    """Hash a CodeGraph checkout or managed runtime without executing it."""
    from selfworkflow.codegraph_ue import SOURCE_PATH, codegraph_ue_node, codegraph_ue_runtime_trees, verify_codegraph_ue_build

    source = _absolute_path(source_value).resolve(strict=True)
    managed_submodule = source.as_posix().endswith("/" + SOURCE_PATH)
    local_script = source / "dist" / "bin" / "codegraph.js"
    managed_script = source / "lib" / "dist" / "bin" / "codegraph.js"
    if managed_script.is_file():
        source_type = "managed-runtime"
        script = managed_script
        node = source / "node.exe"
        path_chain = (source, source / "lib", source / "lib" / "dist", script.parent, script, node)
        command_prefix = (str(node), "--liftoff-only", "--disable-warning=ExperimentalWarning", str(script))
    elif local_script.is_file() and not _is_reparse(local_script):
        source_type = "local-git"
        script = local_script
        path_chain = (source, source / "dist", source / "dist" / "bin", script)
        node_value = codegraph_ue_node(source) if managed_submodule else None
        node_value = node_value or shutil.which("node.exe") or shutil.which("node")
        if node_value is None:
            raise ValueError("codegraph-source-invalid")
        node = Path(node_value).resolve(strict=True)
        command_prefix = (str(node), str(script))
    else:
        raise ValueError("codegraph-source-invalid")
    if any(not item.exists() or _is_reparse(item) for item in path_chain):
        raise ValueError("codegraph-source-invalid")
    if not node.is_file() or _is_reparse(node):
        raise ValueError("codegraph-source-invalid")
    if script.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("codegraph-source-inspection-failed")

    package_candidates = [source / "lib" / "package.json", source / "package.json"] if source_type == "managed-runtime" else [source / "package.json"]
    nested_package = source / "node_modules" / "@colbymchenry" / "codegraph" / "package.json"
    if nested_package not in package_candidates:
        package_candidates.append(nested_package)
    package_path = next((item for item in package_candidates if item.is_file() and not _is_reparse(item)), None)
    package_value = {}
    if package_path is not None:
        try:
            package_value = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise ValueError("codegraph-source-inspection-failed") from None
        if not isinstance(package_value, dict):
            raise ValueError("codegraph-source-inspection-failed")
        package_name = package_value.get("name")
        if package_name not in {None, "@colbymchenry/codegraph"}:
            raise ValueError("codegraph-source-invalid")

    version = package_value.get("version") if isinstance(package_value.get("version"), str) else None
    if version is None and source_type == "managed-runtime":
        for marker in (source / "VERSION", source / "version.txt"):
            if marker.is_file() and not _is_reparse(marker):
                value = marker.read_text(encoding="utf-8").strip()
                if value:
                    version = value.splitlines()[0]
                    break

    def git_bytes(*arguments: str, limit: int = 16 * 1024 * 1024) -> bytes:
        environment = os.environ.copy()
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
        })
        try:
            result = subprocess.run(
                ["git", "-c", "safe.directory=", "-c", f"safe.directory={source.as_posix()}",
                 "-c", "core.fsmonitor=false", *arguments],
                cwd=source, check=False, capture_output=True, timeout=120,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            raise _SourceInspectionError("timeout", arguments[0]) from None
        except OSError:
            raise _SourceInspectionError("start-failed", arguments[0]) from None
        if result.returncode != 0:
            stderr = result.stderr.lower()
            cause = "dubious-ownership" if b"dubious ownership" in stderr else "git-command-failed"
            if b"not a git repository" in stderr:
                cause = "not-a-repository"
            raise _SourceInspectionError(cause, arguments[0], result.returncode)
        if len(result.stdout) > limit:
            raise _SourceInspectionError("output-limit", arguments[0])
        return result.stdout

    runtime = _codegraph_runtime_material(
        source, node,
        ((source / "lib",) if source_type == "managed-runtime" else
         codegraph_ue_runtime_trees(source) if managed_submodule else (source / "dist", source / "node_modules")),
    )
    runtime["commandPrefix"] = command_prefix
    if source_type == "local-git":
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
            "dist", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
        )
        source_material = {
            "commit": commit,
            "tree": tree,
            "statusHash": "sha256:" + hashlib.sha256(status).hexdigest(),
            "relevantDiffHash": "sha256:" + hashlib.sha256(relevant_diff).hexdigest(),
            "runtime": runtime,
        }
        dirty = bool(status)
    else:
        source_material = {"runtime": runtime, "version": version or "unverified"}
        commit = hashlib.sha256(json.dumps(source_material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:40]
        dirty = False
    source_hash = "sha256:" + hashlib.sha256(
        json.dumps(source_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if managed_submodule:
        verify_codegraph_ue_build(source, runtime)
        source_type = "managed-submodule"
    return {
        "source": source,
        "script": script,
        "report": {
            "providerId": "codegraph",
            "sourceType": source_type,
            "commit": commit,
            "dirty": dirty,
            "sourceHash": source_hash,
            "version": version or "unverified",
            "commandPrefix": command_prefix,
            "supportStatus": "unverified",
        },
    }


def _inspect_codegraph_source(source_value: str) -> dict[str, object]:
    """Inspect source identity without executing code from the checkout."""
    observation = _inspect_provider_source_identity(source_value)
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
        command_prefix=tuple(report["commandPrefix"]),
        ownership=(
            "selfworkflow-managed"
            if report.get("sourceType") in {"managed-runtime", "managed-submodule"} else "user-local"
        ),
        source_version=str(report["version"]),
        source_commit=str(report["commit"]),
        source_hash=str(report["sourceHash"]),
        dirty=bool(report["dirty"]),
        source_kind=("managed-submodule" if report.get("sourceType") == "managed-submodule" else None),
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
    doctor_parser.add_argument("--dsh-root")
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
    documents = commands.add_parser("documents", help="Publish or inspect portable workflow documents (maintainer only).")
    document_commands = documents.add_subparsers(dest="document_command", required=True)
    document_publish = document_commands.add_parser("publish")
    document_publish.add_argument("--repository", default=str(Path.cwd()))
    document_publish.add_argument("--output", required=True)
    for action in ("check", "snippet"):
        document_action = document_commands.add_parser(action)
        document_action.add_argument("--root", required=True)
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
    wiki_parser = commands.add_parser("wiki")
    wiki_commands = wiki_parser.add_subparsers(dest="wiki_command", required=True)
    wiki_inspect = wiki_commands.add_parser("inspect")
    wiki_inspect.add_argument("--repository", required=True)
    for action in ("register", "doctor"):
        wiki_action = wiki_commands.add_parser(action)
        wiki_action.add_argument("--repository", required=True)
        wiki_action.add_argument("--config")
        if action == "register":
            wiki_action.add_argument("--confirm-plan-hash")
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
    source_codegraph_ue = source_commands.add_parser("codegraph-ue-prepare")
    source_codegraph_ue.add_argument("--repository", required=True)
    provider_parser = commands.add_parser("provider")
    provider_commands = provider_parser.add_subparsers(
        dest="provider_command", required=True,
    )
    provider_list = provider_commands.add_parser("list")
    provider_list.add_argument("--config-file")
    provider_inspect = provider_commands.add_parser("inspect")
    provider_inspect.add_argument("--codegraph-path", required=True)
    provider_configure = provider_commands.add_parser("configure")
    provider_configure.add_argument("--config-file")
    provider_configure.add_argument("--codegraph-path", required=True)
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
    provider_status.add_argument("--provider-id", default="codegraph")
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
    provider_query.add_argument("--provider-id", default="codegraph")
    provider_query.add_argument("--project-root", required=True)
    provider_query.add_argument("--query", required=True)
    provider_query.add_argument(
        "--query-kind", choices=("ask", "map", "grep", "callers", "skeleton"),
        default="ask",
    )
    provider_preflight = provider_commands.add_parser("preflight")
    provider_preflight.add_argument("--config-file")
    provider_preflight.add_argument("--project-root", required=True)
    provider_ensure = provider_commands.add_parser("ensure")
    provider_ensure.add_argument("--config-file")
    provider_ensure.add_argument("--project-root", required=True)
    provider_sync = provider_commands.add_parser("sync")
    provider_sync.add_argument("--config-file")
    provider_sync.add_argument("--project-root", required=True)
    provider_sync.add_argument("--changed-path", action="append", default=[])
    provider_retire = provider_commands.add_parser("retire")
    provider_retire.add_argument("--config-file")
    provider_retire.add_argument("--provider-id", required=True)
    install = commands.add_parser("install")
    install_commands = install.add_subparsers(dest="install_command", required=True)
    install_plan = install_commands.add_parser("plan")
    install_plan.add_argument("--artifact", required=True)
    install_plan.add_argument("--agents-root", required=True)
    install_plan.add_argument("--codex-root", required=True)
    install_plan.add_argument("--dsh-root")
    install_plan.add_argument("--document-root", help="Link the stable public document entry and retire managed native Skill copies.")
    install_plan.add_argument("--state-root", required=True)
    install_plan.add_argument("--version", required=True)
    install_plan.add_argument("--output", required=True)
    install_plan.add_argument("--host-launcher")
    install_plan.add_argument("--host-python")
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
    if arguments.command == "wiki":
        from .wiki_module import WikiModuleError, inspect_wiki_module, register_wiki_mcp, doctor_wiki_module

        try:
            if arguments.wiki_command == "register":
                result = register_wiki_mcp(arguments.repository, arguments.config,
                                           confirm_plan_hash=arguments.confirm_plan_hash)
            elif arguments.wiki_command == "doctor":
                result = doctor_wiki_module(arguments.repository, arguments.config)
            else:
                result = inspect_wiki_module(arguments.repository)
        except WikiModuleError as error:
            print(f"SelfWorkFlow: wiki-module-inspection-failed:{error}", file=sys.stderr)
            return 78
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    if arguments.command == "provider":
        try:
            if arguments.provider_command == "inspect":
                result = _inspect_codegraph_source(arguments.codegraph_path)["report"]
            else:
                manager = _provider_manager(arguments.config_file)
            if arguments.provider_command == "list":
                result = manager.list_providers()
            elif arguments.provider_command == "configure":
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
                result = manager.status(
                    arguments.provider_id, arguments.project_root,
                )
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
            elif arguments.provider_command in {"preflight", "ensure"}:
                result = manager.preflight(arguments.project_root)
            elif arguments.provider_command == "sync":
                result = manager.sync(arguments.project_root, arguments.changed_path)
            elif arguments.provider_command == "retire":
                result = manager.retire(arguments.provider_id)
            elif arguments.provider_command == "inspect":
                pass
            else:
                raise ValueError("provider-command-invalid")
        except Exception as error:
            reason = getattr(error, "reason", "provider-operation-failed")
            print(f"SelfWorkFlow: provider-operation-failed:{reason}", file=sys.stderr)
            if reason in {"provider-source-inspection-failed", "provider-source-identity-drift"}:
                print(json.dumps({"error": reason, "diagnostics": getattr(error, "diagnostics", None)},
                                 ensure_ascii=False, sort_keys=True), file=sys.stderr)
            return 70
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
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
    if arguments.command == "source" and arguments.source_command == "codegraph-ue-prepare":
        from selfworkflow.codegraph_ue import prepare_codegraph_ue

        try:
            result = prepare_codegraph_ue(arguments.repository)
        except ValueError as error:
            reason = str(error)
            if re.fullmatch(r"codegraph-ue-[a-z-]+", reason) is None:
                reason = "codegraph-ue-prepare-failed"
            print(f"SelfWorkFlow: {reason}", file=sys.stderr)
            return 63
        except (OSError, subprocess.SubprocessError):
            print("SelfWorkFlow: codegraph-ue-prepare-failed", file=sys.stderr)
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
                arguments.agents_root, arguments.codex_root, arguments.state_root,
                arguments.dsh_root,
            )
        elif arguments.command == "documents":
            if arguments.document_command == "publish":
                result = publish_documents(arguments.repository, arguments.output)
            else:
                result = document_binding(arguments.root)
                if arguments.document_command == "snippet":
                    print(render_document_instruction(arguments.root))
                    return 0
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
                dsh_root=arguments.dsh_root,
                document_root=arguments.document_root,
                host_launcher=arguments.host_launcher,
                host_python=arguments.host_python,
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
    except (InstallerError, DocumentError) as error:
        print(f"SelfWorkFlow: install-operation-failed:{error}", file=sys.stderr)
        return 40
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
