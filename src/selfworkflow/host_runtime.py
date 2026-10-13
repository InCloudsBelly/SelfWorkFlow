"""Package the installed Host and render its isolated, plan-bound Windows entry."""

import base64
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys


_DISTRIBUTIONS = ("PyYAML", "jsonschema", "attrs", "jsonschema-specifications", "referencing", "rpds-py", "typing_extensions")


def _check_path(path: Path, boundary: Path) -> None:
    current = path
    while True:
        if current.is_symlink() or getattr(current.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("host-reparse-path-rejected")
        if current == boundary:
            return
        if current.parent == current:
            raise ValueError("host-path-outside-boundary")
        current = current.parent


def build_host_runtime(repository: Path, output: Path) -> None:
    source = repository / "src/selfworkflow"
    for path in sorted(source.rglob("*.py")):
        _check_path(path, repository)
        target = output / "src/selfworkflow" / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    dependencies = output / "host/site-packages"
    versions = {}
    for name in _DISTRIBUTIONS:
        distribution = importlib.metadata.distribution(name)
        pinned = {"PyYAML": "6.0.3", "jsonschema": "4.26.0"}
        if name in pinned and distribution.version != pinned[name]:
            raise ValueError("host-dependency-version-mismatch")
        known = {item.lower().replace("_", "-") for item in _DISTRIBUTIONS}
        for requirement in distribution.requires or ():
            if re.search(r"\bextra\b", requirement):
                continue
            match = re.match(r"[A-Za-z0-9_.-]+", requirement)
            if match is None or match.group().lower().replace("_", "-") not in known:
                raise ValueError("host-dependency-closure-unsupported")
        if not distribution.files:
            raise ValueError("host-dependency-inventory-missing")
        versions[name] = distribution.version
        for item in distribution.files or ():
            relative = PurePosixPath(str(item).replace("\\", "/"))
            if (
                relative.is_absolute() or ".." in relative.parts
                or "__pycache__" in relative.parts or relative.suffix == ".pyc"
                or relative.name == "direct_url.json"
            ):
                continue
            path = Path(distribution.locate_file(item))
            _check_path(path, Path(distribution.locate_file("")))
            target = dependencies.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    bootstrap = repository / "scripts/selfworkflow-host-bootstrap.py"
    _check_path(bootstrap, repository)
    shutil.copyfile(bootstrap, output / "host/bootstrap.py")
    (output / "host/python.json").write_text(json.dumps({
        "version": list(sys.version_info[:3]), "platform": sys.platform,
        "executableHash": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "distributions": versions,
    }, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def render_host_launcher(artifact: Path, agents: Path, python: Path) -> bytes:
    compatibility = json.loads((artifact / "host/python.json").read_text(encoding="utf-8"))
    if hashlib.sha256(python.read_bytes()).hexdigest() != compatibility["executableHash"]:
        raise ValueError("host-python-identity-mismatch")
    payload = base64.b64encode((artifact / "host/bootstrap.py").read_bytes()).decode("ascii")
    pointer = base64.b64encode(str(agents / "selfworkflow/current.json").encode("utf-8")).decode("ascii")
    executable = str(python).replace("%", "%%")
    if '"' in executable or "\n" in executable or "\r" in executable:
        raise ValueError("host-python-path-invalid")
    return (
        "@echo off\r\nsetlocal\r\nrem SelfWorkFlow managed host CLI launcher\r\n"
        f'set "SELFWORKFLOW_CURRENT_B64={pointer}"\r\n'
        f'"{executable}" -I -S -B -c "import base64;exec(compile(base64.b64decode(\'{payload}\'),\'selfworkflow-host\',\'exec\'))" %*\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    ).encode("utf-8")


def legacy_host_launcher(python: Path) -> bytes:
    repository = python.parent.parent.parent
    return (
        "@echo off\r\nsetlocal\r\nrem SelfWorkFlow managed host CLI launcher\r\n"
        f'set "SELFWORKFLOW_PYTHON={python}"\r\n'
        f'set "SELFWORKFLOW_REPOSITORY_ROOT={repository}"\r\n'
        'if not exist "%SELFWORKFLOW_PYTHON%" (\r\n'
        '  >&2 echo SelfWorkFlow: repository environment missing; rerun the installer.\r\n'
        '  exit /b 20\r\n)\r\n'
        'set "PYTHONPATH=%SELFWORKFLOW_REPOSITORY_ROOT%\\src;%PYTHONPATH%"\r\n'
        '"%SELFWORKFLOW_PYTHON%" -m selfworkflow.cli %*\r\n'
        'exit /b %ERRORLEVEL%\r\n'
    ).encode("utf-8")
