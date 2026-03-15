from __future__ import annotations

import unittest

from agentorch_ctx.runtime.review_gate import (
    ReviewGateResult,
    build_loop_state,
    evaluate_review_gate,
    should_continue_loop,
)


class ReviewGateUnitTest(unittest.TestCase):
    def test_gate_allows_completion_when_no_findings(self) -> None:
        result = evaluate_review_gate({"findings": []})

        self.assertTrue(result.can_complete)
        self.assertFalse(result.blocking_found)
        self.assertEqual(result.fixable_operations, [])
        self.assertEqual(result.summary["total"], 0)
        self.assertEqual(result.blocked_reason, "")

    def test_gate_blocks_on_critical_without_fixes(self) -> None:
        result = evaluate_review_gate(
            {
                "findings": [
                    {"id": "F1", "severity": "Critical", "description": "RCE risk"}
                ]
            }
        )

        self.assertFalse(result.can_complete)
        self.assertTrue(result.blocking_found)
        self.assertEqual(result.fixable_operations, [])
        self.assertEqual(result.summary["blocking_count"], 1)
        self.assertEqual(result.blocked_reason, "review_blocking_findings")

    def test_gate_collects_fixable_operations_from_high_findings(self) -> None:
        ops = [{"operation_id": "fix-1"}, {"operation_id": "fix-2"}]
        result = evaluate_review_gate(
            {
                "payload": {
                    "findings": [
                        {
                            "id": "F2",
                            "severity": "High",
                            "description": "Path traversal",
                            "fixable": True,
                            "fix_operations": ops,
                        }
                    ]
                }
            }
        )

        self.assertFalse(result.can_complete)
        self.assertTrue(result.blocking_found)
        self.assertEqual(result.fixable_operations, ops)
        self.assertEqual(result.summary["blocking_count"], 1)
        self.assertEqual(result.blocked_reason, "review_blocking_findings")

    def test_gate_allows_low_mid_findings(self) -> None:
        result = evaluate_review_gate(
            {
                "findings": [
                    {"severity": "Low", "description": "Naming cleanup"},
                    {"severity": "Mid", "description": "Refactor suggestion"},
                ]
            }
        )

        self.assertTrue(result.can_complete)
        self.assertFalse(result.blocking_found)
        self.assertEqual(result.summary["blocking_count"], 0)

    def test_should_continue_loop_blocking_within_cap(self) -> None:
        gate_result = ReviewGateResult(
            can_complete=False,
            blocking_found=True,
            fixable_operations=[{"operation_id": "fix-1"}],
            findings=[],
            summary={},
            blocked_reason="review_blocking_findings",
        )

        self.assertEqual(
            should_continue_loop(
                gate_result,
                {"currentIteration": 1, "maxLoops": 3, "blockersResolvedCount": 0},
            ),
            (True, "blocking_found"),
        )

    def test_should_continue_loop_cap_reached(self) -> None:
        gate_result = ReviewGateResult(
            can_complete=False,
            blocking_found=True,
            fixable_operations=[{"operation_id": "fix-1"}],
            findings=[],
            summary={},
            blocked_reason="review_blocking_findings",
        )

        self.assertEqual(
            should_continue_loop(
                gate_result,
                {"currentIteration": 3, "maxLoops": 3, "blockersResolvedCount": 1},
            ),
            (False, "loop_cap_reached"),
        )

    def test_should_continue_loop_cap_reached_with_snake_case_state(self) -> None:
        gate_result = ReviewGateResult(
            can_complete=False,
            blocking_found=True,
            fixable_operations=[{"operation_id": "op1"}],
            findings=[{"severity": "blocking"}],
            summary={},
            blocked_reason="review_blocking_findings",
        )

        cont, reason = should_continue_loop(
            gate_result,
            {"current_iteration": 3, "max_loops": 3},
        )

        self.assertFalse(cont)
        self.assertEqual(reason, "loop_cap_reached")

    def test_should_continue_loop_continues_when_blocking(self) -> None:
        gate_result = ReviewGateResult(
            can_complete=False,
            blocking_found=True,
            fixable_operations=[{"operation_id": "op1"}],
            findings=[{"severity": "blocking"}],
            summary={},
            blocked_reason="review_blocking_findings",
        )

        cont, reason = should_continue_loop(
            gate_result,
            {"current_iteration": 1, "max_loops": 3},
        )

        self.assertTrue(cont)
        self.assertEqual(reason, "blocking_found")

    def test_should_continue_loop_no_blockers(self) -> None:
        gate_result = ReviewGateResult(
            can_complete=True,
            blocking_found=False,
            fixable_operations=[],
            findings=[],
            summary={},
            blocked_reason="",
        )

        self.assertEqual(
            should_continue_loop(
                gate_result,
                {"currentIteration": 0, "maxLoops": 3, "blockersResolvedCount": 0},
            ),
            (False, "blocking_cleared"),
        )

    def test_should_continue_loop_no_fixable_ops(self) -> None:
        gate_result = ReviewGateResult(
            can_complete=False,
            blocking_found=True,
            fixable_operations=[],
            findings=[],
            summary={},
            blocked_reason="review_blocking_findings",
        )

        self.assertEqual(
            should_continue_loop(
                gate_result,
                {"currentIteration": 1, "maxLoops": 3, "blockersResolvedCount": 0},
            ),
            (False, "no_fixable_operations"),
        )

    def test_build_loop_state_correct(self) -> None:
        self.assertEqual(
            build_loop_state(current_iteration=2, max_loops=5, blockers_resolved=3),
            {
                "currentIteration": 2,
                "maxLoops": 5,
                "blockersResolvedCount": 3,
                "status": "running",
            },
        )


if __name__ == "__main__":
    unittest.main()
