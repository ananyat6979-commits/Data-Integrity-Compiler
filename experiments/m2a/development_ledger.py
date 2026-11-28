"""Resume development cases from a checksummed JSONL journal."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from dic.pipeline import sha256


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


@contextmanager
def _writer_lock(path: Path):
    # The operating system releases the lock if a worker exits unexpectedly.
    with path.open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _load_records(stream):
    stream.seek(0)
    while line := stream.readline():
        start = stream.tell() - len(line)
        try:
            if not line.endswith(b"\n"):
                raise ValueError("Incomplete record")
            envelope = json.loads(line)
            record = envelope["record"]
            if (
                envelope["sha256"] != hashlib.sha256(canonical(record)).hexdigest()
                or record["version"] != 1
            ):
                raise ValueError("Record checksum or version mismatch")
            for name in ("identity", "attempt", "artifacts", "result"):
                if name not in record:
                    raise ValueError("Missing record field")
        except (TypeError, KeyError, ValueError, UnicodeDecodeError) as exc:
            if stream.read(1):
                raise ValueError(f"Invalid development record at byte {start}") from exc
            stream.truncate(start)
            stream.flush()
            os.fsync(stream.fileno())
            return
        yield record


def _artifacts(attempt: Path) -> dict[str, str]:
    # Keep evidence under the execution root so the ledger never hashes a
    # private ground truth record.
    execution = attempt / "execution"
    if attempt.is_symlink() or execution.is_symlink():
        raise ValueError("Development evidence directory cannot be a symbolic link")
    paths = sorted(execution.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("Development evidence cannot include symbolic links")
    return {
        path.relative_to(attempt).as_posix(): sha256(path)
        for path in paths if path.is_file()
    }


def execute_or_resume(workspace: Path, journal: Path, identity: dict, run_case) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with _writer_lock(journal.with_name(journal.name + ".lock")), journal.open("a+b") as stream:
        candidates = [record for record in _load_records(stream) if record["identity"] == identity]
        for record in reversed(candidates):
            name = record["attempt"]
            if len(name) != 32 or any(c not in "0123456789abcdef" for c in name):
                raise ValueError("Invalid attempt name in development journal")
            if record["artifacts"] and _artifacts(workspace / name) == record["artifacts"]:
                return record["result"]

        attempt = workspace / uuid4().hex
        result = run_case(attempt)
        artifacts = _artifacts(attempt)
        if not artifacts:
            raise ValueError("Development case completed without persisted evidence")
        record = {
            "version": 1,
            "identity": identity,
            "attempt": attempt.name,
            "artifacts": artifacts,
            "result": result,
        }
        line = canonical({"record": record, "sha256": hashlib.sha256(canonical(record)).hexdigest()})
        stream.seek(0, os.SEEK_END)
        stream.write(line + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
        return result
