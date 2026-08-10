"""Crash-safe JSON persistence: advisory locks + atomic replace.

The scheduler has had this since it started running under concurrent Claude
Code tool calls. The profile — which holds every private key — had none of it:
``save()`` was ``read_text()`` … 55 lines … ``write_text()``, so a crash
mid-write truncated the only copy of the identity, and two writers that
overlapped a network round-trip silently lost one side's changes.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

__all__ = ["atomic_write_json", "file_lock", "locked_read_json"]


@contextmanager
def file_lock(lock_path: Path, *, shared: bool = False) -> Iterator[int]:
    """Hold an advisory lock on *lock_path* for the duration of the block.

    Yields the lock file descriptor. Shared locks allow concurrent readers;
    the default exclusive lock serialises writers.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_write_json(path: Path, data: Any, *, mode: int | None = None) -> None:
    """Write JSON via tmp file → fsync → rename. Caller should hold the lock.

    *mode* is applied to the temp file **before** the rename, so the file is
    never visible at its final path with wider permissions — the previous
    write-then-chmod left a window on the key file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, default=str) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        encoded = content.encode()
        total = 0
        while total < len(encoded):
            written = os.write(fd, encoded[total:])
            if written == 0:
                raise OSError("os.write returned 0 bytes during atomic write")
            total += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        if mode is not None:
            Path(tmp).chmod(mode)
        Path(tmp).replace(path)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        with suppress(OSError):
            Path(tmp).unlink(missing_ok=True)
        raise


def locked_read_json(path: Path, lock_path: Path) -> Any | None:
    """Read JSON under a shared lock. None if missing or corrupt."""
    if not path.exists():
        return None
    with file_lock(lock_path, shared=True):
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
