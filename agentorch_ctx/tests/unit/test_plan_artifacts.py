from __future__ import annotations

import unittest

from agentorch_ctx.runtime.plan_artifacts import (
    extract_plan_artifacts,
    plan_artifact_scope_summary,
    validate_plan_artifacts,
)


class PlanArtifactsUnitTest(unittest.TestCase):
    def test_extracts_json_block_with_implementation_steps(self) -> None:
        normalized = {"payload": {"content": """
```json
{
  "summary": "Implement runtime changes",
  "implementationSteps": [
    {"id": "S01", "description": "Update phase runner", "targetFiles": ["agentorch_ctx/runtime/phase_runner.py"]},
    "Add tests"
  ],
  "targetPaths": ["agentorch_ctx/runtime/phase_runner.py", "agentorch_ctx/tests/"],
  "constraints": {"dangerousOperations": ["rm -rf"]},
  "checklist": ["Add integration tests"]
}
```
"""}}

        plan, checklist, deferred = extract_plan_artifacts(
            task_id="task-1",
            step_id="FINAL_plan",
            normalized=normalized,
        )

        self.assertEqual(plan["summary"], "Implement runtime changes")
        self.assertEqual(plan["implementationSteps"][0]["id"], "S01")
        self.assertEqual(plan["implementationSteps"][1]["description"], "Add tests")
        self.assertEqual(
            plan["targetPaths"][0], "agentorch_ctx/runtime/phase_runner.py"
        )
        self.assertEqual(checklist["items"][0]["description"], "Add integration tests")
        self.assertIsNone(deferred)

    def test_synthesizes_steps_from_markdown_numbered_list(self) -> None:
        normalized = {"payload": {"content": """
# Canonical Plan
1. Update agentorch_ctx/runtime/phase_runner.py
2) Add agentorch_ctx/tests/unit/test_plan_artifacts.py
- [ ] verify manifests
"""}}

        plan, checklist, deferred = extract_plan_artifacts(
            task_id="task-2",
            step_id="FINAL_plan",
            normalized=normalized,
        )

        self.assertEqual(plan["summary"], "Canonical Plan")
        self.assertEqual(len(plan["implementationSteps"]), 2)
        self.assertEqual(
            plan["implementationSteps"][0]["description"],
            "Update agentorch_ctx/runtime/phase_runner.py",
        )
        self.assertEqual(checklist["items"][0]["description"], "verify manifests")
        self.assertIsNone(deferred)

    def test_empty_content_still_produces_valid_minimal_artifacts(self) -> None:
        plan, checklist, deferred = extract_plan_artifacts(
            task_id="task-3",
            step_id="FINAL_plan",
            normalized={"payload": {"content": ""}},
        )

        self.assertEqual(plan["schemaVersion"], "1.0.0")
        self.assertEqual(plan["taskId"], "task-3")
        self.assertEqual(plan["phase"], "plan")
        self.assertIn("implementationSteps", plan)
        self.assertIn("targetPaths", plan)
        self.assertEqual(checklist["schemaVersion"], "1.0.0")
        self.assertEqual(checklist["phase"], "plan")
        self.assertIsNone(deferred)

    def test_extracts_deferred_items(self) -> None:
        normalized = {"payload": {"content": """
```json
{
  "summary": "Plan with deferred",
  "implementationSteps": ["Do immediate work"],
  "checklist": ["Immediate checklist item"],
  "deferredItems": [
    {
      "id": "D001",
      "description": "Handle migration later",
      "reason": "outside current scope",
      "impact": "medium",
      "expectedResolutionPhase": "harden"
    }
  ]
}
```
"""}}

        _, _, deferred = extract_plan_artifacts(
            task_id="task-4",
            step_id="FINAL_plan",
            normalized=normalized,
        )

        self.assertIsNotNone(deferred)
        assert deferred is not None
        self.assertEqual(deferred["items"][0]["id"], "D001")
        self.assertEqual(deferred["items"][0]["reason"], "outside current scope")
        self.assertEqual(
            deferred["items"][0]["expectedResolutionPhase"],
            "harden",
        )

    def test_extracts_plan_from_normalized_report_summary(self) -> None:
        normalized = {
            "payload": {
                "reports": [
                    {
                        "id": "report-1",
                        "summary": """
```json
{
  "summary": "Plan from normalized report",
  "implementationSteps": [{"id": "S01", "description": "Inspect runtime"}],
  "targetPaths": ["agentorch_ctx/runtime/phase_runner.py"],
  "checklist": ["Confirm emitted artifacts"]
}
```
""",
                    }
                ]
            }
        }

        plan, checklist, deferred = extract_plan_artifacts(
            task_id="task-5",
            step_id="FINAL_plan",
            normalized=normalized,
        )

        self.assertEqual(plan["summary"], "Plan from normalized report")
        self.assertEqual(
            plan["targetPaths"][0], "agentorch_ctx/runtime/phase_runner.py"
        )
        self.assertEqual(
            checklist["items"][0]["description"], "Confirm emitted artifacts"
        )
        self.assertIsNone(deferred)


