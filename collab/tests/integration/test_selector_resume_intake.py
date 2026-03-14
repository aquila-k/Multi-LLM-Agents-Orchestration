from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collab.runtime.claude_code_skill import ClaudeCodeSkill
from collab.runtime.phase_runner import PhaseRunner


class SelectorResumeIntakeIntegrationTest(unittest.TestCase):
    def test_resume_request_without_existing_task_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resume.json"
            source.write_text(
                json.dumps({"summary": "Resume missing task id"}), encoding="utf-8"
            )

            with self.assertRaises(ValueError):
                ClaudeCodeSkill(root_dir=root).dispatch(
                    source_path=source,
                    workflow_intent="resume",
                    source_kind="json",
                    selectors={"phase": "impl", "step": "I0_analyze"},
                    operator_context={"summary": "missing task id"},
                )

    def test_resume_request_reuses_existing_task_root_and_updates_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = ClaudeCodeSkill(root_dir=root)

            initial_source = root / "plan.md"
            initial_source.write_text("# Plan runtime\n", encoding="utf-8")
            initial = skill.dispatch(
                source_path=initial_source,
                workflow_intent="plan",
                source_kind="markdown",
                operator_context={"summary": "initial task"},
            )
            phase_result = PhaseRunner(root).run(request_path=initial.request_path)
            self.assertEqual(phase_result.controller_status, "partial")

            resume_source = root / "resume.json"
            resume_source.write_text(
                json.dumps(
                    {
                        "task_id": initial.task_id,
                        "summary": "Resume existing plan task",
                    }
                ),
                encoding="utf-8",
            )
            result = skill.dispatch(
                source_path=resume_source,
                workflow_intent="resume",
                source_kind="json",
                selectors={
                    "phase": "plan",
                    "strategy": "COLLAB_PLAN_FULL",
                    "step": "P0_survey",
                    "resume_from": "cursor-001",
                },
                operator_context={"summary": "resume existing task"},
            )

            request = json.loads(result.request_path.read_text(encoding="utf-8"))
            self.assertEqual(request["workflow_intent"], "resume")
            self.assertEqual(request["task_id"], initial.task_id)
            self.assertEqual(request["selectors"]["phase"], "plan")
            self.assertEqual(request["selectors"]["resume_from"], "cursor-001")
            self.assertIn(initial.task_id, request["artifacts"]["task_root"])

            controller_state = json.loads(
                result.controller_state_path.read_text(encoding="utf-8")
            )
            self.assertEqual(controller_state["current_status"], "partial")
            self.assertFalse(result.stop_and_confirm)

            resume_cursor = json.loads(
                (result.controller_state_path.parent / "resume-cursor.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(resume_cursor["phase"], "plan")
            self.assertEqual(resume_cursor["resume_from"], "cursor-001")
            self.assertGreaterEqual(int(resume_cursor["run"]), 2)


if __name__ == "__main__":
    unittest.main()
