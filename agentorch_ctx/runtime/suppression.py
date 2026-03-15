from __future__ import annotations

from typing import Any


class SuppressionTracker:
    """Simple duplicate suppression helper for event/decision emission."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def should_emit(
        self, category: str, key: str, payload: dict[str, Any] | None = None
    ) -> bool:
        suffix = ""
        if payload:
            suffix = repr(sorted(payload.items()))
        token = f"{category}:{key}:{suffix}"
        if token in self._seen:
            return False
        self._seen.add(token)
        return True
