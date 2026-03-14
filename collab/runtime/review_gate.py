"""Completion gate for review and harden phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from collab.runtime.findings import (
    extract_findings,
    findings_summary,
    has_blocking_findings,
)


@dataclass(frozen=True)
class ReviewGateResult:
    can_complete: bool
    blocking_found: bool
    fixable_operations: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    summary: dict[str, Any]
    blocked_reason: str


def evaluate_review_gate(normalized: dict[str, Any]) -> ReviewGateResult:
    """Evaluate whether a review/harden step can complete."""
    findings = extract_findings(normalized)
    summary = findings_summary(findings)
    blocking = has_blocking_findings(findings)

    fixable_ops: list[dict[str, Any]] = []
    for finding in findings:
        operations = finding.get("fix_operations")
        if finding.get("fixable") and isinstance(operations, list):
            fixable_ops.extend(operations)

    if blocking:
        return ReviewGateResult(
            can_complete=False,
            blocking_found=True,
            fixable_operations=fixable_ops,
            findings=findings,
            summary=summary,
            blocked_reason="review_blocking_findings",
        )

    return ReviewGateResult(
        can_complete=True,
        blocking_found=False,
        fixable_operations=fixable_ops,
        findings=findings,
        summary=summary,
        blocked_reason="",
    )


def should_continue_loop(
    gate_result: ReviewGateResult, loop_state: dict[str, Any]
) -> tuple[bool, str]:
    """Determine whether iterative remediation should continue."""
    if not gate_result.blocking_found:
        return False, "blocking_cleared"

    current_iteration = int(
        loop_state.get("current_iteration", loop_state.get("currentIteration", 0))
    )
    max_loops = int(loop_state.get("max_loops", loop_state.get("maxLoops", 0)))
    if current_iteration >= max_loops:
        return False, "loop_cap_reached"

    if not gate_result.fixable_operations:
        return False, "no_fixable_operations"

    return True, "blocking_found"


def build_loop_state(
    current_iteration: int, max_loops: int, blockers_resolved: int = 0
) -> dict[str, Any]:
    return {
        "currentIteration": current_iteration,
        "maxLoops": max_loops,
        "blockersResolvedCount": blockers_resolved,
        "status": "running",
    }
