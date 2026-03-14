from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from collab.runtime.artifact_store import ArtifactStore


class CheckpointManager:
    def __init__(self, root_dir: Path) -> None:
        self.store = ArtifactStore(root_dir)

    def create_checkpoint(
        self,
        *,
        task_id: str,
        target_paths: list[Path],
        phase: str,
        step: str,
        attempt: int = 1,
        run: int = 1,
    ) -> Path:
        snapshots = []
        for path in target_paths:
            if path.exists():
                content = path.read_text(encoding="utf-8")
                snapshots.append(
                    {
                        "path": str(path),
                        "existed": True,
                        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        "content": content,
                    }
                )
            else:
                snapshots.append(
                    {
                        "path": str(path),
                        "existed": False,
                        "sha256": "",
                        "content": "",
                    }
                )
        record = {
            "created_at": _isoformat(datetime.now(timezone.utc)),
            "snapshots": snapshots,
        }
        artifact = self.store.write_json_artifact(
            task_id=task_id,
            family="checkpoints",
            artifact_type="checkpoint",
            payload=record,
            filename=f"checkpoint-{phase}-{step}-{attempt}-{run}.json",
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
            retention_class="audit",
        )
        return artifact.path


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
