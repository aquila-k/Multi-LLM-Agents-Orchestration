from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentorch_ctx.runtime.claude_code_skill import ClaudeCodeSkill
from agentorch_ctx.runtime.pathing import task_artifacts_dir
from agentorch_ctx.runtime.phase_runner import PhaseRunner


class ResumeFromStateIntegrationTest(unittest.TestCase):
    def test_resume_request_reuses_existing_task_and_drives_provider_resume(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text("# Implement runtime\n", encoding="utf-8")
            target = root / "src" / "hello.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")

            skill = ClaudeCodeSkill(root_dir=root)
            initial = skill.dispatch(
                source_path=source,
                workflow_intent="impl",
                source_kind="markdown",
                targets={"paths": ["src/hello.txt"]},
                constraints={"disallowed_paths": ["src/hello.txt"]},
                operator_context={"summary": "initial blocked impl"},
            )
            plan_path = (
                task_artifacts_dir(root, initial.task_id)
                / "plans"
                / "plan-plan-FINAL_plan.json"
            )
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(
                json.dumps(
                    {
                        "summary": "seed plan artifact for resume precondition",
                        "implementationSteps": [],
                        "checklist": [],
                    },
                    indent=2,
                    ensure_ascii=True,
                )
                + "\n",
                encoding="utf-8",
            )
            blocked = PhaseRunner(root).run(request_path=initial.request_path)
            self.assertEqual(blocked.controller_status, "blocked")

            resume_source = root / "resume.json"
            resume_source.write_text(
                json.dumps(
                    {
                        "task_id": initial.task_id,
                        "summary": "Resume blocked impl",
                        "targets": {"paths": ["src/hello.txt"]},
                        "output": {
                            "preferred_mode": "patch",
                            "allowed_modes": ["patch"],
                            "operations_required": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = skill.dispatch(
                source_path=resume_source,
                workflow_intent="resume",
                source_kind="json",
                selectors={
                    "phase": "impl",
                    "strategy": "COLLAB_IMPL_PATCH_FIRST",
                    "step": "I0_analyze",
                    "resume_from": "I0_analyze",
                },
                operator_context={"summary": "resume test"},
            )

            controller = json.loads(
                result.controller_state_path.read_text(encoding="utf-8")
            )
            self.assertEqual(result.task_id, initial.task_id)
            self.assertEqual(controller["current_status"], "running")
            self.assertIn("stub:codex:impl:", target.read_text(encoding="utf-8"))

            adapter_dir = task_artifacts_dir(root, result.task_id) / "adapter"
            adapter_requests = sorted(
                adapter_dir.glob("adapter-request-impl-I0_analyze-*.json")
            )
            self.assertTrue(adapter_requests)
            adapter_request = json.loads(
                adapter_requests[-1].read_text(encoding="utf-8")
            )
            self.assertEqual(
                adapter_request["payload"]["session"]["requestedMode"], "resume"
            )
            self.assertEqual(
                adapter_request["payload"]["session"]["resolvedMode"], "resume"
            )

            events_path = task_artifacts_dir(root, result.task_id) / "events.jsonl"
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("task_resumed", [event["event_type"] for event in events])


if __name__ == "__main__":
    unittest.main()
