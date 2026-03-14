from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from collab.runtime.budget_gate import BudgetDecision, BudgetGate
from collab.runtime.capabilities import CapabilityRegistry

PHASE_WEIGHTS = {
    "plan": {
        "ambiguityLevel": 3,
        "evidenceLevel": 3,
        "coordinationComplexity": 2,
        "sessionReuseValue": 2,
        "providerUncertaintyScore": -3,
    },
    "impl": {
        "targetFileCount": 2,
        "targetFileBytes": 2,
        "contextDemand": 3,
        "toolDependence": 2,
        "applyRisk": 3,
        "normalizationBurdenScore": 2,
        "consistencyDemand": 2,
    },
    "review": {
        "evidenceLevel": 3,
        "artifactStrictness": 3,
        "consistencyDemand": 3,
        "mergeComplexity": 2,
        "knownFailureSignals": -3,
    },
    "harden": {
        "securityLevel": 4,
        "evidenceLevel": 3,
        "applyRisk": 3,
        "toolDependence": 2,
        "providerUncertaintyScore": -4,
    },
}
ORDINAL = {"low": 1, "medium": 2, "high": 3, "extreme": 4}


@dataclass(frozen=True)
class RoutingResult:
    selected: dict[str, Any] | None
    excluded: list[dict[str, Any]]
    budget_state: str
    stop_and_confirm: bool
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    hard_filters_applied: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    confidence: float = 0.0


