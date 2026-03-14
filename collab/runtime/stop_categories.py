"""First-class stop category codes used by the collab runtime.

These correspond to requirement §11.3 and are used consistently across
routing, auto-advance, pause-confirm, and resume logic.
"""

from __future__ import annotations

# --- First-class stop categories (§11.3) ---
APPROVAL_REQUIRED = "approval_required"
TASK_AMBIGUITY = "task_ambiguity"
MISSING_TOOL_OR_AUTH = "missing_tool_or_auth"
PROVIDER_RETRY_EXHAUSTED = "provider_retry_exhausted"
UNSAFE_APPLY = "unsafe_apply"
BUDGET_STOP = "budget_stop"
LOOP_CAP_REACHED = "loop_cap_reached"
STRATEGY_BUDGET_PREFLIGHT = "strategy_budget_preflight"
RESUME_OVERRIDE_CONFLICT = "resume_override_conflict"
PROVIDER_CAPABILITY_MISMATCH = "provider_capability_mismatch"
ARTIFACT_CONSISTENCY_FAILURE = "artifact_consistency_failure"
PLAN_ARTIFACT_INCOMPLETE = "plan_artifact_incomplete"

# --- Routing-level stop signals checked by auto-advance ---
AMBIGUITY_SIGNAL = "ambiguity_signal"
BELOW_MINIMUM_CONFIDENCE = "below_minimum_confidence"
NO_CANDIDATE_AFTER_FILTERS = "no_candidate_after_filters"
STRATEGY_OVERRIDE_DISABLED = "strategy_override_disabled"
STRATEGY_OVERRIDE_UNAVAILABLE = "strategy_override_unavailable"
TIE_BREAK_REASONING_REQUIRED = "tie_break_reasoning_required"

# --- Step contract failures ---
STEP_INPUT_CONTRACT_FAILED = "step_input_contract_failed"
STEP_OUTPUT_CONTRACT_FAILED = "step_output_contract_failed"

AUTO_ADVANCE_STOP_CODES = frozenset(
    {
        AMBIGUITY_SIGNAL,
        BELOW_MINIMUM_CONFIDENCE,
        BUDGET_STOP,
        NO_CANDIDATE_AFTER_FILTERS,
        STRATEGY_OVERRIDE_DISABLED,
        STRATEGY_OVERRIDE_UNAVAILABLE,
        TIE_BREAK_REASONING_REQUIRED,
    }
)
