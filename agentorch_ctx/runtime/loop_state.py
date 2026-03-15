"""Loop state artifact builder for review/harden iterative controller."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_loop_state_artifact(
    *,
    task_id: str,
    phase: str,
    strategy_id: str,
    current_iteration: int,
    max_loops: int,
    status: str,  # "running", "completed", "paused_loop_cap", "paused_budget", "paused_approval"
    blockers_resolved: int = 0,
    blockers_remaining: int = 0,
    fix_operations_applied: int = 0,
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "phase": phase,
        "strategyId": strategy_id,
        "currentIteration": current_iteration,
        "maxLoops": max_loops,
        "status": status,
        "blockersResolvedCount": blockers_resolved,
        "blockersRemainingCount": blockers_remaining,
        "fixOperationsApplied": fix_operations_applied,
        "createdAt": _isoformat(datetime.now(timezone.utc)),
    }


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
