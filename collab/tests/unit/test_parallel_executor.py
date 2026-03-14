from __future__ import annotations

import unittest

from collab.runtime.parallel_executor import (
    ParallelStepResult,
    execute_steps_parallel,
    is_consolidation_step,
    is_parallel_step,
    merge_parallel_results,
)


class ParallelExecutorUnitTest(unittest.TestCase):
    def test_single_step_returns_single_result(self) -> None:
        results = execute_steps_parallel(
            step_defs=[{"id": "S1"}],
            execute_fn=lambda step: {
                "step": step["id"],
                "success": True,
                "output": {"ok": True},
            },
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].step_id, "S1")
        self.assertTrue(results[0].success)

    def test_two_successful_steps_return_two_results(self) -> None:
        def execute_fn(step: dict[str, object]) -> dict[str, object]:
            return {"step": step["id"], "success": True, "output": {"id": step["id"]}}

        results = execute_steps_parallel(
            step_defs=[{"id": "A"}, {"id": "B"}],
            execute_fn=execute_fn,
            max_workers=2,
        )
        self.assertEqual(len(results), 2)
        self.assertEqual({result.step_id for result in results}, {"A", "B"})
        self.assertTrue(all(result.success for result in results))

    def test_failing_step_returns_failed_result(self) -> None:
        def execute_fn(step: dict[str, object]) -> dict[str, object]:
            if step["id"] == "bad":
                raise RuntimeError("boom")
            return {"step": step["id"], "success": True, "output": {}}

        results = execute_steps_parallel(
            step_defs=[{"id": "bad"}],
            execute_fn=execute_fn,
        )
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("boom", results[0].error)

    def test_is_parallel_step_true_when_flag_set(self) -> None:
        self.assertTrue(is_parallel_step({"id": "R0", "parallel": True}))

    def test_is_consolidation_step_true_for_consolidate_suffix(self) -> None:
        self.assertTrue(is_consolidation_step({"id": "P2_consolidate"}))

    def test_is_consolidation_step_false_for_normal_step(self) -> None:
        self.assertFalse(is_consolidation_step({"id": "P0_plan_outline"}))

    def test_is_consolidation_step_true_for_explicit_flag(self) -> None:
        self.assertTrue(is_consolidation_step({"id": "merge", "consolidate": True}))

    def test_merge_parallel_results_all_success(self) -> None:
        results = [
            ParallelStepResult(
                step_id="A", success=True, output={"key": "a"}, error=""
            ),
            ParallelStepResult(
                step_id="B", success=True, output={"key": "b"}, error=""
            ),
        ]
        merged = merge_parallel_results(results)
        self.assertEqual(merged["mergeStatus"], "complete")
        self.assertEqual(merged["workerCount"], 2)
        self.assertEqual(merged["successCount"], 2)
        self.assertEqual(merged["failedCount"], 0)
        self.assertEqual(len(merged["workers"]), 2)

    def test_merge_parallel_results_partial_failure(self) -> None:
        results = [
            ParallelStepResult(step_id="A", success=True, output={}, error=""),
            ParallelStepResult(step_id="B", success=False, output={}, error="boom"),
        ]
        merged = merge_parallel_results(results)
        self.assertEqual(merged["mergeStatus"], "partial")
        self.assertEqual(merged["successCount"], 1)
        self.assertEqual(merged["failedCount"], 1)
        self.assertEqual(merged["workers"][1]["error"], "boom")

    def test_merge_parallel_results_empty(self) -> None:
        merged = merge_parallel_results([])
        self.assertEqual(merged["mergeStatus"], "complete")
        self.assertEqual(merged["workerCount"], 0)


if __name__ == "__main__":
    unittest.main()
