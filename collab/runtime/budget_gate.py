from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BudgetDecision:
    budget_state: str
    stop_required: bool
    reroute_recommended: bool


@dataclass(frozen=True)
class EscalationDecision:
    allowed: bool
    requires_approval: bool
    reason: str
    reroute_candidates: list[str]


class BudgetGate:
    def evaluate(self, budget: dict[str, Any]) -> BudgetDecision:
        hard_cap = _safe_float(budget.get("hardCap", budget.get("taskHardCap", 0)))
        soft_cap = _safe_float(budget.get("softCap", budget.get("taskSoftCap", 0)))
        consumed = _safe_float(budget.get("consumed", 0))
        estimated_next = _safe_float(
            budget.get("estimatedNextCost", budget.get("estimatedNextCostUnits", 0))
        )
        if hard_cap and consumed + estimated_next > hard_cap:
            return BudgetDecision("hard_limit_exceeded", True, False)
        if hard_cap and consumed >= hard_cap * 0.9:
            return BudgetDecision("hard_limit_near", True, False)
        if soft_cap and consumed + estimated_next > soft_cap:
            return BudgetDecision("soft_limit_exceeded", False, True)
        if soft_cap and consumed >= soft_cap * 0.9:
            return BudgetDecision("soft_limit_near", False, True)
        return BudgetDecision("healthy", False, False)

    def evaluate_loop_iteration(
        self,
        budget: dict[str, Any],
        current_iteration: int,
        max_loops: int,
        estimated_cost_per_loop: float = 0.0,
    ) -> BudgetDecision:
        remaining_loops = max(0, max_loops - current_iteration)
        projected_additional_cost = (
            _safe_float(estimated_cost_per_loop) * remaining_loops
        )
        hard_cap = _safe_float(budget.get("hardCap", budget.get("taskHardCap", 0)))
        consumed = _safe_float(budget.get("consumed", 0))
        if hard_cap and consumed + projected_additional_cost > hard_cap:
            return BudgetDecision("budget_stop", True, False)
        return self.evaluate(budget)

    def evaluate_escalation(
        self,
        current_provider: str,
        target_provider: str,
        budget: dict[str, Any],
        escalation_requires_approval: bool = True,
        reroute_candidates: list[str] | None = None,
    ) -> EscalationDecision:
        reroute = list(reroute_candidates or [])
        has_approval = bool(budget.get("escalationDecisionRef"))
        if escalation_requires_approval and not has_approval:
            return EscalationDecision(
                allowed=False,
                requires_approval=True,
                reason="escalation_needs_approval",
                reroute_candidates=reroute,
            )

        hard_cap = _safe_float(budget.get("hardCap", budget.get("taskHardCap", 0)))
        consumed = _safe_float(budget.get("consumed", 0))
        estimated_next = _safe_float(
            budget.get("estimatedNextCost", budget.get("estimatedNextCostUnits", 0))
        )
        if hard_cap and consumed + estimated_next > hard_cap:
            return EscalationDecision(
                allowed=False,
                requires_approval=False,
                reason="hard_limit_exceeded",
                reroute_candidates=reroute,
            )

        if current_provider == target_provider:
            return EscalationDecision(
                allowed=True,
                requires_approval=False,
                reason="same_provider",
                reroute_candidates=reroute,
            )

        return EscalationDecision(
            allowed=True,
            requires_approval=False,
            reason="allowed",
            reroute_candidates=reroute,
        )


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
