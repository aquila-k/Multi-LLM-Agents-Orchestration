from __future__ import annotations

import json
from typing import Any


def build_manifest_snapshot(
    *,
    request: dict[str, Any],
    resolved_config: dict[str, Any],
    routing_result: dict[str, Any],
    artifact_refs: dict[str, str],
    stop_and_confirm: bool,
    blocked_reason: str,
    plan_artifact_refs: dict[str, str] | None = None,
    approval_refs: dict[str, str] | None = None,
    final_report_ref: str = "",
) -> dict[str, Any]:
    phase = resolved_config["phase"]
    step = request.get("selectors", {}).get("step", "intake")
    strategy = resolved_config["strategy"]["selectedStrategyId"]
    return {
        "schemaVersion": "1.0.0",
        "taskId": request["task_id"],
        "activePhase": phase,
        "activeStrategyId": strategy,
        "activeStep": step,
        "attempt": 1,
        "run": 1,
        "controllerStatus": "blocked" if stop_and_confirm else "running",
        "budgetState": routing_result.get("budgetState", "healthy"),
        "resumeCursor": {
            "phase": phase,
            "strategy": strategy,
            "step": step,
            "resumeFrom": request.get("selectors", {}).get("resume_from", ""),
            "approvalContinuation": request.get("selectors", {}).get(
                "approval_continuation", ""
            ),
            "artifactRef": artifact_refs.get("manifest", ""),
        },
        "blockers": [blocked_reason] if stop_and_confirm and blocked_reason else [],
        "blockerRefs": [],
        "sessionRefs": {
            "provider": resolved_config["provider"]["provider"],
            "sessionRef": None,
        },
        "approvalState": {
            "required": bool(request.get("constraints", {}).get("approvals_required")),
            "status": (
                "approved"
                if request.get("selectors", {}).get("approval_continuation")
                else (
                    "pending"
                    if request.get("constraints", {}).get("approvals_required")
                    else "not_required"
                )
            ),
            "marker": request.get("selectors", {}).get("approval_continuation", ""),
        },
        "approvalRefs": {
            "approvalRequestRef": (
                approval_refs.get("approvalRequestRef", "") if approval_refs else ""
            ),
            "approvalDecisionRef": (
                approval_refs.get("approvalDecisionRef", "") if approval_refs else ""
            ),
        },
        "lastSuccessfulArtifactRefs": [
            ref
            for ref in (
                artifact_refs.get("request", ""),
                artifact_refs.get("resolvedConfig", ""),
                artifact_refs.get("routingResult", ""),
                artifact_refs.get("promptBundle", ""),
                artifact_refs.get("summary", ""),
            )
            if ref
        ],
        "latestValidationApplySummary": {
            "summary": "request accepted; validation deferred to later phases",
            "validationRef": "",
            "applyResultRef": "",
        },
        "latestPhaseSummary": {
            "phase": phase,
            "summary": request.get("summary", ""),
            "artifactRef": artifact_refs.get("summary", ""),
        },
        "latestShellDigestRefs": (
            [
                artifact_refs.get("shellDigest", ""),
            ]
            if artifact_refs.get("shellDigest")
            else []
        ),
        "compositionMode": (
            "composed"
            if phase == "review"
            and resolved_config.get("phaseOptions", {}).get("withHarden", False)
            else "single"
        ),
        "phaseOptions": resolved_config.get("phaseOptions", {}),
        "planArtifactRefs": {
            "planRef": (
                plan_artifact_refs.get("planRef", "") if plan_artifact_refs else ""
            ),
            "checklistRef": (
                plan_artifact_refs.get("checklistRef", "") if plan_artifact_refs else ""
            ),
            "deferredItemsRef": (
                plan_artifact_refs.get("deferredItemsRef", "")
                if plan_artifact_refs
                else ""
            ),
        },
        "finalReportRef": final_report_ref,
        "artifactRefs": artifact_refs,
    }


def build_pause_confirm(
    *,
    request: dict[str, Any],
    resolved_config: dict[str, Any],
    routing_result: dict[str, Any],
    blocked_reason: str,
    artifact_refs: dict[str, str],
) -> dict[str, Any]:
    strategy = resolved_config["strategy"]["selectedStrategyId"]
    phase = resolved_config["phase"]
    return {
        "schemaVersion": "1.0.0",
        "stopReason": blocked_reason,
        "reasonCode": (routing_result.get("reasonCodes") or [blocked_reason])[0],
        "severity": "high" if blocked_reason == "blocked_for_approval" else "medium",
        "recommendedAction": _recommended_action(blocked_reason),
        "requiredArtifacts": [
            artifact_refs["request"],
            artifact_refs["resolvedConfig"],
            artifact_refs["routingResult"],
            artifact_refs["manifest"],
        ],
        "resumeOptions": [
            {
                "label": "continue_current_phase",
                "phase": phase,
                "strategy": strategy,
                "step": request.get("selectors", {}).get("step", "intake"),
            }
        ],
        "operatorDecision": None,
        "resolvedAt": None,
    }


