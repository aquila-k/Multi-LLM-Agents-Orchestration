from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class LockError(RuntimeError):
    pass


@dataclass(frozen=True)
class LockInfo:
    path: Path
    owner: dict[str, Any]


class FileLock:
    def __init__(self, path: Path, *, stale_after_seconds: int = 900) -> None:
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self._acquired = False

    def acquire(self, *, allow_stale_recovery: bool = False) -> LockInfo:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            if allow_stale_recovery and self._is_stale():
                self.path.unlink()
            else:
                raise LockError(f"lock already held: {self.path}")

        owner = {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "started_at": _isoformat(datetime.now(timezone.utc)),
        }
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise LockError(f"lock already held: {self.path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(owner, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
        self._acquired = True
        return LockInfo(path=self.path, owner=owner)

    def release(self) -> None:
        if self._acquired and self.path.exists():
            self.path.unlink()
        self._acquired = False

    def __enter__(self) -> LockInfo:
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def _is_stale(self) -> bool:
        try:
            owner = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        pid = owner.get("pid")
        started_at = owner.get("started_at")
        if not _pid_is_alive(pid):
            return True
        if not started_at:
            return True
        try:
            start_epoch = datetime.fromisoformat(
                started_at.replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            return True
        return (time.time() - start_epoch) > self.stale_after_seconds


def _pid_is_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
