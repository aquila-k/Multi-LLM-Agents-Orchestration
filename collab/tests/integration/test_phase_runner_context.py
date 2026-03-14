from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collab.runtime.claude_code_skill import ClaudeCodeSkill
from collab.runtime.phase_runner import PhaseRunner
import collab.tests.integration.test_phase_runner as phase_runner_integration


_VALID_PLAN_CONTENT = "\n".join(
    [
        "1. Update collab/runtime/phase_runner.py with context write-back hooks",
        "2. Add regression checks for stored context prompts",
        "- [ ] Persist task snapshot revisions",
        "collab/runtime/phase_runner.py",
    ]
)


class PhaseRunnerContextIntegrationTest(unittest.TestCase):
    def _helper(self) -> unittest.TestCase:
        return phase_runner_integration.PhaseRunnerIntegrationTest(methodName="runTest")

    def test_write_back_context_called_after_phase(self) -> None:
        helper = self._helper()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("collab.runtime.phase_runner._write_back_context") as write_back:
                helper._run_mocked_plan_phase(root=root, content=_VALID_PLAN_CONTENT)
            self.assertTrue(write_back.called)

    def test_blocked_phase_skips_context_write_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "plan.md"
            source.write_text("# Plan runtime\n", encoding="utf-8")
            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                selectors={"step": "FINAL_plan"},
                operator_context={"summary": "mocked plan artifacts"},
            )
            runner = PhaseRunner(root)
            with patch.object(
                PhaseRunner, "_should_block_for_task_ambiguity", return_value=True
            ):
                with patch("collab.runtime.phase_runner._write_back_context") as write_back:
                    result = runner.run(request_path=dispatch.request_path)
            self.assertEqual(result.executed_phases, [])
            self.assertFalse(write_back.called)

    def test_context_bridge_failures_are_degraded(self) -> None:
        helper = self._helper()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "collab.runtime.context_bridge.save_task_snapshot",
                side_effect=RuntimeError("boom"),
            ):
                with patch(
                    "collab.runtime.context_bridge.log_episode",
                    side_effect=RuntimeError("boom"),
                ):
                    with patch(
                        "collab.runtime.context_bridge.log_decision",
                        side_effect=RuntimeError("boom"),
                    ):
                        task_id, _phase_run_path = helper._run_mocked_plan_phase(
                            root=root, content=_VALID_PLAN_CONTENT
                        )
        self.assertTrue(task_id)

    def test_plan_phase_logs_decisions_for_findings(self) -> None:
        helper = self._helper()
        findings = [
            "Why is this needed?",
            "What about edge cases?",
            "Do we have tests?",
            "Extra question?",
        ]
        recorded_decisions: list[dict[str, object]] = []
        original = helper._mock_coordination_result

        def patched_mocked_coordination_result(**kwargs: object):
            result = original(**kwargs)
            normalized_path = result.normalized_path
            normalized_path.write_text(
                json.dumps(
                    {
                        "content": _VALID_PLAN_CONTENT,
                        "summary": "normalized",
                        "findings": findings,
                        "next_steps": ["next"],
                        "risks": [],
                    }
                ),
                encoding="utf-8",
            )
            return result

        def record_decision(*args: object, **kwargs: object) -> dict[str, object]:
            recorded_decisions.append({"args": args, "kwargs": kwargs})
            return {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(
                helper,
                "_mock_coordination_result",
                side_effect=patched_mocked_coordination_result,
            ):
                with patch(
                    "collab.runtime.context_bridge.save_task_snapshot",
                    return_value={"ok": True},
                ):
                    with patch(
                        "collab.runtime.context_bridge.log_episode",
                        return_value={"ok": True},
                    ):
                        with patch(
                            "collab.runtime.context_bridge.log_decision",
                            side_effect=record_decision,
                        ):
                            helper._run_mocked_plan_phase(
                                root=root, content=_VALID_PLAN_CONTENT
                            )
        self.assertEqual(len(recorded_decisions), 3)
        self.assertTrue(
            all(
                "summary" in str(call["kwargs"].get("payload", {}))
                for call in recorded_decisions
            )
        )
        self.assertFalse(
            any(
                "Extra question" in str(call["kwargs"].get("payload", {}).get("summary", ""))
                for call in recorded_decisions
            )
        )


if __name__ == "__main__":
    unittest.main()