class ValidatePlanArtifactsTest(unittest.TestCase):
    """Tests for validate_plan_artifacts()."""

    def _make_plan(
        self,
        steps: list | None = None,
        target_paths: list | None = None,
        constraints: dict | None = None,
    ) -> dict:
        return {
            "schemaVersion": "1.0.0",
            "taskId": "t1",
            "phase": "plan",
            "stepId": "FINAL_plan",
            "summary": "test plan",
            "implementationSteps": (
                steps if steps is not None else [{"id": "S01", "description": "step"}]
            ),
            "targetPaths": target_paths if target_paths is not None else ["src/"],
            "constraints": constraints if constraints is not None else {},
            "ambiguitiesResolved": [],
            "ambiguitiesDeferred": [],
            "extractedFrom": "t1:plan:FINAL_plan",
        }

    def _make_checklist(self, items: list | None = None) -> dict:
        return {
            "schemaVersion": "1.0.0",
            "taskId": "t1",
            "phase": "plan",
            "items": (
                items
                if items is not None
                else [{"id": "C001", "description": "check this"}]
            ),
            "extractedFrom": "t1:plan:FINAL_plan",
        }

    def test_validate_plan_artifacts_empty_checklist_fails(self) -> None:
        plan = self._make_plan()
        checklist = self._make_checklist(items=[])
        ok, reasons = validate_plan_artifacts(plan, checklist, None)
        self.assertFalse(ok)
        self.assertTrue(any("checklist" in r for r in reasons))

    def test_validate_plan_artifacts_empty_steps_fails(self) -> None:
        plan = self._make_plan(steps=[])
        checklist = self._make_checklist()
        ok, reasons = validate_plan_artifacts(plan, checklist, None)
        self.assertFalse(ok)
        self.assertTrue(any("implementationSteps" in r for r in reasons))

    def test_validate_plan_artifacts_valid_passes(self) -> None:
        plan = self._make_plan(
            steps=[{"id": "S01", "description": "do something"}],
            target_paths=["src/"],
        )
        checklist = self._make_checklist(
            items=[{"id": "C001", "description": "verify it"}]
        )
        ok, reasons = validate_plan_artifacts(plan, checklist, None)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_validate_plan_artifacts_no_scope_fails(self) -> None:
        """Both targetPaths and constraints empty → validation fails."""
        plan = self._make_plan(target_paths=[], constraints={})
        checklist = self._make_checklist()
        ok, reasons = validate_plan_artifacts(plan, checklist, None)
        self.assertFalse(ok)
        self.assertTrue(
            any("scope" in r.lower() or "targetPaths" in r for r in reasons)
        )

    def test_validate_plan_artifacts_constraints_only_scope_passes(self) -> None:
        """No targetPaths but non-empty constraints is sufficient scope."""
        plan = self._make_plan(
            target_paths=[],
            constraints={"dangerousOperations": ["rm -rf"]},
        )
        checklist = self._make_checklist()
        ok, reasons = validate_plan_artifacts(plan, checklist, None)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])


class PlanArtifactScopeSummaryTest(unittest.TestCase):
    """Tests for plan_artifact_scope_summary()."""

    def test_scope_summary_correct(self) -> None:
        plan = {
            "implementationSteps": [
                {"id": "S01", "description": "step one"},
                {"id": "S02", "description": "step two"},
            ],
            "targetPaths": ["src/", "tests/"],
        }
        checklist = {
            "items": [
                {"id": "C001", "description": "check a"},
                {"id": "C002", "description": "check b"},
                {"id": "C003", "description": "check c"},
            ]
        }
        deferred = {"items": [{"id": "D001", "description": "later"}]}

        summary = plan_artifact_scope_summary(plan, checklist, deferred)

        self.assertEqual(summary["totalSteps"], 2)
        self.assertEqual(summary["totalChecklistItems"], 3)
        self.assertTrue(summary["hasTargetPaths"])
        self.assertTrue(summary["hasDeferredItems"])

    def test_scope_summary_no_deferred(self) -> None:
        plan = {
            "implementationSteps": [{"id": "S01", "description": "x"}],
            "targetPaths": [],
        }
        checklist = {"items": []}
        summary = plan_artifact_scope_summary(plan, checklist, None)

        self.assertEqual(summary["totalSteps"], 1)
        self.assertEqual(summary["totalChecklistItems"], 0)
        self.assertFalse(summary["hasTargetPaths"])
        self.assertFalse(summary["hasDeferredItems"])


if __name__ == "__main__":
    unittest.main()
