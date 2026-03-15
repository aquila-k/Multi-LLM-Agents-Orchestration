from __future__ import annotations

import json

from agentorch_ctx.runtime.pathing import task_state_dir
from agentorch_ctx.runtime.task_runner import TaskRunner


def test_resume_approval_required_without_outcome_stays_blocked(tmp_path) -> None:
    runner = TaskRunner(tmp_path)
    task_id = "test-task-001"
    state_dir = task_state_dir(tmp_path, task_id)
    state_dir.mkdir(parents=True)

    controller = {
        "current_status": "blocked",
        "blocked_reason": "approval_required",
        "active_phase": "impl",
        "active_step": "I0_analyze",
        "active_strategy": "COLLAB_IMPL_STANDARD",
        "resume_hint": "",
        "resume_selectors": [],
        "last_successful_artifact_refs": [],
        "retry_counters": {},
    }
    (state_dir / "controller-state.json").write_text(
        json.dumps(controller, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (state_dir / "approval-state.json").write_text(
        json.dumps({"pending_approval_required": True}, indent=2, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
    )
    (state_dir / "resume-cursor.json").write_text(
        json.dumps({"phase": "impl", "step": "I0_analyze"}, indent=2, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
    )
    (state_dir / "known-information.json").write_text(
        json.dumps(
            {
                "latest_phase_summary": {
                    "phase": "impl",
                    "summary": "blocked awaiting approval",
                    "artifact_ref": "artifact-001",
                },
                "unresolved_blockers": ["approval_required"],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.resume(task_id=task_id)

    assert result.get("current_status") == "blocked"
    assert result.get("resume_hint") == "provide_approval_decision"
