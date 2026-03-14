from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactRecord:
    path: Path
    metadata: dict[str, Any]


class ArtifactStore:
    """Minimal append-only artifact writer for the collab runtime."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()

    def task_root(self, task_id: str) -> Path:
        return self.root_dir / "collab" / "artifacts" / "tasks" / task_id

    def family_dir(self, task_id: str, family: str) -> Path:
        path = self.task_root(task_id) / family
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_json_artifact(
        self,
        *,
        task_id: str,
        family: str,
        artifact_type: str,
        payload: dict[str, Any],
        filename: str,
        phase: str = "unknown",
        step: str = "unknown",
        attempt: int = 1,
        run: int = 1,
        visibility: str = "internal",
        retention_class: str = "standard",
        canonical: bool = True,
    ) -> ArtifactRecord:
        directory = self.family_dir(task_id, family)
        artifact_path = directory / filename
        created_at = _isoformat(datetime.now(timezone.utc))
        metadata = {
            "artifactId": f"{task_id}:{family}:{filename}",
            "artifactType": artifact_type,
            "taskId": task_id,
            "phase": phase,
            "step": step,
            "attempt": attempt,
            "run": run,
            "createdAt": created_at,
            "format": "json",
            "canonical": canonical,
            "visibility": visibility,
            "retentionClass": retention_class,
        }
        envelope = {"metadata": metadata, "payload": payload}
        artifact_path.write_text(
            json.dumps(envelope, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        return ArtifactRecord(path=artifact_path, metadata=metadata)

    def write_text_artifact(
        self,
        *,
        task_id: str,
        family: str,
        filename: str,
        content: str,
    ) -> Path:
        directory = self.family_dir(task_id, family)
        path = directory / filename
        path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
