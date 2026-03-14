from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventLog:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()

    def append(
        self,
        *,
        task_id: str,
        event_type: str,
        phase: str,
        step: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = self._path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": _isoformat(datetime.now(timezone.utc)),
            "task_id": task_id,
            "event_type": event_type,
            "phase": phase,
            "step": step,
            "payload": payload or {},
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")
        return event

    def read_all(self, task_id: str) -> list[dict[str, Any]]:
        path = self._path(task_id)
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _path(self, task_id: str) -> Path:
        return (
            self.root_dir / "collab" / "artifacts" / "tasks" / task_id / "events.jsonl"
        )


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
