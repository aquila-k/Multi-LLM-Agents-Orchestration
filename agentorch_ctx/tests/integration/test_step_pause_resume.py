from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentorch_ctx.runtime.claude_code_skill import ClaudeCodeSkill
from agentorch_ctx.runtime.task_runner import TaskRunner


class StepPauseResumeIntegrationTest(unittest.TestCase):
    def test_pause_and_resume_updates_state_and_audit_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text("# Plan task\n", encoding="utf-8")

            skill = ClaudeCodeSkill(root_dir=root)
            result = skill.dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                operator_context={"summary": "pause resume test"},
            )

            runner = TaskRunner(root)
            runner.start_phase(
                task_id=result.task_id, phase="plan", step="survey", strategy="default"
            )
            paused = runner.pause_step(
                task_id=result.task_id,
                phase="plan",
                step="survey",
                reason="needs_clarification",
                resume_from="survey-clarify",
            )
            self.assertEqual(paused["current_status"], "blocked")
            self.assertEqual(
                paused["resume_selectors"]["resume_from"], "survey-clarify"
            )

            resumed = runner.resume(task_id=result.task_id)
            self.assertEqual(resumed["current_status"], "running")

            completed = runner.complete_step(
                task_id=result.task_id,
                phase="plan",
                step="survey",
                artifact_ref="artifact-001",
                partial=True,
            )
            self.assertEqual(completed["current_status"], "partial")

            known_information = json.loads(
                (
                    root
                    / ".agentorch"
                    / "state"
                    / "tasks"
                    / result.task_id
                    / "known-information.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                known_information["latest_phase_summary"]["artifact_ref"],
                "artifact-001",
            )
            manifest = json.loads(
                (
                    root
                    / ".agentorch"
                    / "artifacts"
                    / "tasks"
                    / result.task_id
                    / "manifests"
                    / "manifest.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["payload"]["controllerStatus"], "partial")
            self.assertEqual(
                manifest["payload"]["latestPhaseSummary"]["artifactRef"], "artifact-001"
            )
            events_path = (
                root
                / ".agentorch"
                / "artifacts"
                / "tasks"
                / result.task_id
                / "events.jsonl"
            )
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [event["event_type"] for event in events],
                ["phase_started", "step_paused", "task_resumed", "step_completed"],
            )

    def test_complete_step_without_partial_keeps_task_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text("# Implement task\n", encoding="utf-8")

            skill = ClaudeCodeSkill(root_dir=root)
            result = skill.dispatch(
                source_path=source,
                workflow_intent="impl",
                source_kind="markdown",
                operator_context={"summary": "non partial completion"},
            )

            runner = TaskRunner(root)
            completed = runner.complete_step(
                task_id=result.task_id,
                phase="impl",
                step="apply",
                artifact_ref="artifact-002",
                partial=False,
            )

            self.assertEqual(completed["current_status"], "running")
            self.assertIn("artifact-002", completed["last_successful_artifact_refs"])

    def test_pause_step_persists_shell_digest_and_updates_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text("# Plan task\n", encoding="utf-8")

            skill = ClaudeCodeSkill(root_dir=root)
            result = skill.dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                operator_context={"summary": "pause digest"},
            )

            runner = TaskRunner(root)
            paused = runner.pause_step(
                task_id=result.task_id,
                phase="plan",
                step="survey",
                reason="needs_clarification",
                resume_from="survey-clarify",
            )

            self.assertEqual(paused["current_status"], "blocked")
            self.assertEqual(len(paused["latest_shell_digest_refs"]), 2)
            latest_digest = Path(paused["latest_shell_digest_refs"][-1])
            self.assertTrue(latest_digest.exists())

            known_information = json.loads(
                (
                    root
                    / ".agentorch"
                    / "state"
                    / "tasks"
                    / result.task_id
                    / "known-information.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                known_information["latest_shell_digestion_summary"]["shell_digest_ref"],
                latest_digest.as_posix(),
            )
            resume_cursor = json.loads(
                (
                    root
                    / ".agentorch"
                    / "state"
                    / "tasks"
                    / result.task_id
                    / "resume-cursor.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(resume_cursor["resume_from"], "survey-clarify")

    def test_resume_override_conflict_creates_confirmation_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text("# Resume task\n", encoding="utf-8")

            skill = ClaudeCodeSkill(root_dir=root)
            result = skill.dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                operator_context={"summary": "resume override conflict"},
            )

            runner = TaskRunner(root)
            runner.pause_step(
                task_id=result.task_id,
                phase="plan",
                step="survey",
                reason="needs_clarification",
                resume_from="survey",
            )
            resumed = runner.resume(
                task_id=result.task_id,
                selectors={"phase": "impl", "step": "apply"},
            )

            self.assertEqual(resumed["current_status"], "blocked")
            decisions_path = (
                root
                / ".agentorch"
                / "artifacts"
                / "tasks"
                / result.task_id
                / "decisions.jsonl"
            )
            decisions = [
                json.loads(line)
                for line in decisions_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(decisions[-1]["decision_type"], "resume_override")
            pause_confirm = (
                root
                / ".agentorch"
                / "artifacts"
                / "tasks"
                / result.task_id
                / "pause-confirm"
                / "pause-confirm-resume-override-plan-survey.json"
            )
            self.assertTrue(pause_confirm.exists())

    def test_strategy_change_from_intake_resume_remains_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text("# Resume task\n", encoding="utf-8")

            skill = ClaudeCodeSkill(root_dir=root)
            result = skill.dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                constraints={"approvals_required": ["apply"]},
                operator_context={"summary": "intake strategy override"},
            )
            self.assertTrue(result.stop_and_confirm)

            resumed = TaskRunner(root).resume(
                task_id=result.task_id,
                approval_outcome="approved_continue",
                selectors={"strategy": "COLLAB_PLAN_QUESTIONS_ONLY"},
            )
            self.assertEqual(resumed["current_status"], "running")
            self.assertEqual(resumed["blocked_reason"], "")

    def test_partial_resume_override_blocks_for_strategy_change_redo(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text("# Review task\n", encoding="utf-8")

            skill = ClaudeCodeSkill(root_dir=root)
            result = skill.dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                operator_context={"summary": "partial resume override"},
            )

            runner = TaskRunner(root)
            runner.complete_step(
                task_id=result.task_id,
                phase="plan",
                step="survey",
                artifact_ref="artifact-003",
                partial=True,
            )
            resumed = runner.resume(
                task_id=result.task_id,
                selectors={
                    "phase": "review",
                    "step": "R0_standard_review",
                    "strategy": "COLLAB_REVIEW_PRESET_STANDARD",
                    "resume_from": "review-start",
                },
            )

            self.assertEqual(resumed["current_status"], "blocked")
            self.assertEqual(
                resumed["blocked_reason"], "strategy_changed_requires_redo"
            )
            self.assertEqual(resumed["active_phase"], "review")
            self.assertEqual(
                resumed["active_strategy"], "COLLAB_REVIEW_PRESET_STANDARD"
            )

            resume_cursor = json.loads(
                (
                    root
                    / ".agentorch"
                    / "state"
                    / "tasks"
                    / result.task_id
                    / "resume-cursor.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(resume_cursor["phase"], "review")
            self.assertEqual(resume_cursor["resume_from"], "R0_standard_review")

            strategy_switch = (
                root
                / ".agentorch"
                / "artifacts"
                / "tasks"
                / result.task_id
                / "strategy-switches"
                / "strategy-switch-plan-review.json"
            )
            self.assertTrue(strategy_switch.exists())


if __name__ == "__main__":
    unittest.main()
