"""Inspect the explicit source checkout used by the optional Wiki module."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import hashlib
import re
import tomllib
import uuid
import ctypes
from contextlib import contextmanager


class WikiModuleError(ValueError):
    pass


def _host_config_path(config_path: str | None) -> Path:
    path = Path(config_path) if config_path else Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    if not path.is_absolute():
        raise WikiModuleError("host-config-must-be-absolute")
    path = Path(os.path.abspath(path))
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise WikiModuleError("host-config-link-rejected")
    return path


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@contextmanager
def _host_mutex(config: Path):
    if os.name != "nt":
        raise WikiModuleError("windows-host-required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    kernel.ReleaseMutex.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    key = hashlib.sha256(str(config).lower().encode("utf-8")).hexdigest()
    mutex = kernel.CreateMutexW(None, False, "Local\\SelfWorkFlow-Mcp-" + key)
    if not mutex:
        raise WikiModuleError("wiki-host-config-lock-failed")
    held = False
    try:
        held = kernel.WaitForSingleObject(mutex, 0) in (0, 0x80)
        if not held:
            raise WikiModuleError("wiki-host-config-busy")
        yield
    finally:
        if held:
            kernel.ReleaseMutex(mutex)
        kernel.CloseHandle(mutex)


def _private_backup_directory(directory: Path):
    # Use framework file security directly; do not depend on PowerShell module autoload.
    code = r'''
$ErrorActionPreference = 'Stop'
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$acl = [IO.Directory]::GetAccessControl($p.path)
$acl.SetSecurityDescriptorSddlForm("D:P(A;OICI;FA;;;$sid)(A;OICI;FA;;;SY)", [Security.AccessControl.AccessControlSections]::Access)
[IO.Directory]::SetAccessControl($p.path, $acl)
[Console]::Write('private')
'''
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", code],
                                input=json.dumps({"path": str(directory)}), capture_output=True,
                                text=True, encoding="utf-8", timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise WikiModuleError("wiki-private-backup-security-failed") from None
    if result.returncode or result.stdout != "private":
        raise WikiModuleError("wiki-private-backup-security-failed")


def _replace_config(source: Path, target: Path, captured: Path | None):
    if captured is None:
        # Windows rename refuses a target created by a concurrent writer.
        os.rename(source, target)
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    replace = kernel.ReplaceFileW
    replace.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                       ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)
    replace.restype = ctypes.c_int
    # Flags 0 preserves DACL/attributes and does not ignore merge failures.
    if not replace(str(target), str(source), str(captured), 0, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


def _restore_captured_config(config: Path, captured: Path, owned_bytes: bytes):
    # Every displaced version stays in the private backup directory. Never
    # restore over a later observed write. Capture/check the restore itself too.
    for _ in range(3):
        if not config.exists() or config.read_bytes() != owned_bytes:
            return
        restore_bytes = captured.read_bytes()
        displaced = captured.with_name(uuid.uuid4().hex + ".conflict.toml")
        _replace_config(captured, config, displaced)
        if displaced.read_bytes() == owned_bytes:
            return
        captured, owned_bytes = displaced, restore_bytes


def register_wiki_mcp(repository_root: str, config_path: str | None = None, *,
                      confirm_plan_hash: str | None = None) -> dict[str, object]:
    source = inspect_wiki_module(repository_root)
    if source["status"] != "source-ready":
        raise WikiModuleError("wiki-build-and-verification-required")
    node = shutil.which("node")
    if node is None:
        raise WikiModuleError("node-missing")
    config = _host_config_path(config_path)
    before_exists = config.exists()
    before = config.read_bytes() if before_exists else b""
    try:
        text = before.decode("utf-8-sig")
        parsed = tomllib.loads(text)
    except (UnicodeError, tomllib.TOMLDecodeError):
        raise WikiModuleError("host-config-invalid") from None
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise WikiModuleError("host-config-invalid")
    existing = servers.get("self-openwiki", {})
    allowed = {"command", "args", "startup_timeout_sec", "tool_timeout_sec", "enabled"}
    if not isinstance(existing, dict) or not set(existing) <= allowed:
        raise WikiModuleError("wiki-custom-host-config-requires-review")
    for key in ("startup_timeout_sec", "tool_timeout_sec"):
        if key in existing and (type(existing[key]) not in {int, float} or not 0 < existing[key] < float("inf")):
            raise WikiModuleError("wiki-custom-host-config-requires-review")
    entry = str(Path(str(source["moduleRoot"])) / "self-openwiki/mcp-server/dist/index.js")
    server = {"command": str(Path(node).resolve()), "args": [entry], "enabled": True,
              "startup_timeout_sec": existing.get("startup_timeout_sec", 120),
              "tool_timeout_sec": existing.get("tool_timeout_sec", 120)}
    section = "[mcp_servers.self-openwiki]\n" + "".join(
        f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in server.items()
    )
    headers = list(re.finditer(r"(?m)^[ \t]*\[[^\r\n]+\][ \t]*(?:#[^\r\n]*)?\r?$", text))
    matches = []
    for index, match in enumerate(headers):
        try:
            table = tomllib.loads(match.group() + "\n")
        except tomllib.TOMLDecodeError:
            continue
        if table == {"mcp_servers": {"self-openwiki": {}}}:
            matches.append(index)
    if "self-openwiki" in parsed.get("mcp_servers", {}) and len(matches) != 1:
        raise WikiModuleError("wiki-host-table-layout-unsupported")
    if matches:
        index = matches[0]
        start = headers[index].start()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        updated = text[:start] + section + text[end:]
    else:
        updated = text + ("\n" if text and not text.endswith("\n") else "") + section
    if before.startswith(b"\xef\xbb\xbf"):
        updated = "\ufeff" + updated
    after = updated.encode("utf-8")
    try:
        after_parsed = tomllib.loads(updated.lstrip("\ufeff"))
    except tomllib.TOMLDecodeError:
        raise WikiModuleError("host-config-render-invalid") from None
    rendered_servers = after_parsed.get("mcp_servers")
    if not isinstance(rendered_servers, dict) or rendered_servers.get("self-openwiki") != server:
        raise WikiModuleError("wiki-host-table-layout-unsupported")
    for document in (parsed, after_parsed):
        document.setdefault("mcp_servers", {}).pop("self-openwiki", None)
    if parsed != after_parsed:
        raise WikiModuleError("unrelated-host-config-change")
    plan = {"configPath": str(config), "sourceRepositoryRoot": str(Path(repository_root)), "beforeConfigExists": before_exists,
            "beforeConfigHash": _digest(before), "afterConfigHash": _digest(after), "server": server}
    plan_hash = _digest(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode())
    if confirm_plan_hash is None:
        return {"status": "registration-plan", "planHash": plan_hash, **plan}
    if confirm_plan_hash != plan_hash:
        raise WikiModuleError("wiki-registration-plan-stale")
    config.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(config) + ".selfworkflow-wiki.lock")
    lock = None
    mutex = None
    temporary = None
    try:
        try:
            lock = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise WikiModuleError("wiki-host-config-busy") from None
        mutex = _host_mutex(config)
        mutex.__enter__()
        if (config.read_bytes() if config.exists() else b"") != before:
            raise WikiModuleError("wiki-host-config-changed")
        backups = config.parent / "selfworkflow-wiki-backups"
        _host_config_path(str(backups / "placeholder"))
        backups.mkdir(exist_ok=True)
        _private_backup_directory(backups)
        backup = backups / (uuid.uuid4().hex + ".toml")
        with backup.open("xb") as stream:
            stream.write(before)
        temporary = backups / (uuid.uuid4().hex + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        _host_config_path(str(config))
        if (config.read_bytes() if config.exists() else b"") != before:
            raise WikiModuleError("wiki-host-config-changed")
        captured = backups / (uuid.uuid4().hex + ".captured.toml") if before_exists else None
        try:
            _replace_config(temporary, config, captured)
        except OSError:
            if captured is not None and captured.exists() and not config.exists():
                os.rename(captured, config)
            raise WikiModuleError("wiki-host-config-write-failed") from None
        temporary = None
        if captured is not None and captured.read_bytes() != before:
            _restore_captured_config(config, captured, after)
            raise WikiModuleError("wiki-host-config-changed")
        if config.read_bytes() != after:
            raise WikiModuleError("wiki-host-config-postcondition-conflict")
        return {"status": "host-registered", "planHash": plan_hash, "backupPath": str(backup),
                "nativeTools": "restart-or-new-session-required", **plan}
    finally:
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        finally:
            try:
                if lock is not None:
                    os.close(lock)
                    lock_path.unlink(missing_ok=True)
            finally:
                if mutex is not None:
                    mutex.__exit__(None, None, None)


def doctor_wiki_module(repository_root: str, config_path: str | None = None) -> dict[str, object]:
    plan = register_wiki_mcp(repository_root, config_path)
    config = _host_config_path(config_path)
    parsed = tomllib.loads(config.read_text(encoding="utf-8-sig")) if config.exists() else {}
    server = parsed.get("mcp_servers", {}).get("self-openwiki", {})
    config_before_hash = _digest(config.read_bytes()) if config.exists() else _digest(b"")
    desired = plan["server"]
    if server.get("command") != desired["command"] or server.get("args") != desired["args"] or server.get("enabled", True) is not True:
        return {"status": "registration-required", "configPath": str(config)}
    probe = Path(repository_root) / "extensions/knowledge/selfopenwiki/scripts/probe-mcp.mjs"
    try:
        result = subprocess.run([desired["command"], str(probe)], cwd=probe.parent,
                                capture_output=True, text=True, encoding="utf-8", timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise WikiModuleError("wiki-live-probe-failed") from None
    if result.returncode != 0 or len(result.stdout) > 64 * 1024:
        raise WikiModuleError("wiki-live-probe-failed")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise WikiModuleError("wiki-live-probe-invalid") from None
    if not isinstance(report, dict) or report.get("status") != "wiki-ready":
        raise WikiModuleError("wiki-live-probe-invalid")
    if _digest(config.read_bytes()) != config_before_hash:
        raise WikiModuleError("wiki-host-config-changed")
    return {**report, "configPath": str(config), "nativeTools": "restart-or-new-session-required"}


def inspect_wiki_module(repository_root: str) -> dict[str, object]:
    requested = Path(repository_root)
    if not requested.is_absolute():
        raise WikiModuleError("source-repository-must-be-absolute")
    for ancestor in (requested, *requested.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise WikiModuleError("source-repository-link-rejected")
    try:
        root = requested.resolve(strict=True)
    except OSError:
        raise WikiModuleError("source-repository-missing") from None
    module = root / "extensions/knowledge/selfopenwiki"
    for ancestor in (module, module.parent, module.parent.parent, module / "scripts"):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise WikiModuleError("source-module-link-rejected")
    report = {
        "status": "setup-required", "hostRegistration": "unverified",
        "sourceRepositoryRoot": str(root), "moduleRoot": str(module),
    }
    entry = module / "scripts/manage-wiki.mjs"
    if entry.is_symlink():
        raise WikiModuleError("source-module-link-rejected")
    if not entry.is_file():
        return {**report, "reason": "source-module-missing"}
    node = shutil.which("node")
    if node is None:
        return {**report, "reason": "node-missing"}
    try:
        completed = subprocess.run(
            [node, str(entry), "inspect"], cwd=root,
            capture_output=True, text=True, encoding="utf-8", timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if completed.returncode != 0 or len(completed.stdout) > 64 * 1024:
            raise WikiModuleError("module-inspection-failed")
        value = json.loads(completed.stdout)
        if (
            not isinstance(value, dict)
            or value.get("status") not in {"setup-required", "source-ready"}
            or value.get("hostRegistration") != "unverified"
            or Path(str(value.get("moduleRoot", ""))) != module
        ):
            raise WikiModuleError("module-inspection-invalid")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        raise WikiModuleError("module-inspection-failed") from None
    return value
