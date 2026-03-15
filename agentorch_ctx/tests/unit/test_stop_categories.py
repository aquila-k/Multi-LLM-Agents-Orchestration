from __future__ import annotations

import unittest

from agentorch_ctx.runtime.stop_categories import (
    ARTIFACT_CONSISTENCY_FAILURE,
    AUTO_ADVANCE_STOP_CODES,
    BUDGET_STOP,
    MISSING_TOOL_OR_AUTH,
    PLAN_ARTIFACT_INCOMPLETE,
    STEP_INPUT_CONTRACT_FAILED,
    STEP_OUTPUT_CONTRACT_FAILED,
)


class StopCategoriesUnitTest(unittest.TestCase):
    def test_auto_advance_stop_codes_contains_budget_stop(self) -> None:
        self.assertIn(BUDGET_STOP, AUTO_ADVANCE_STOP_CODES)

    def test_auto_advance_stop_codes_is_frozenset(self) -> None:
        self.assertIsInstance(AUTO_ADVANCE_STOP_CODES, frozenset)

    def test_constants_are_strings(self) -> None:
        self.assertIsInstance(MISSING_TOOL_OR_AUTH, str)
        self.assertIsInstance(ARTIFACT_CONSISTENCY_FAILURE, str)
        self.assertIsInstance(PLAN_ARTIFACT_INCOMPLETE, str)
        self.assertIsInstance(STEP_INPUT_CONTRACT_FAILED, str)
        self.assertIsInstance(STEP_OUTPUT_CONTRACT_FAILED, str)

    def test_stop_codes_count(self) -> None:
        self.assertEqual(len(AUTO_ADVANCE_STOP_CODES), 7)


if __name__ == "__main__":
    unittest.main()
