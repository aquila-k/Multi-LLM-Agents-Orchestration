"""File-based write lock for serializing DB writes."""

import json
import os
import socket
import time
from pathlib import Path

from ..core.errors import LockTimeout
from ..core.ids import now_iso

LOCK_FILENAME = ".write.lock"


class StaleLock(Exception):
    """Raised when a stale lock is detected and cleaned up."""

    pass


class WriteLock:
    """
    Context manager for file-based write lock.

    Lock file path: {db_dir}/.write.lock
    Lock file contents: JSON with pid, hostname, started_at, command

    Acquisition:
      1. Try open(lock_path, O_CREAT | O_EXCL | O_WRONLY) — atomic on POSIX
      2. If file exists: check PID liveness via os.kill(pid, 0)
         - if dead OR file age > timeout_sec: delete and retry
         - if alive: wait 0.5s and retry
      3. If timeout_sec passes: raise LockTimeout

    Release: always in __exit__, unlink lock_path
    """

    def __init__(self, db_dir: Path, command: str = "unknown", timeout_sec: int = None):
        self.db_dir = Path(db_dir)
        self.lock_path = self.db_dir / LOCK_FILENAME
        self.command = command
        if timeout_sec is not None:
            self.timeout_sec = timeout_sec
        else:
            env_val = os.environ.get("CONTEXTS_LOCK_TIMEOUT")
            if env_val is not None:
                try:
                    self.timeout_sec = int(env_val)
                except ValueError:
                    self.timeout_sec = 30
            else:
                self.timeout_sec = 30
        self._acquired = False

    def _lock_info(self) -> dict:
        return {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "started_at": now_iso(),
            "command": self.command,
        }

    def _is_pid_alive(self, pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _try_acquire(self) -> bool:
        """Attempt to atomically create the lock file. Returns True if acquired."""
        try:
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                info = json.dumps(self._lock_info())
                os.write(fd, info.encode("utf-8"))
            finally:
                os.close(fd)
            self._acquired = True
            return True
        except FileExistsError:
            return False
        except OSError:
            return False

    def _check_and_clean_stale(self) -> bool:
        """
        Check if the existing lock is stale (dead PID or too old).
        If stale, remove and return True. Otherwise return False.
        """
        try:
            with open(str(self.lock_path), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            # Can't read lock file — try to remove it
            try:
                os.unlink(str(self.lock_path))
            except OSError:
                pass
            return True

        pid = data.get("pid")
        if pid is not None and not self._is_pid_alive(pid):
            try:
                os.unlink(str(self.lock_path))
            except OSError:
                pass
            return True

        # Check file age
        try:
            stat = os.stat(str(self.lock_path))
            age = time.time() - stat.st_mtime
            if age > self.timeout_sec:
                try:
                    os.unlink(str(self.lock_path))
                except OSError:
                    pass
                return True
        except OSError:
            return False

        return False

    def __enter__(self):
        deadline = time.monotonic() + self.timeout_sec
        while True:
            if self._try_acquire():
                return self

            if self._check_and_clean_stale():
                if self._try_acquire():
                    return self

            if time.monotonic() >= deadline:
                raise LockTimeout(
                    "Could not acquire write lock at {} within {} seconds".format(
                        self.lock_path, self.timeout_sec
                    )
                )
            time.sleep(0.5)

    def __exit__(self, *args):
        if self._acquired:
            try:
                os.unlink(str(self.lock_path))
            except OSError:
                pass
            self._acquired = False
