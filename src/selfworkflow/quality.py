"""Deterministic review-package construction and completion quality gate."""

from __future__ import annotations

from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import threading
import time
from typing import Any, Mapping, Sequence


_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_SPEC_FIELDS = (
    "workflowMode",
    "userRequest",
    "acceptanceCriteria",
    "design",
    "testDesign",
    "implementationPlan",
    "projectRules",
)
_BEFORE_LIMIT = 4 * 1024 * 1024
_MAX_PATHS = 512
_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_SHELL_EXECUTABLES = {
    "bash", "cmd", "cmd.exe", "command", "fish", "pwsh", "pwsh.exe",
    "powershell", "powershell.exe", "sh", "zsh",
}


class _WindowsJob:
    """Kill-on-close containment for one suspended Windows process tree."""

    _KILL_ON_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9
    _BASIC_ACCOUNTING_INFORMATION = 1

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        if os.name != "nt":
            raise QualityGateError("quality-verification-containment-failed")
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class BasicAccountingInformation(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p,
        ]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtResumeProcess.restype = ctypes.c_long

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise QualityGateError("quality-verification-containment-failed")
        self._ctypes = ctypes
        self._kernel32 = kernel32
        self._accounting_type = BasicAccountingInformation
        self._handle = handle
        try:
            limits = ExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = self._KILL_ON_CLOSE
            if not kernel32.SetInformationJobObject(
                handle,
                self._EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise QualityGateError("quality-verification-containment-failed")
            process_handle = wintypes.HANDLE(int(getattr(process, "_handle")))
            if not kernel32.AssignProcessToJobObject(handle, process_handle):
                raise QualityGateError("quality-verification-containment-failed")
            if ntdll.NtResumeProcess(process_handle) != 0:
                raise QualityGateError("quality-verification-containment-failed")
        except Exception:
            kernel32.CloseHandle(handle)
            self._handle = None
            raise

    def active_processes(self) -> int:
        if self._handle is None:
            return 0
        value = self._accounting_type()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            self._BASIC_ACCOUNTING_INFORMATION,
            self._ctypes.byref(value),
            self._ctypes.sizeof(value),
            None,
        ):
            raise QualityGateError("quality-verification-containment-failed")
        return int(value.ActiveProcesses)

    def terminate_and_close(self) -> None:
        if self._handle is None:
            return
        handle = self._handle
        try:
            if not self._kernel32.TerminateJobObject(handle, 1):
                raise QualityGateError("quality-verification-termination-failed")
            deadline = time.monotonic() + 10
            while self.active_processes() != 0:
                if time.monotonic() >= deadline:
                    raise QualityGateError("quality-verification-termination-failed")
                time.sleep(0.01)
        finally:
            self._kernel32.CloseHandle(handle)
            self._handle = None


