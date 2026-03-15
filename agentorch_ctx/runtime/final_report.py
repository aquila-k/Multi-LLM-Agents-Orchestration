"""Final report artifact generator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_final_report(
    *,
    task_id: str,
    phase: str,
    strategy_id: str,
    step_records: list[dict[str, Any]],
    plan_artifact_refs: dict[str, str] | None = None,
    blocked_reason: str = "",
    controller_status: str = "completed",
) -> dict[str, Any]:
    """Build a final report artifact summarizing the phase run."""
    completed_steps = [
        r for r in step_records if r.get("controllerStatus") != "blocked"
    ]
    blocked_steps = [r for r in step_records if r.get("controllerStatus") == "blocked"]

    artifacts_produced: list[dict[str, str]] = []
    for record in step_records:
        for ref_key in (
            "responseRef",
            "normalizedRef",
            "applyResultRef",
            "validationRef",
        ):
            ref_val = str(record.get(ref_key, ""))
            if ref_val:
                artifacts_produced.append(
                    {
                        "type": ref_key,
                        "ref": ref_val,
                        "step": str(record.get("step", "")),
                    }
                )

    plan_refs = plan_artifact_refs or {}

    unresolved_items: list[str] = []
    if blocked_reason:
        unresolved_items.append(f"Phase blocked: {blocked_reason}")

    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "phase": phase,
        "strategyId": strategy_id,
        "generatedAt": _isoformat(datetime.now(timezone.utc)),
        "controllerStatus": controller_status,
        "summary": {
            "completedSteps": len(completed_steps),
            "blockedSteps": len(blocked_steps),
            "totalSteps": len(step_records),
        },
        "whatWasDone": [str(r.get("step", "unknown")) for r in completed_steps],
        "unresolvedItems": unresolved_items,
        "artifactLocations": artifacts_produced,
        "planArtifactRefs": plan_refs,
        "nextUserActions": _next_actions(controller_status, blocked_reason, phase),
        "blockedReason": blocked_reason,
    }


def _next_actions(controller_status: str, blocked_reason: str, phase: str) -> list[str]:
    if controller_status == "blocked":
        if "approval" in blocked_reason:
            return [
                "Review and approve the pending operations",
                f"Resume {phase} after approval",
            ]
        if "budget" in blocked_reason:
            return [
                "Confirm budget to proceed with this strategy",
                f"Resume {phase} after budget confirmation",
            ]
        return [
            f"Investigate blocked reason: {blocked_reason}",
            f"Resume {phase} when ready",
        ]
    next_phase = {
        "plan": "impl",
        "impl": "review",
        "review": "harden",
        "harden": None,
    }.get(phase)
    if next_phase:
        return [
            f"Run next phase: {next_phase}",
            "Or review artifacts before proceeding",
        ]
    return ["Review generated artifacts", "Task complete"]


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
