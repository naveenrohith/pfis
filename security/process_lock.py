"""Small nonblocking advisory file lock for one assessment per local lab."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import IO


class ProcessLock:
    """Hold an OS lock that is released automatically when its process exits."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._file: IO[bytes] | None = None
        self._guard = threading.Lock()

    def try_acquire(self) -> bool:
        with self._guard:
            if self._file is not None:
                return True
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    lock_file = getattr(msvcrt, "locking")  # noqa: B009
                    nonblocking_lock = getattr(msvcrt, "LK_NBLCK")  # noqa: B009
                    lock_file(handle.fileno(), nonblocking_lock, 1)
                else:
                    import fcntl

                    lock_file = getattr(fcntl, "flock")  # noqa: B009
                    lock_flags = getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB")  # noqa: B009
                    lock_file(handle.fileno(), lock_flags)
            except OSError:
                handle.close()
                return False
            self._file = handle
            return True

    def release(self) -> None:
        with self._guard:
            handle = self._file
            if handle is None:
                return
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    lock_file = getattr(msvcrt, "locking")  # noqa: B009
                    unlock_lock = getattr(msvcrt, "LK_UNLCK")  # noqa: B009
                    lock_file(handle.fileno(), unlock_lock, 1)
                else:
                    import fcntl

                    unlock_file = getattr(fcntl, "flock")  # noqa: B009
                    unlock_file(handle.fileno(), getattr(fcntl, "LOCK_UN"))  # noqa: B009
            finally:
                handle.close()
                self._file = None
