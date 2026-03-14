from __future__ import annotations

from typing import Any

REQUIRED_KEYS = [
    "current_task_intent",
    "user_added_instructions",
    "prior_decisions",
    "active_constraints",
    "required_outputs",
    "stop_conditions",
    "unresolved_questions",
]
OPTIONAL_DROP_KEYS = [
    "historical_narrative",
    "superseded_alternatives",
    "duplicate_explanations",
]


def condense_context(context: dict[str, Any], *, current_step: str) -> dict[str, Any]:
    retained = {key: context.get(key) for key in REQUIRED_KEYS if key in context}
    dropped = []
    for key in OPTIONAL_DROP_KEYS:
        if key in context and context.get(key):
            dropped.append(
                {
                    "category": key,
                    "reason": f"not required for current step {current_step}",
                }
            )
    references = list(context.get("references", []))
    confidence = (
        1.0 if all(key in retained for key in REQUIRED_KEYS if key in context) else 0.6
    )
    status = "ready" if confidence >= 0.8 else "needs_review"
    return {
        "retained": retained,
        "dropped": dropped,
        "references": references,
        "confidence": confidence,
        "status": status,
    }
