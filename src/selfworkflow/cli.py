"""Command-line entry point for SelfWorkFlow."""

import argparse
import json
import os
from pathlib import Path
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
from selfworkflow.resolver import resolve_task
from selfworkflow.ledger import validate_ledger
from selfworkflow.git_policy import check_repository
from selfworkflow.sources import (
    SourceSelectionError,
    inspect_superpowers_source,
    stage_superpowers_source,
)
from selfworkflow.transactions import write_json_atomic


_REPARSE_POINT = 0x400


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
    arguments = parser.parse_args(argv)
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
    if arguments.command == "source" and arguments.source_command == "stage":
        try:
            result = stage_superpowers_source(
                arguments.path,
                arguments.target,
                arguments.expected_inventory_hash,
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
