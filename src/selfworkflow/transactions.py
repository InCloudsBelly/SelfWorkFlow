"""Small transaction primitives for the sandbox-safe installer."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time


class TransactionError(RuntimeError):
    pass


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


@contextmanager
def exclusive_install_lock(state_root: str | Path):
    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "install.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise TransactionError("installer-locked") from None
    body_failure = None
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        descriptor = -1
        yield lock_path
    except BaseException as failure:
        body_failure = failure
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        for attempt in range(3):
            try:
                lock_path.unlink(missing_ok=True)
                break
            except OSError:
                if attempt < 2:
                    time.sleep(0.1)
                    continue
                if body_failure is not None:
                    body_failure.add_note("installer-lock-release-failed")
                else:
                    raise TransactionError("installer-lock-release-failed") from None


def recover_transactions(state_root: str | Path) -> list[dict[str, str]]:
    transaction_root = Path(state_root) / "transactions"
    if not transaction_root.is_dir():
        return []
    result: list[dict[str, str]] = []
    for path in sorted(transaction_root.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result.append({"transactionId": path.stem, "action": "manual-attention"})
            continue
        if value.get("state") not in {"completed", "rolled-back"}:
            result.append(
                {
                    "transactionId": str(value.get("transactionId", path.stem)),
                    "action": "manual-attention",
                }
            )
    return result
