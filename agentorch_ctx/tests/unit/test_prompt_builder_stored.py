from __future__ import annotations

import unittest

from agentorch_ctx.runtime.prompt_builder import build_prompt


class PromptBuilderStoredContextTest(unittest.TestCase):
    def test_stored_context_missing_skips_section(self) -> None:
        prompt = self._build_prompt(stored_context=None)
        self.assertNotIn("## Stored Context", prompt)

    def test_task_snapshot_only_renders_task_goal(self) -> None:
        stored_context = {"task_snapshot": {"task_goal": "Finish testing"}}
        prompt = self._build_prompt(stored_context=stored_context)
        self.assertIn("## Stored Context", prompt)
        self.assertIn("### Task Goal", prompt)
        self.assertIn("Finish testing", prompt)

    def test_full_stored_context_clips_and_limits(self) -> None:
        stored_context = {
            "project_context": {"goal": "Ship the stored context feature"},
            "task_snapshot": {
                "task_goal": "Integrate contexts",
                "current_plan": "plan-" + "A" * 1_000,
                "progress": "Halfway there",
                "open_questions": [f"Question {i}?" for i in range(1, 5)],
                "blockers": [f"Blocker {i}" for i in range(1, 5)],
            },
            "decisions": [
                {"key": f"key-{i}", "summary": f"Decision {i}"} for i in range(6)
            ],
        }
        prompt = self._build_prompt(stored_context=stored_context)
        self.assertIn("### Project Goal", prompt)
        self.assertIn("## Stored Context (from project memory)", prompt)
        self.assertIn("Blocker 3", prompt)
        self.assertNotIn("Blocker 4", prompt)
        self.assertIn("Active Decisions", prompt)
        self.assertIn("key-4", prompt)
        self.assertNotIn("key-5", prompt)

    def _build_prompt(self, *, stored_context: dict | None) -> str:
        request = {
            "workflow_intent": "impl",
            "summary": "Implement stored context",
            "targets": {"paths": ["agentorch_ctx/runtime/prompt_builder.py"]},
            "constraints": {"hard": [], "soft": []},
            "source": {"path": "/tmp/mock.md", "kind": "markdown"},
            "operator_context": {},
        }
        if stored_context is not None:
            request["operator_context"]["stored_context"] = stored_context
        resolved_config = {
            "phase": "impl",
            "artifacts": {},
            "strategy": {"selectedStrategyId": "mock"},
            "provider": {"provider": "codex", "modelRef": "codex-primary"},
            "signals": [],
        }
        return build_prompt(
            request=request,
            resolved_config=resolved_config,
            step_id="I1",
            provider="codex",
            model_ref="codex-primary",
            effective_output_mode="patch",
        )


if __name__ == "__main__":
    unittest.main()
