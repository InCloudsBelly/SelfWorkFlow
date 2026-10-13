"""This stdlib-only verifier is embedded in the installer-managed launcher."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid


def checked_path(path):
    current = path
    while True:
        metadata = current.lstat()
        if current.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("workflow-host-reparse-path")
        if current.parent == current:
            break
        current = current.parent
    return path


def start():
    pointer = checked_path(Path(base64.b64decode(os.environ["SELFWORKFLOW_CURRENT_B64"]).decode("utf-8")))
    identity = json.loads(pointer.read_text(encoding="utf-8"))
    if (
        re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,63}", identity["version"]) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", identity["artifactHash"]) is None
    ):
        raise ValueError("workflow-host-pointer-invalid")
    snapshot = checked_path(Path(identity["snapshot"]))
    expected = pointer.parent / "versions" / identity["version"] / identity["artifactHash"].removeprefix("sha256:")
    if snapshot != expected or not snapshot.is_absolute():
        raise ValueError("workflow-host-pointer-invalid")
    inventory = []
    for path in sorted(snapshot.rglob("*")):
        checked_path(path)
        if path.is_file():
            inventory.append({"path": path.relative_to(snapshot).as_posix(), "size": path.stat().st_size,
                              "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()})
    actual = "sha256:" + hashlib.sha256(json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if actual != identity["artifactHash"]:
        raise ValueError("workflow-host-artifact-drift")
    compatibility = json.loads((snapshot / "host/python.json").read_text(encoding="utf-8"))
    if (
        compatibility["version"] != list(sys.version_info[:3])
        or compatibility["platform"] != sys.platform
        or compatibility["executableHash"] != hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    ):
        raise ValueError("workflow-host-python-drift")
    if sys.argv[1:] == ["--host-info"]:
        print(json.dumps({"artifactHash": actual, "snapshot": str(snapshot),
                          "cliPath": str(snapshot / "src/selfworkflow/cli.py"),
                          "pythonVersion": compatibility["version"]}, sort_keys=True))
        return 0
    # -I -S excludes cwd, user site and PYTHONPATH. Frozen packages are the only additions.
    sys.path[:0] = [str(snapshot / "src"), str(snapshot / "host/site-packages")]
    sys.dont_write_bytecode = True
    sys.pycache_prefix = str(snapshot / "host" / ("no-bytecode-" + uuid.uuid4().hex))
    from selfworkflow.cli import main

    return main(sys.argv[1:])


try:
    raise SystemExit(start())
except (OSError, ValueError, KeyError, ImportError) as error:
    reason = str(error) if isinstance(error, ValueError) and str(error).startswith("workflow-host-") else "workflow-host-start-failed"
    print("SelfWorkFlow: " + reason, file=sys.stderr)
    raise SystemExit(21)
