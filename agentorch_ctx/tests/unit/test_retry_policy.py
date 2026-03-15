from __future__ import annotations

import unittest

from agentorch_ctx.runtime.budget_gate import BudgetGate
from agentorch_ctx.runtime.retry_policy import classify_retry_candidate


class RetryPolicyUnitTest(unittest.TestCase):
    def test_cold_stop_without_meaningful_output_is_auto_retryable(self) -> None:
        result = classify_retry_candidate(
            coordination_result_summary={
                "controller_status": "blocked",
                "blocked_reason": "provider_capability_mismatch",
            },
            apply_result=None,
            normalized={"status": "failed_unusable"},
        )
        self.assertTrue(result["auto_retry_eligible"])
        self.assertEqual(result["retry_condition"], "cold_stop_no_output")
        self.assertTrue(result["preserve_existing"])

    def test_meaningful_output_is_not_auto_retryable(self) -> None:
        result = classify_retry_candidate(
            coordination_result_summary={
                "controller_status": "blocked",
                "blocked_reason": "blocked_for_scope",
            },
            apply_result=None,
            normalized={"status": "succeeded"},
        )
        self.assertFalse(result["auto_retry_eligible"])
        self.assertEqual(
            result["retry_condition"], "output_contract_violation_meaningful"
        )
        self.assertTrue(result["preserve_existing"])

    def test_ambiguity_block_requires_human_decision(self) -> None:
        result = classify_retry_candidate(
            coordination_result_summary={
                "controller_status": "blocked",
                "blocked_reason": "task_ambiguity",
            },
            apply_result=None,
            normalized=None,
        )
        self.assertFalse(result["auto_retry_eligible"])
        self.assertEqual(result["retry_condition"], "ambiguity_or_approval")
        self.assertEqual(result["reason"], "human_decision_required")
        self.assertTrue(result["preserve_existing"])

    def test_already_applied_is_not_retryable(self) -> None:
        result = classify_retry_candidate(
            coordination_result_summary={
                "controller_status": "running",
                "blocked_reason": "",
            },
            apply_result={"result": "applied"},
            normalized={"status": "succeeded"},
        )
        self.assertFalse(result["auto_retry_eligible"])
        self.assertEqual(result["retry_condition"], "already_applied")
        self.assertEqual(result["reason"], "already_applied")
        self.assertTrue(result["preserve_existing"])

    def test_budget_gate_loop_iteration_stop_on_hard_cap(self) -> None:
        decision = BudgetGate().evaluate_loop_iteration(
            budget={"hardCap": 10, "consumed": 7},
            current_iteration=1,
            max_loops=4,
            estimated_cost_per_loop=1.5,
        )
        self.assertEqual(decision.budget_state, "budget_stop")
        self.assertTrue(decision.stop_required)
        self.assertFalse(decision.reroute_recommended)

    def test_evaluate_loop_iteration_budget_stop(self) -> None:
        result = BudgetGate().evaluate_loop_iteration(
            budget={"hardCap": 10.0, "consumed": 8.0},
            current_iteration=1,
            max_loops=3,
            estimated_cost_per_loop=2.0,
        )

        self.assertTrue(result.stop_required)
        self.assertEqual(result.budget_state, "budget_stop")

    def test_budget_gate_loop_iteration_healthy_under_cap(self) -> None:
        decision = BudgetGate().evaluate_loop_iteration(
            budget={"hardCap": 20, "consumed": 4, "estimatedNextCost": 1},
            current_iteration=1,
            max_loops=4,
            estimated_cost_per_loop=1.0,
        )
        self.assertEqual(decision.budget_state, "healthy")
        self.assertFalse(decision.stop_required)
        self.assertFalse(decision.reroute_recommended)

    def test_escalation_requires_approval_when_flag_true(self) -> None:
        decision = BudgetGate().evaluate_escalation(
            current_provider="gemini",
            target_provider="copilot",
            budget={},
            escalation_requires_approval=True,
            reroute_candidates=["codex-mini", "gemini-flash"],
        )
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_approval)
        self.assertEqual(decision.reason, "escalation_needs_approval")
        self.assertEqual(decision.reroute_candidates, ["codex-mini", "gemini-flash"])

    def test_escalation_allowed_when_decision_present(self) -> None:
        decision = BudgetGate().evaluate_escalation(
            current_provider="gemini",
            target_provider="copilot",
            budget={
                "hardCap": 10,
                "consumed": 6,
                "estimatedNextCost": 2,
                "escalationDecisionRef": "approval/escalation-123",
            },
            escalation_requires_approval=True,
        )
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_approval)
        self.assertEqual(decision.reason, "allowed")
        self.assertEqual(decision.reroute_candidates, [])


if __name__ == "__main__":
    unittest.main()
