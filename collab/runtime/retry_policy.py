from __future__ import annotations

from typing import Any

AUTO_RETRY_CONDITIONS = frozenset(
    {
        "cold_stop_no_output",
        "transient_cli_error",
        "recoverable_operational",
    }
)

NON_RETRY_CONDITIONS = frozenset(
    {
        "timeout_with_output",
        "output_contract_violation_meaningful",
        "diff_apply_failed_reinterpretable",
        "ambiguity_or_approval",
    }
)


def classify_retry_candidate(
    *,
    coordination_result_summary: dict[str, Any],
    apply_result: dict[str, Any] | None,
    normalized: dict[str, Any] | None,
) -> dict[str, Any]:
    if apply_result and apply_result.get("result") == "applied":
        return {
            "auto_retry_eligible": False,
            "reason": "already_applied",
            "preserve_existing": True,
            "retry_condition": "already_applied",
        }

    controller_status = str(coordination_result_summary.get("controller_status", ""))
    blocked_reason = str(coordination_result_summary.get("blocked_reason", ""))
    has_meaningful_output = bool(
        normalized and normalized.get("status") not in {"", "failed_unusable"}
    )

    if blocked_reason in {
        "task_ambiguity",
        "blocked_for_approval",
        "missing_exact_session_ref",
    }:
        return {
            "auto_retry_eligible": False,
            "reason": "human_decision_required",
            "preserve_existing": True,
            "retry_condition": "ambiguity_or_approval",
        }

    if has_meaningful_output:
        return {
            "auto_retry_eligible": False,
            "reason": "meaningful_output_preserved_for_analysis",
            "preserve_existing": True,
            "retry_condition": "output_contract_violation_meaningful",
        }

    if controller_status == "blocked" and not has_meaningful_output:
        return {
            "auto_retry_eligible": True,
            "reason": "cold_stop_no_meaningful_output",
            "preserve_existing": True,
            "retry_condition": "cold_stop_no_output",
        }

    return {
        "auto_retry_eligible": False,
        "reason": "default_no_retry",
        "preserve_existing": True,
        "retry_condition": "default",
    }
