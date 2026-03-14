from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collab.runtime.claude_code_skill import ClaudeCodeSkill
from collab.runtime.condensation import condense_context
from collab.runtime.redaction import redact_text
from collab.runtime.renderers.diagnostics import render_shell_digest
from collab.runtime.shell_digest import derive_shell_digest, ingest_shell_digest
from collab.runtime.task_runner import TaskRunner


class ShellRedigestionResumeRegressionTest(unittest.TestCase):
    def test_redigested_shell_summary_preserves_resume_signal_after_redaction(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "task.md"
            source.write_text("# Implement runtime\n", encoding="utf-8")

            skill = ClaudeCodeSkill(root_dir=root)
            dispatch = skill.dispatch(
                source_path=source,
                workflow_intent="impl",
                source_kind="markdown",
                selectors={
                    "phase": "impl",
                    "step": "apply-gate",
                    "resume_from": "cursor-99",
                },
                constraints={"approvals_required": ["apply"]},
                operator_context={"summary": "regression"},
            )
            self.assertTrue(dispatch.stop_and_confirm)

            shell_summary = (
                "STOP_AND_CONFIRM before phase=impl step=apply-gate "
                "because token sk-secretkey12345678 was observed"
            )
            redacted = redact_text(shell_summary)
            self.assertNotIn("sk-secretkey12345678", redacted["redacted_text"])

            digest = derive_shell_digest(
                task_id=dispatch.task_id,
                concise_summary=redacted["redacted_text"],
                execution_record_ref="exec-1",
            )
            self.assertEqual(
                render_shell_digest(digest),
                "status=blocked | stop=approval required | resume=apply-gate",
            )

            known_information_path = (
                root
                / "collab"
                / "state"
                / "tasks"
                / dispatch.task_id
                / "known-information.json"
            )
            known_information = json.loads(
                known_information_path.read_text(encoding="utf-8")
            )
            updated_known_information = ingest_shell_digest(
                known_information=known_information,
                shell_digest=digest,
            )
            known_information_path.write_text(
                json.dumps(updated_known_information, indent=2, ensure_ascii=True)
                + "\n",
                encoding="utf-8",
            )

            condensation = condense_context(
                {
                    "current_task_intent": updated_known_information[
                        "user_goal_summary"
                    ],
                    "user_added_instructions": ["fail closed"],
                    "prior_decisions": ["approval required"],
                    "active_constraints": updated_known_information[
                        "confirmed_constraints"
                    ],
                    "required_outputs": ["safe resume"],
                    "stop_conditions": updated_known_information["unresolved_blockers"],
                    "unresolved_questions": ["who approves?"],
                    "historical_narrative": ["verbose history"],
                    "references": [dispatch.request_path.as_posix()],
                },
                current_step="resume",
            )
            self.assertEqual(condensation["status"], "ready")
            self.assertEqual(
                condensation["dropped"][0]["category"], "historical_narrative"
            )

            runner = TaskRunner(root)
            resumed = runner.resume(
                task_id=dispatch.task_id,
                approval_outcome="approved_continue",
                approval_marker="approval-xyz",
            )
            self.assertEqual(resumed["current_status"], "running")
            reloaded_known_information = json.loads(
                known_information_path.read_text(encoding="utf-8")
            )
            self.assertIn(
                "<REDACTED:OPENAI_KEY>",
                reloaded_known_information["latest_shell_digestion_summary"]["summary"],
            )


if __name__ == "__main__":
    unittest.main()