class QualityGateError(ValueError):
    """Stable fail-closed quality error without sensitive payload echo."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise QualityGateError("quality-input-invalid") from None


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_git(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        raise QualityGateError("quality-git-failed") from None
    if result.returncode != 0 or len(result.stdout) > 32 * 1024 * 1024:
        raise QualityGateError("quality-git-failed")
    return result.stdout


def _repository(value: str | Path) -> Path:
    try:
        root = Path(value).resolve(strict=True)
        top = Path(
            _run_git(root, "rev-parse", "--show-toplevel")
            .decode("utf-8", errors="strict")
            .strip()
        ).resolve(strict=True)
    except (OSError, UnicodeError, ValueError):
        raise QualityGateError("quality-repository-invalid") from None
    if top != root:
        raise QualityGateError("quality-repository-invalid")
    return root


def _safe_relative(root: Path, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise QualityGateError("quality-path-invalid")
    try:
        relative = PurePosixPath(value.replace("\\", "/"))
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError
        candidate = root.joinpath(*relative.parts)
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
        current = candidate
        while current != root:
            if current.exists() and current.is_symlink():
                raise ValueError
            current = current.parent
    except (OSError, ValueError):
        raise QualityGateError("quality-path-invalid") from None
    return relative.as_posix()


def _snapshot_bytes(data: bytes) -> dict[str, Any]:
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    if len(data) <= _BEFORE_LIMIT:
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeError:
            pass
        else:
            if "\x00" not in text:
                return {
                    "kind": "text", "sha256": digest,
                    "size": len(data), "content": text,
                }
    return {"kind": "binary", "sha256": digest, "size": len(data)}


def _snapshot(root: Path, relative: str) -> dict[str, Any]:
    path = root.joinpath(*PurePosixPath(relative).parts)
    if not path.exists():
        return {"kind": "missing", "sha256": None, "size": 0, "gitMode": None}
    if path.is_symlink() or not path.is_file():
        raise QualityGateError("quality-path-invalid")
    try:
        snapshot = _snapshot_bytes(path.read_bytes())
        snapshot["gitMode"] = "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"
        return snapshot
    except OSError:
        raise QualityGateError("quality-read-failed") from None


def _index_snapshot(root: Path, relative: str) -> dict[str, Any]:
    entry = _run_git(root, "ls-files", "--stage", "-z", "--", relative)
    if not entry:
        return {"kind": "missing", "sha256": None, "size": 0, "gitMode": None}
    try:
        records = [record for record in entry.split(b"\0") if record]
        if len(records) != 1:
            raise ValueError
        header, separator, encoded_path = records[0].partition(b"\t")
        mode, object_id, stage = header.split(b" ")
        listed_path = encoded_path.decode("utf-8", errors="strict").replace("\\", "/")
        if (
            separator != b"\t"
            or listed_path != relative
            or stage != b"0"
            or re.fullmatch(rb"[0-7]{6}", mode) is None
            or re.fullmatch(rb"[0-9a-f]{40,64}", object_id) is None
        ):
            raise ValueError
        snapshot = _snapshot_bytes(_run_git(root, "show", f":{relative}"))
        snapshot["gitMode"] = mode.decode("ascii", errors="strict")
        return snapshot
    except (QualityGateError, UnicodeError, ValueError):
        raise QualityGateError("quality-index-read-failed") from None


def capture_review_baseline(
    repository: str | Path, paths: Sequence[str],
) -> dict[str, Any]:
    """Capture exact task-start bytes for the approved path set."""

    root = _repository(repository)
    if (
        not isinstance(paths, Sequence)
        or isinstance(paths, (str, bytes))
        or not 0 < len(paths) <= _MAX_PATHS
    ):
        raise QualityGateError("quality-path-invalid")
    normalized = sorted({_safe_relative(root, value) for value in paths})
    if len(normalized) != len(paths):
        raise QualityGateError("quality-path-invalid")
    head = _run_git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    baseline = {
        "schemaVersion": 1,
        "repository": str(root),
        "capturedAt": _now(),
        "baseHead": head,
        "paths": normalized,
        "files": {relative: _snapshot(root, relative) for relative in normalized},
        "indexFiles": {
            relative: _index_snapshot(root, relative) for relative in normalized
        },
        "workspace": _workspace_state(root, head),
    }
    baseline["baselineHash"] = _hash(_baseline_semantic(baseline))
    return baseline


def _name_set(root: Path, *arguments: str) -> set[str]:
    output = _run_git(root, *arguments)
    try:
        return {
            item.decode("utf-8", errors="strict").replace("\\", "/")
            for item in output.split(b"\0") if item
        }
    except UnicodeError:
        raise QualityGateError("quality-git-failed") from None


def _git_states(root: Path, base_head: str) -> dict[str, set[str]]:
    sources = {
        "committed": _name_set(root, "diff", "--name-only", "-z", f"{base_head}..HEAD", "--"),
        "staged": _name_set(root, "diff", "--cached", "--name-only", "-z", "--"),
        "unstaged": _name_set(root, "diff", "--name-only", "-z", "--"),
        "untracked": _name_set(root, "ls-files", "--others", "--exclude-standard", "-z", "--"),
    }
    result: dict[str, set[str]] = {}
    for state, names in sources.items():
        for name in names:
            result.setdefault(name, set()).add(state)
    return result


def _baseline_semantic(baseline: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": baseline.get("schemaVersion"),
        "baseHead": baseline.get("baseHead"),
        "paths": baseline.get("paths"),
        "files": baseline.get("files"),
        "indexFiles": baseline.get("indexFiles"),
        "workspace": baseline.get("workspace"),
    }


def _workspace_state(root: Path, base_head: str) -> dict[str, Any]:
    states = _git_states(root, base_head)
    if len(states) > _MAX_PATHS:
        raise QualityGateError("quality-workspace-too-large")
    result: dict[str, Any] = {}
    for relative in sorted(states):
        normalized = _safe_relative(root, relative)
        snapshot = _snapshot(root, normalized)
        index_snapshot = _index_snapshot(root, normalized)
        result[normalized] = {
            "states": sorted(states[relative]),
            "kind": snapshot["kind"],
            "sha256": snapshot["sha256"],
            "size": snapshot["size"],
            "gitMode": snapshot["gitMode"],
            "indexSha256": index_snapshot["sha256"],
            "indexGitMode": index_snapshot["gitMode"],
        }
    return result


def _patch(relative: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> str | None:
    mode_patch = ""
    if before.get("gitMode") != after.get("gitMode"):
        if before.get("gitMode") is None:
            mode_patch = f"new file mode {after.get('gitMode')}\n"
        elif after.get("gitMode") is None:
            mode_patch = f"deleted file mode {before.get('gitMode')}\n"
        else:
            mode_patch = (
                f"old mode {before.get('gitMode')}\n"
                f"new mode {after.get('gitMode')}\n"
            )
    if before["kind"] not in {"text", "missing"} or after["kind"] not in {"text", "missing"}:
        return mode_patch or None
    old = "" if before["kind"] == "missing" else str(before["content"])
    new = "" if after["kind"] == "missing" else str(after["content"])
    return mode_patch + "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{relative}",
        tofile=f"b/{relative}",
        lineterm="\n",
    ))


def _specification(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(_SPEC_FIELDS):
        raise QualityGateError("quality-spec-invalid")
    result: dict[str, str] = {}
    for field in _SPEC_FIELDS:
        content = value[field]
        if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 4 * 1024 * 1024:
            raise QualityGateError("quality-spec-invalid")
        if field == "workflowMode" and content not in {"Light", "Full", "Deep"}:
            raise QualityGateError("quality-spec-invalid")
        result[field] = content
    return result


def _cwd_relative(value: object) -> str:
    if value == ".":
        return "."
    if not isinstance(value, str):
        raise QualityGateError("quality-verification-plan-invalid")
    try:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError
    except ValueError:
        raise QualityGateError("quality-verification-plan-invalid") from None
    return path.as_posix()


def _verification_plans(value: object) -> list[dict[str, Any]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not 1 <= len(value) <= 32
    ):
        raise QualityGateError("quality-verification-plan-invalid")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for plan in value:
        if not isinstance(plan, Mapping) or set(plan) != {
            "id", "argv", "cwdRelative", "timeoutSeconds", "confirmedByUser",
            "resultContract",
        }:
            raise QualityGateError("quality-verification-plan-invalid")
        identifier = plan.get("id")
        argv = plan.get("argv")
        timeout = plan.get("timeoutSeconds")
        result_contract = plan.get("resultContract")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", identifier)
            or identifier in seen
            or not isinstance(argv, Sequence)
            or isinstance(argv, (str, bytes))
            or not 1 <= len(argv) <= 64
            or any(not isinstance(item, str) or not item or len(item) > 4096 or "\x00" in item or "\n" in item for item in argv)
            or not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or not 1 <= timeout <= 600
            or plan.get("confirmedByUser") is not True
            or result_contract != {
                "kind": "process-exit", "allowedExitCodes": [0],
            }
        ):
            raise QualityGateError("quality-verification-plan-invalid")
        executable = Path(str(argv[0])).name.casefold()
        if executable in _SHELL_EXECUTABLES:
            raise QualityGateError("quality-verification-plan-invalid")
        seen.add(identifier)
        result.append({
            "id": identifier,
            "argv": list(argv),
            "cwdRelative": _cwd_relative(plan.get("cwdRelative")),
            "timeoutSeconds": timeout,
            "confirmedByUser": True,
            "resultContract": {
                "kind": "process-exit", "allowedExitCodes": [0],
            },
        })
    return result


def _validate_baseline(root: Path, baseline: Mapping[str, Any]) -> tuple[list[str], Mapping[str, Any]]:
    if (
        not isinstance(baseline, Mapping)
        or baseline.get("schemaVersion") != 1
        or baseline.get("repository") != str(root)
        or not _HASH.fullmatch(str(baseline.get("baselineHash", "")))
        or _hash(_baseline_semantic(baseline)) != baseline.get("baselineHash")
    ):
        raise QualityGateError("quality-baseline-invalid")
    paths = baseline.get("paths")
    files = baseline.get("files")
    index_files = baseline.get("indexFiles")
    workspace = baseline.get("workspace")
    if (
        not isinstance(paths, list)
        or not isinstance(files, Mapping)
        or not isinstance(index_files, Mapping)
        or not isinstance(workspace, Mapping)
        or set(paths) != set(files)
        or set(paths) != set(index_files)
    ):
        raise QualityGateError("quality-baseline-invalid")
    return paths, files


def _assert_scope_unchanged(root: Path, baseline: Mapping[str, Any], approved: set[str]) -> None:
    current = _workspace_state(root, str(baseline.get("baseHead")))
    before = baseline.get("workspace")
    if not isinstance(before, Mapping):
        raise QualityGateError("quality-baseline-invalid")
    for relative in set(before) | set(current):
        if relative not in approved and before.get(relative) != current.get(relative):
            raise QualityGateError("quality-out-of-scope-change")


def build_review_package(
    repository: str | Path,
    baseline: Mapping[str, Any],
    specification: Mapping[str, str],
    verification_plans: object = None,
) -> dict[str, Any]:
    """Build one readable package shared by Standards and Spec reviewers."""

    root = _repository(repository)
    paths, files = _validate_baseline(root, baseline)
    supplied_hash = str(baseline["baselineHash"])
    approved = set(paths)
    _assert_scope_unchanged(root, baseline, approved)
    states = _git_states(root, str(baseline.get("baseHead")))
    changes = []
    for relative in paths:
        normalized = _safe_relative(root, relative)
        before = files[relative]
        before_index = baseline["indexFiles"][relative]
        after = _snapshot(root, normalized)
        after_index = _index_snapshot(root, normalized)
        if not isinstance(before, Mapping) or not isinstance(before_index, Mapping):
            raise QualityGateError("quality-baseline-invalid")
        worktree_unchanged = (
            before.get("sha256") == after.get("sha256")
            and before.get("kind") == after.get("kind")
            and before.get("gitMode") == after.get("gitMode")
        )
        index_unchanged = (
            before_index.get("sha256") == after_index.get("sha256")
            and before_index.get("kind") == after_index.get("kind")
            and before_index.get("gitMode") == after_index.get("gitMode")
        )
        if worktree_unchanged and index_unchanged:
            continue
        status = "modified"
        if before.get("kind") == "missing":
            status = "added"
        elif after.get("kind") == "missing":
            status = "deleted"
        changes.append({
            "path": normalized,
            "status": status,
            "gitStates": sorted(states.get(normalized, set())),
            "before": dict(before),
            "after": after,
            "beforeIndex": dict(before_index),
            "afterIndex": after_index,
            "patch": _patch(normalized, before, after),
            "stagedPatch": _patch(normalized, before_index, after_index),
        })
    semantic = {
        "schemaVersion": 1,
        "baselineHash": supplied_hash,
        "baseline": _baseline_semantic(baseline),
        "baseHead": baseline.get("baseHead"),
        "specification": _specification(specification),
        "verificationPlans": _verification_plans(verification_plans),
        "changes": changes,
    }
    package = {**semantic, "createdAt": _now()}
    package["packageHash"] = _hash(semantic)
    return package


def _package_hash(package: Mapping[str, Any]) -> str:
    if not isinstance(package, Mapping):
        raise QualityGateError("quality-package-invalid")
    supplied = package.get("packageHash")
    semantic = {
        key: package.get(key) for key in (
            "schemaVersion", "baselineHash", "baseHead", "specification",
            "baseline", "verificationPlans", "changes",
        )
    }
    if not isinstance(supplied, str) or not _HASH.fullmatch(supplied) or _hash(semantic) != supplied:
        raise QualityGateError("quality-package-invalid")
    return supplied


def _assert_package_current(
    root: Path, package: Mapping[str, Any], package_hash: str,
) -> None:
    embedded = package.get("baseline")
    baseline_hash = package.get("baselineHash")
    if (
        not isinstance(embedded, Mapping)
        or not isinstance(baseline_hash, str)
        or _hash(embedded) != baseline_hash
    ):
        raise QualityGateError("quality-package-invalid")
    baseline = {
        **dict(embedded),
        "repository": str(root),
        "baselineHash": baseline_hash,
    }
    rebuilt = build_review_package(
        root,
        baseline,
        package.get("specification"),
        package.get("verificationPlans"),
    )
    if rebuilt["packageHash"] != package_hash:
        raise QualityGateError("quality-package-stale")


def _posix_group_exists(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except (OSError, PermissionError):
        raise QualityGateError("quality-verification-termination-failed") from None
    return True


def _terminate_process_tree(
    process: subprocess.Popen[bytes], windows_job: _WindowsJob | None,
) -> None:
    if os.name == "nt":
        if windows_job is None:
            raise QualityGateError("quality-verification-containment-failed")
        windows_job.terminate_and_close()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (OSError, PermissionError):
            raise QualityGateError("quality-verification-termination-failed") from None
    try:
        process.wait(timeout=10)
    except (OSError, subprocess.SubprocessError):
        raise QualityGateError("quality-verification-termination-failed") from None
    if process.poll() is None:
        raise QualityGateError("quality-verification-termination-failed")
    if os.name != "nt":
        deadline = time.monotonic() + 10
        while _posix_group_exists(process.pid):
            if time.monotonic() >= deadline:
                raise QualityGateError("quality-verification-termination-failed")
            time.sleep(0.01)


def _read_bounded_stream(
    stream: Any,
    outputs: dict[str, bytes],
    key: str,
    exceeded: threading.Event,
    failed: threading.Event,
) -> None:
    data = bytearray()
    try:
        while True:
            remaining = _MAX_OUTPUT_BYTES + 1 - len(data)
            if remaining <= 0:
                exceeded.set()
                break
            chunk = stream.read(min(64 * 1024, remaining))
            if not chunk:
                break
            if len(data) + len(chunk) > _MAX_OUTPUT_BYTES:
                exceeded.set()
                break
            data.extend(chunk)
    except (OSError, ValueError):
        failed.set()
    finally:
        outputs[key] = bytes(data)


def _execute_bounded_process(
    plan: Mapping[str, Any], resolved_cwd: Path, allowed_environment: Mapping[str, str],
) -> tuple[int, bool, bytes, bytes]:
    creationflags = (
        subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004
        if os.name == "nt" else 0
    )
    process = subprocess.Popen(
        plan["argv"], cwd=resolved_cwd, env=dict(allowed_environment),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    if process.stdout is None or process.stderr is None:
        try:
            process.kill()
            process.wait(timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        raise QualityGateError("quality-verification-execution-failed")
    windows_job: _WindowsJob | None = None
    tree_terminated = False
    readers: list[threading.Thread] = []
    outputs: dict[str, bytes] = {}
    output_limited = threading.Event()
    reader_failed = threading.Event()
    timed_out = False
    background_process = False
    cleanup_error: QualityGateError | None = None
    try:
        if os.name == "nt":
            windows_job = _WindowsJob(process)
        for key, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            reader = threading.Thread(
                target=_read_bounded_stream,
                args=(stream, outputs, key, output_limited, reader_failed),
                daemon=True,
            )
            reader.start()
            readers.append(reader)
        deadline = time.monotonic() + int(plan["timeoutSeconds"])
        while process.poll() is None:
            if output_limited.is_set():
                _terminate_process_tree(process, windows_job)
                tree_terminated = True
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _terminate_process_tree(process, windows_job)
                tree_terminated = True
                break
            output_limited.wait(0.01)
        if not tree_terminated:
            if os.name == "nt":
                if windows_job is None:
                    raise QualityGateError("quality-verification-containment-failed")
                background_process = windows_job.active_processes() > 0
            else:
                background_process = _posix_group_exists(process.pid)
            _terminate_process_tree(process, windows_job)
            tree_terminated = True
        for reader in readers:
            reader.join(timeout=10)
        if any(reader.is_alive() for reader in readers) or reader_failed.is_set():
            raise QualityGateError("quality-verification-reader-failed")
        if background_process:
            raise QualityGateError("quality-verification-background-process")
        if output_limited.is_set():
            raise QualityGateError("quality-verification-output-limit")
        exit_code = process.returncode if process.returncode is not None else 124
        return exit_code, timed_out, outputs.get("stdout", b""), outputs.get("stderr", b"")
    finally:
        if not tree_terminated:
            try:
                if os.name == "nt" and windows_job is None:
                    process.kill()
                    process.wait(timeout=10)
                else:
                    _terminate_process_tree(process, windows_job)
            except (OSError, subprocess.SubprocessError, QualityGateError):
                cleanup_error = QualityGateError("quality-verification-termination-failed")
        for reader in readers:
            reader.join(timeout=10)
        if any(reader.is_alive() for reader in readers):
            cleanup_error = QualityGateError("quality-verification-termination-failed")
        try:
            process.stdout.close()
            process.stderr.close()
        except (OSError, ValueError):
            cleanup_error = QualityGateError("quality-verification-termination-failed")
        if cleanup_error is not None:
            raise cleanup_error


def run_verification(
    repository: str | Path, package: Mapping[str, Any], plan_id: str,
) -> dict[str, Any]:
    """Execute one package-bound verification plan without a shell or stdin."""

    root = _repository(repository)
    package_hash = _package_hash(package)
    _assert_package_current(root, package, package_hash)
    plans = _verification_plans(package.get("verificationPlans"))
    plan = next((item for item in plans if item["id"] == plan_id), None)
    if plan is None:
        raise QualityGateError("quality-verification-plan-unbound")
    cwd = root if plan["cwdRelative"] == "." else root.joinpath(*PurePosixPath(plan["cwdRelative"]).parts)
    try:
        resolved_cwd = cwd.resolve(strict=True)
        resolved_cwd.relative_to(root)
        if not resolved_cwd.is_dir():
            raise ValueError
        current = resolved_cwd
        while current != root:
            if current.is_symlink():
                raise ValueError
            current = current.parent
    except (OSError, ValueError):
        raise QualityGateError("quality-verification-cwd-invalid") from None
    allowed_environment = {
        key: os.environ[key] for key in (
            "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
        ) if key in os.environ
    }
    started = _now()
    try:
        exit_code, timed_out, stdout, stderr = _execute_bounded_process(
            plan, resolved_cwd, allowed_environment,
        )
    except OSError:
        raise QualityGateError("quality-verification-execution-failed") from None
    completed = _now()
    _assert_package_current(root, package, package_hash)
    matched = not timed_out and exit_code in plan["resultContract"]["allowedExitCodes"]
    return {
        "schemaVersion": 1,
        "attestation": "runner_attested",
        "planId": plan["id"],
        "planHash": _hash(plan),
        "inputHash": package_hash,
        "argv": plan["argv"],
        "cwdRelative": plan["cwdRelative"],
        "startedAt": started,
        "completedAt": completed,
        "exitCode": exit_code,
        "failureCount": 0 if matched else 1,
        "stdoutHash": "sha256:" + hashlib.sha256(stdout).hexdigest(),
        "stderrHash": "sha256:" + hashlib.sha256(stderr).hexdigest(),
        "consumerResult": {
            "kind": "process-exit",
            "observedExitCode": exit_code,
            "matched": matched,
            "timedOut": timed_out,
        },
        "status": "verified" if matched else "failed",
    }


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise QualityGateError("quality-verification-invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise QualityGateError("quality-verification-invalid") from None
    return parsed


def validate_completion(
    repository: str | Path,
    baseline: Mapping[str, Any],
    specification: Mapping[str, str],
    package: Mapping[str, Any],
    reviews: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Fail closed unless mode-appropriate Review and fresh verification are current."""

    package_hash = _package_hash(package)
    rebuilt = build_review_package(repository, baseline, specification, package.get("verificationPlans"))
    if rebuilt["packageHash"] != package_hash:
        raise QualityGateError("quality-package-stale")
    workflow_mode = package.get("specification", {}).get("workflowMode")
    if workflow_mode == "Light":
        expected_axes = {"self"}
        expected_attestation = "self_attested"
    elif workflow_mode in {"Full", "Deep"}:
        expected_axes = {"standards", "spec"}
        expected_attestation = "host_attested"
    else:
        raise QualityGateError("quality-review-mode-mismatch")
    if (
        not isinstance(reviews, Sequence)
        or isinstance(reviews, (str, bytes))
        or len(reviews) != len(expected_axes)
    ):
        raise QualityGateError("quality-review-missing")
    by_axis: dict[str, Mapping[str, Any]] = {}
    execution_ids: set[str] = set()
    for review in reviews:
        if not isinstance(review, Mapping) or review.get("axis") not in expected_axes:
            raise QualityGateError("quality-review-missing")
        axis = str(review["axis"])
        execution = review.get("executionId")
        if review.get("workflowMode") != workflow_mode:
            raise QualityGateError("quality-review-mode-mismatch")
        if review.get("attestation") != expected_attestation:
            raise QualityGateError("quality-review-invalid")
        if axis in by_axis or not isinstance(execution, str) or not execution:
            raise QualityGateError("quality-review-not-independent")
        if execution in execution_ids:
            raise QualityGateError("quality-review-not-independent")
        execution_ids.add(execution)
        by_axis[axis] = review
        if review.get("packageHash") != package_hash:
            raise QualityGateError("quality-package-stale")
        findings = review.get("findings")
        if not isinstance(findings, list):
            raise QualityGateError("quality-review-invalid")
        for finding in findings:
            if not isinstance(finding, Mapping) or finding.get("severity") not in {"critical", "high", "medium", "low", "info"}:
                raise QualityGateError("quality-review-invalid")
            severity = finding["severity"]
            status = finding.get("status")
            if severity in {"critical", "high", "medium"} and status != "resolved":
                raise QualityGateError("quality-review-open-blocker")
            if severity in {"low", "info"} and (
                status not in {"resolved", "accepted"}
                or not isinstance(finding.get("disposition"), str)
                or not finding["disposition"].strip()
            ):
                raise QualityGateError("quality-review-invalid")
    if set(by_axis) != expected_axes:
        raise QualityGateError("quality-review-missing")
    plans = _verification_plans(package.get("verificationPlans"))
    owned_verifications = [
        run_verification(repository, package, plan["id"]) for plan in plans
    ]
    package_time = _timestamp(package.get("createdAt"))
    plans_by_id = {item["id"]: item for item in plans}
    seen_plans: set[str] = set()
    for receipt in owned_verifications:
        if not isinstance(receipt, Mapping):
            raise QualityGateError("quality-verification-invalid")
        if receipt.get("status") == "unverified":
            raise QualityGateError("quality-verification-unverified")
        plan_id = receipt.get("planId")
        plan = plans_by_id.get(plan_id) if isinstance(plan_id, str) else None
        if (
            plan is None
            or plan_id in seen_plans
            or receipt.get("attestation") != "runner_attested"
            or receipt.get("planHash") != _hash(plan)
            or receipt.get("status") != "verified"
            or receipt.get("inputHash") != package_hash
            or receipt.get("argv") != plan["argv"]
            or receipt.get("cwdRelative") != plan["cwdRelative"]
            or receipt.get("exitCode") != 0
            or receipt.get("failureCount") != 0
            or receipt.get("consumerResult") != {
                "kind": "process-exit",
                "observedExitCode": 0,
                "matched": True,
                "timedOut": False,
            }
            or not _HASH.fullmatch(str(receipt.get("stdoutHash", "")))
            or not _HASH.fullmatch(str(receipt.get("stderrHash", "")))
        ):
            raise QualityGateError("quality-verification-failed")
        seen_plans.add(plan_id)
        started = _timestamp(receipt.get("startedAt"))
        completed = _timestamp(receipt.get("completedAt"))
        if started < package_time or completed < started:
            raise QualityGateError("quality-verification-failed")
    if seen_plans != set(plans_by_id):
        raise QualityGateError("quality-verification-missing")
    return {
        "schemaVersion": 1,
        "status": "complete",
        "workflowMode": workflow_mode,
        "packageHash": package_hash,
        "verifications": owned_verifications,
    }