def _recommended_action(blocked_reason: str) -> str:
    if blocked_reason == "blocked_for_approval":
        return "Review the approval-sensitive artifacts and confirm whether execution should continue."
    if blocked_reason == "below_minimum_confidence":
        return "Confirm whether to continue with the selected routing or adjust the strategy/provider choice."
    return "Review the blocking artifacts and choose a safe continuation path."


def build_runtime_pause_confirm(
    *,
    task_id: str,
    phase: str,
    step: str,
    strategy: str,
    blocked_reason: str,
    reason_code: str,
    artifact_refs: dict[str, str],
    severity: str = "medium",
) -> dict[str, Any]:
    required_artifacts = [
        ref
        for ref in (
            artifact_refs.get("request", ""),
            artifact_refs.get("resolvedConfig", ""),
            artifact_refs.get("routingResult", ""),
            artifact_refs.get("promptBundle", ""),
            artifact_refs.get("manifest", ""),
            artifact_refs.get("response", ""),
            artifact_refs.get("validation", ""),
            artifact_refs.get("applyResult", ""),
        )
        if ref
    ]
    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "stopReason": blocked_reason,
        "reasonCode": reason_code or blocked_reason,
        "severity": severity,
        "recommendedAction": _recommended_action(blocked_reason),
        "requiredArtifacts": required_artifacts,
        "resumeOptions": [
            {
                "label": "continue_current_phase",
                "phase": phase,
                "strategy": strategy,
                "step": step,
            }
        ],
        "operatorDecision": None,
        "resolvedAt": None,
    }


def extend_manifest_snapshot(
    *,
    manifest: dict[str, Any],
    phase: str,
    step: str,
    attempt: int,
    run: int,
    blocked_reason: str,
    session_refs: dict[str, Any],
    artifact_refs: dict[str, str],
    active_strategy_id: str | None = None,
    controller_status: str | None = None,
    approval_state: dict[str, Any] | None = None,
    resume_cursor: dict[str, Any] | None = None,
    last_successful_artifact_refs: list[str] | None = None,
    latest_validation_apply_summary: dict[str, Any] | None = None,
    latest_phase_summary: dict[str, Any] | None = None,
    latest_shell_digest_refs: list[str] | None = None,
    blocker_refs: list[str] | None = None,
    composition_mode: str | None = None,
    plan_artifact_refs: dict[str, str] | None = None,
    final_report_ref: str | None = None,
) -> dict[str, Any]:
    updated = json.loads(json.dumps(manifest))
    updated["activePhase"] = phase
    updated["activeStep"] = step
    updated["attempt"] = attempt
    updated["run"] = run
    if active_strategy_id:
        updated["activeStrategyId"] = active_strategy_id
    if controller_status:
        updated["controllerStatus"] = controller_status
    updated["blockers"] = [blocked_reason] if blocked_reason else []
    if blocker_refs is not None:
        updated["blockerRefs"] = blocker_refs
    existing_resume_cursor = dict(updated.get("resumeCursor", {}))
    resume_cursor_updates = (
        {
            "phase": phase,
            "step": step,
        }
        if resume_cursor is None
        else resume_cursor
    )
    existing_resume_cursor.update(
        {
            key: value
            for key, value in resume_cursor_updates.items()
            if value is not None
        }
    )
    updated["resumeCursor"] = existing_resume_cursor
    merged_session_refs = dict(updated.get("sessionRefs", {}))
    merged_session_refs.update(
        {key: value for key, value in session_refs.items() if value is not None}
    )
    updated["sessionRefs"] = merged_session_refs
    if approval_state is not None:
        updated["approvalState"] = approval_state
    if last_successful_artifact_refs is not None:
        updated["lastSuccessfulArtifactRefs"] = last_successful_artifact_refs
    if latest_validation_apply_summary is not None:
        updated["latestValidationApplySummary"] = latest_validation_apply_summary
    if latest_phase_summary is not None:
        updated["latestPhaseSummary"] = latest_phase_summary
    if latest_shell_digest_refs is not None:
        updated["latestShellDigestRefs"] = latest_shell_digest_refs
    if composition_mode is not None:
        updated["compositionMode"] = composition_mode
    if final_report_ref is not None:
        updated["finalReportRef"] = final_report_ref
    existing_plan_refs = dict(updated.get("planArtifactRefs", {}))
    source_plan_refs = plan_artifact_refs or {}
    if not source_plan_refs:
        source_plan_refs = {
            key: artifact_refs.get(key, "")
            for key in ("planRef", "checklistRef", "deferredItemsRef")
            if artifact_refs.get(key)
        }
    existing_plan_refs.update(
        {key: value for key, value in source_plan_refs.items() if value is not None}
    )
    updated["planArtifactRefs"] = {
        "planRef": existing_plan_refs.get("planRef", ""),
        "checklistRef": existing_plan_refs.get("checklistRef", ""),
        "deferredItemsRef": existing_plan_refs.get("deferredItemsRef", ""),
    }
    merged_artifact_refs = dict(updated.get("artifactRefs", {}))
    merged_artifact_refs.update(
        {key: value for key, value in artifact_refs.items() if value}
    )
    updated["artifactRefs"] = merged_artifact_refs
    return updated
