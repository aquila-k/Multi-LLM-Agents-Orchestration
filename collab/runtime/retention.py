from __future__ import annotations

from datetime import datetime, timedelta, timezone

RETENTION_WINDOWS_DAYS = {
    "ephemeral": 1,
    "debug": 14,
    "standard": 90,
    "audit": 180,
}
SIZE_CAP_BYTES = {
    "request": 256 * 1024,
    "response": 512 * 1024,
    "normalized": 512 * 1024,
    "validation": 256 * 1024,
    "raw": 2 * 1024 * 1024,
    "shell_summary": 1024,
}


def retention_deadline(created_at: str, retention_class: str) -> str:
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    days = RETENTION_WINDOWS_DAYS.get(
        retention_class, RETENTION_WINDOWS_DAYS["standard"]
    )
    deadline = created + timedelta(days=days)
    return (
        deadline.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def is_retained(created_at: str, retention_class: str, now: str | None = None) -> bool:
    deadline = datetime.fromisoformat(
        retention_deadline(created_at, retention_class).replace("Z", "+00:00")
    )
    current = (
        datetime.fromisoformat(now.replace("Z", "+00:00"))
        if now
        else datetime.now(timezone.utc)
    )
    return current <= deadline


def fits_size_cap(artifact_kind: str, content: str) -> bool:
    cap = SIZE_CAP_BYTES.get(artifact_kind)
    if cap is None:
        return True
    return len(content.encode("utf-8")) <= cap
