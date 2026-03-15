from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.pathing import task_artifacts_dir


class DecisionLog:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()

    def append(
        self,
        *,
        task_id: str,
        decision_type: str,
        phase: str,
        step: str,
        outcome: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = self._path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        decision = {
            "timestamp": _isoformat(datetime.now(timezone.utc)),
            "task_id": task_id,
            "decision_type": decision_type,
            "phase": phase,
            "step": step,
            "outcome": outcome,
            "payload": payload or {},
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision, ensure_ascii=True) + "\n")
        return decision

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
        return task_artifacts_dir(self.root_dir, task_id) / "decisions.jsonl"


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
