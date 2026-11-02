"""Black-box cleanup regressions; all links and their targets are fixture-owned."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from selfworkflow.work_artifacts import WorkArtifactError, WorkArtifactManager


def _capture(root, *, two_files=False):
    manager = WorkArtifactManager(root, "cleanup")
    state = {"contentGeneration": 0, "stateRevision": 0, "manifestHash": None}
    documents = [{"id": "a", "kind": "design", "content": "# Owned\n"}]
    if two_files:
        documents.append({"id": "b", "kind": "plan", "content": "# Second\n"})
    for generation in range(3):
        state = manager.transition(state["contentGeneration"], state["stateRevision"], state["manifestHash"],
                                   "documents-captured" if generation == 0 else "documents-revised",
                                   documents, operation_nonce=f"capture-{generation}")
    arguments = (3, state["stateRevision"], state["manifestHash"])
    return manager, arguments


def _junction(link, target):
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr.decode(errors="replace"))


def _contents(root):
    return {str(file.relative_to(root)): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in root.rglob("*") if file.is_file()}


@contextmanager
def _deny_delete(path):
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def _redirect_empty_directory(directory, target):
    import ctypes
    import struct
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, w.LPVOID, w.DWORD, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID]
    kernel.DeviceIoControl.restype = w.BOOL
    substitute = ("\\??\\" + str(target)).encode("utf-16-le")
    printable = str(target).encode("utf-16-le")
    names = substitute + b"\x00\x00" + printable + b"\x00\x00"
    payload = struct.pack("<IHHHHHH", 0xA0000003, 8 + len(names), 0, 0, len(substitute), len(substitute) + 2, len(printable)) + names
    handle = kernel.CreateFileW(str(directory), 0x100, 7, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        returned = w.DWORD()
        if not kernel.DeviceIoControl(handle, 0x900A4, payload, len(payload), None, 0, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


@unittest.skipUnless(os.name == "nt", "Windows cleanup apply boundary")
class WorkArtifactReconcileTests(unittest.TestCase):
    def test_pinned_parent_cannot_redirect_a_subsequent_file_open(self):
        from contextlib import ExitStack
        from selfworkflow.work_artifacts import _ReconcileHandles
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generation, foreign = root / "generation", root / "foreign"
            generation.mkdir()
            foreign.mkdir()
            source = generation / "a.md"
            source.write_bytes(b"owned file identity")
            redirected = False
            try:
                with ExitStack() as stack:
                    handles = _ReconcileHandles(stack)
                    handles.directory(generation)
                    source.rename(foreign / source.name)
                    _redirect_empty_directory(generation, foreign)
                    redirected = True
                    with self.assertRaises(WorkArtifactError):
                        handles.file(source, delete=True)
                    # Exercise the native no-reparse lookup itself as well as
                    # the owner's metadata guard: no private collaborator mock.
                    import ctypes
                    from ctypes import wintypes as w
                    buffer = ctypes.create_unicode_buffer(source.name)
                    size = len(source.name.encode("utf-16-le"))
                    name = handles.name_type(size, size + 2, ctypes.cast(buffer, w.LPVOID))
                    attributes = handles.attributes_type(ctypes.sizeof(handles.attributes_type),
                                                          handles.directories[generation], ctypes.pointer(name), 0x1040, None, None)
                    opened, status = w.HANDLE(), handles.status_type()
                    result = handles.nt_open(ctypes.byref(opened), 0x80110000, ctypes.byref(attributes),
                                             ctypes.byref(status), None, 0, 1, 1, 0x204060, None, 0)
                    if result >= 0:
                        handles.kernel.CloseHandle(opened)
                    self.assertLess(result, 0, "Native parent-relative open followed a junction")
                self.assertEqual((foreign / "a.md").read_bytes(), b"owned file identity")
            finally:
                if redirected:
                    generation.rmdir()

    def test_dry_run_is_zero_write_and_apply_retains_two_latest_generations(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager, arguments = _capture(temporary)
            before = _contents(manager.task_path)
            plan = manager.reconcile("dry-run", *arguments)
            self.assertEqual(_contents(manager.task_path), before)
            self.assertEqual(len(plan["targets"]), 1)
            result = manager.reconcile("apply", *arguments, plan_hash=plan["planHash"])
            self.assertEqual(result["status"], "applied")
            self.assertFalse((manager.task_path / "generations/000001/a.md").exists())
            for generation in (2, 3):
                self.assertEqual((manager.task_path / f"generations/{generation:06d}/a.md").read_text(), "# Owned\n")
            self.assertEqual(_contents(manager.task_path)["manifest.yaml"], before["manifest.yaml"])

    def test_dry_run_rejects_generation_and_nested_junctions(self):
        for nested in (False, True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manager, arguments = _capture(root)
                foreign = root / "foreign"
                foreign.mkdir()
                sentinel = foreign / "sentinel.md"
                sentinel.write_text("external sentinel", encoding="utf-8")
                link = manager.task_path / ("generations/000001/nested" if nested else "generations/0")
                _junction(link, foreign)
                try:
                    with self.assertRaisesRegex(WorkArtifactError, "path-reparse"):
                        manager.reconcile("dry-run", *arguments)
                    self.assertEqual(sentinel.read_text(), "external sentinel")
                finally:
                    link.rmdir()

    def test_apply_rejects_task_or_generation_ancestor_swapped_after_plan(self):
        for task in (False, True):
            with self.subTest(task=task), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manager, arguments = _capture(root)
                plan = manager.reconcile("dry-run", *arguments)
                target = manager.task_path if task else manager.task_path / "generations"
                saved, foreign = root / "saved", root / "foreign"
                target.rename(saved)
                shutil.copytree(saved, foreign)
                before = _contents(foreign)
                _junction(target, foreign)
                try:
                    with self.assertRaisesRegex(WorkArtifactError, "path-reparse"):
                        manager.reconcile("apply", *arguments, plan_hash=plan["planHash"])
                    self.assertEqual(_contents(foreign), before)
                finally:
                    target.rmdir()

    def test_same_content_replacement_requires_a_new_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager, arguments = _capture(root)
            plan = manager.reconcile("dry-run", *arguments)
            target = manager.task_path / "generations/000001/a.md"
            retained = root / "retained.md"
            target.rename(retained)
            target.write_bytes(retained.read_bytes())
            with self.assertRaisesRegex(WorkArtifactError, "reconcile-plan-mismatch"):
                manager.reconcile("apply", *arguments, plan_hash=plan["planHash"])
            self.assertEqual(target.read_bytes(), retained.read_bytes())

    def test_linked_lock_is_rejected_without_modifying_the_link_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager, arguments = _capture(root)
            plan = manager.reconcile("dry-run", *arguments)
            sentinel = root / "external.lock"
            sentinel.write_bytes(b"untouched")
            lock = manager.task_path / ".task.lock"
            lock.unlink()
            os.link(sentinel, lock)
            with self.assertRaises(WorkArtifactError):
                manager.reconcile("apply", *arguments, plan_hash=plan["planHash"])
            self.assertEqual(sentinel.read_bytes(), b"untouched")
            self.assertTrue((manager.task_path / "generations/000001/a.md").is_file())

    def test_busy_candidate_prevents_deleting_any_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager, arguments = _capture(temporary, two_files=True)
            plan = manager.reconcile("dry-run", *arguments)
            generation = manager.task_path / "generations/000001"
            with _deny_delete(generation / "b.md"):
                with self.assertRaises(WorkArtifactError):
                    manager.reconcile("apply", *arguments, plan_hash=plan["planHash"])
            self.assertEqual(sorted(file.name for file in generation.iterdir()), ["a.md", "b.md"])

    def test_apply_respects_the_existing_task_byte_lock(self):
        import msvcrt
        with tempfile.TemporaryDirectory() as temporary:
            manager, arguments = _capture(temporary)
            plan = manager.reconcile("dry-run", *arguments)
            with (manager.task_path / ".task.lock").open("r+b") as lock:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                try:
                    with self.assertRaisesRegex(WorkArtifactError, "task-locked"):
                        manager.reconcile("apply", *arguments, plan_hash=plan["planHash"])
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            self.assertTrue((manager.task_path / "generations/000001/a.md").is_file())