class RoutingEngine:
    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        budget_gate: BudgetGate | None = None,
        policy: dict[str, Any] | None = None,
    ) -> None:
        self.capability_registry = capability_registry
        self.budget_gate = budget_gate or BudgetGate()
        self.policy = policy or {}

    def route(
        self,
        *,
        phase: str,
        candidates: list[dict[str, Any]],
        metrics: dict[str, Any],
        required_capabilities: list[dict[str, Any]] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> RoutingResult:
        budget_decision = self.budget_gate.evaluate(budget or {})
        if budget_decision.stop_required:
            return RoutingResult(
                selected=None,
                excluded=[],
                budget_state=budget_decision.budget_state,
                stop_and_confirm=True,
                reason_codes=["budget_stop"],
            )

        ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        excluded: list[dict[str, Any]] = []
        hard_filters: list[str] = []
        for candidate in candidates:
            exclusion_reason = self._exclude_reason(
                candidate, required_capabilities or []
            )
            if exclusion_reason:
                excluded.append({"candidate": candidate, "reason": exclusion_reason})
                hard_filters.append(exclusion_reason)
                continue
            score, breakdown = self._score_candidate(
                phase, candidate, metrics, budget_decision
            )
            ranked.append((score, candidate, breakdown))

        ranked.sort(key=lambda item: item[0], reverse=True)
        candidate_scores = self._build_candidate_scores(phase, ranked)
        thresholds = self._phase_policy(phase).get("thresholds", {})
        stop_and_confirm = False
        reason_codes: list[str] = []
        if budget_decision.reroute_recommended:
            reason_codes.append("budget_rerank_recommended")
        if candidate_scores:
            top_score = candidate_scores[0]["normalizedScore"]
            if top_score < thresholds.get("minimumNormalizedScore", 0):
                stop_and_confirm = True
                reason_codes.append("below_minimum_confidence")
            if len(candidate_scores) > 1:
                score_delta = (
                    candidate_scores[0]["normalizedScore"]
                    - candidate_scores[1]["normalizedScore"]
                )
                if score_delta <= thresholds.get("tieDelta", 0):
                    reason_codes.append("tie_break_reasoning_required")
        elif excluded:
            stop_and_confirm = True
            reason_codes.append("no_candidate_after_filters")

        return RoutingResult(
            selected=ranked[0][1] if ranked else None,
            excluded=excluded,
            budget_state=budget_decision.budget_state,
            stop_and_confirm=stop_and_confirm,
            candidate_scores=candidate_scores,
            hard_filters_applied=hard_filters,
            reason_codes=reason_codes,
            confidence=(
                candidate_scores[0]["normalizedScore"] / 100.0
                if candidate_scores
                else 0.0
            ),
        )

    def _exclude_reason(
        self, candidate: dict[str, Any], required_capabilities: list[dict[str, Any]]
    ) -> str | None:
        if candidate.get("disabled"):
            return "disabled"
        provider = candidate["provider"]
        declared = candidate.get("capabilities", {})
        self.capability_registry.merge_declared(provider, declared)
        for requirement in required_capabilities:
            state = self.capability_registry.resolve(
                provider,
                requirement["key"],
                default_state=declared.get(requirement["key"], "unknown"),
            )
            if state == "unsupported":
                return f"unsupported:{requirement['key']}"
            if requirement.get("high_impact") and state != "verified":
                return f"high_impact_not_verified:{requirement['key']}"
        return None

    def _score_candidate(
        self,
        phase: str,
        candidate: dict[str, Any],
        metrics: dict[str, Any],
        budget_decision: BudgetDecision,
    ) -> tuple[float, dict[str, Any]]:
        weights = self._phase_policy(phase).get("weights", PHASE_WEIGHTS.get(phase, {}))
        penalty_weights = self.policy.get("penaltyWeights", {})
        candidate_scores = candidate.get("scores", {})
        total = 0.0
        metric_breakdown: dict[str, Any] = {}
        for metric, weight in weights.items():
            raw_value = candidate_scores.get(metric, metrics.get(metric, "medium"))
            numeric_value = self._score_value(raw_value)
            contribution = weight * numeric_value
            total += contribution
            metric_breakdown[metric] = {
                "value": raw_value,
                "numeric": numeric_value,
                "weight": weight,
                "contribution": contribution,
            }
        penalty_breakdown: dict[str, Any] = {}
        for penalty_name, penalty_weight in penalty_weights.items():
            penalty_value = float(candidate.get("penalties", {}).get(penalty_name, 0.0))
            penalty_contribution = penalty_weight * penalty_value
            total -= penalty_contribution
            penalty_breakdown[penalty_name] = {
                "value": penalty_value,
                "weight": penalty_weight,
                "contribution": penalty_contribution,
            }
        estimated_cost = float(candidate.get("estimated_cost", 0.0))
        total -= estimated_cost
        if budget_decision.reroute_recommended:
            total -= estimated_cost
        total -= float(candidate.get("known_failure_penalty", 0.0))
        return total, {
            "metrics": metric_breakdown,
            "penalties": penalty_breakdown,
            "estimatedCost": estimated_cost,
        }

    def _score_value(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(ORDINAL.get(value, 2))
        return 0.0

    def _phase_policy(self, phase: str) -> dict[str, Any]:
        return self.policy.get("phases", {}).get(phase, {})

    def _build_candidate_scores(
        self,
        phase: str,
        ranked: list[tuple[float, dict[str, Any], dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        if not ranked:
            return []
        max_possible = max(self._max_possible_score(phase), 1.0)
        selected_provider = ranked[0][1]["provider"]
        selected_profile = ranked[0][1].get("profile")
        records: list[dict[str, Any]] = []
        for raw_score, candidate, breakdown in ranked:
            normalized = max(0.0, min(100.0, (raw_score / max_possible) * 100.0))
            records.append(
                {
                    "provider": candidate["provider"],
                    "profile": candidate.get("profile"),
                    "modelRef": candidate.get("modelRef"),
                    "rawScore": round(raw_score, 3),
                    "normalizedScore": round(normalized, 3),
                    "metrics": breakdown["metrics"],
                    "penalties": breakdown["penalties"],
                    "estimatedCost": breakdown["estimatedCost"],
                    "selected": candidate["provider"] == selected_provider
                    and candidate.get("profile") == selected_profile,
                }
            )
        return records

    def _max_possible_score(self, phase: str) -> float:
        weights = self._phase_policy(phase).get("weights", PHASE_WEIGHTS.get(phase, {}))
        return float(sum(float(weight) for weight in weights.values()) * 5.0)
