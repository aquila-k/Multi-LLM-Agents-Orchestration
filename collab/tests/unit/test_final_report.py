from __future__ import annotations

import unittest

from collab.runtime.final_report import build_final_report


class FinalReportUnitTest(unittest.TestCase):
    def test_completed_steps_populate_what_was_done(self) -> None:
        report = build_final_report(
            task_id="task-001",
            phase="plan",
            strategy_id="COLLAB_PLAN_FULL",
            step_records=[
                {"step": "R0_repo_survey", "controllerStatus": "partial"},
                {"step": "FINAL_plan", "controllerStatus": "partial"},
            ],
        )
        self.assertEqual(report["summary"]["completedSteps"], 2)
        self.assertIn("R0_repo_survey", report["whatWasDone"])
        self.assertIn("FINAL_plan", report["whatWasDone"])

    def test_blocked_step_populates_unresolved_items_and_resume_action(self) -> None:
        report = build_final_report(
            task_id="task-002",
            phase="review",
            strategy_id="COLLAB_REVIEW_PRESET_STRICT",
            step_records=[
                {"step": "R0_strict_review", "controllerStatus": "blocked"},
            ],
            blocked_reason="blocked_for_approval",
            controller_status="blocked",
        )
        self.assertEqual(report["controllerStatus"], "blocked")
        self.assertTrue(report["unresolvedItems"])
        self.assertTrue(
            any("Resume review" in action for action in report["nextUserActions"])
        )

    def test_plan_phase_includes_plan_artifact_refs(self) -> None:
        report = build_final_report(
            task_id="task-003",
            phase="plan",
            strategy_id="COLLAB_PLAN_THOROUGH",
            step_records=[{"step": "P3_final_plan", "controllerStatus": "partial"}],
            plan_artifact_refs={
                "planRef": "/tmp/plan.json",
                "checklistRef": "/tmp/checklist.json",
                "deferredItemsRef": "",
            },
        )
        self.assertEqual(report["planArtifactRefs"]["planRef"], "/tmp/plan.json")
        self.assertEqual(
            report["planArtifactRefs"]["checklistRef"], "/tmp/checklist.json"
        )


if __name__ == "__main__":
    unittest.main()
