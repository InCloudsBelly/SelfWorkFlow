"""Command-line entry point for SelfWorkFlow."""

import argparse
import os
from pathlib import Path
import sys
import tempfile
import unicodedata

from selfworkflow import __version__
from selfworkflow.catalog import compile_catalog


_REPARSE_POINT = 0x400


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="selfworkflow")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    catalog = commands.add_parser("catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command")
    compile_parser = catalog_commands.add_parser("compile")
    compile_parser.add_argument("--source", required=True)
    compile_parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "catalog" and arguments.catalog_command == "compile":
        try:
            catalog_hash = _publish_catalog(arguments.source, arguments.output)
        except Exception:
            print("SelfWorkFlow: catalog-compile-failed", file=sys.stderr)
            return 20
        print(catalog_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
