from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentorch_ctx.runtime.pathing import task_artifacts_dir, task_state_dir
from agentorch_ctx.runtime.task_entrypoint import (
    RequestValidationError,
    run_task_from_request,
)


class MalformedRequestRegressionTest(unittest.TestCase):
    def test_rejects_request_missing_required_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_root = task_artifacts_dir(root, "task-1")
            state_dir = task_state_dir(root, "task-1")
            task_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)
            request_path = task_root / "requests" / "request.json"
            request_path.parent.mkdir(parents=True, exist_ok=True)
            request_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "task_id": "task-1",
                        "source": {"path": "/tmp/task.md", "kind": "markdown"},
                        "workflow_intent": "plan",
                        "targets": {},
                        "constraints": {},
                        "output": {
                            "preferred_mode": "report_only",
                            "allowed_modes": ["report_only"],
                            "operations_required": False,
                        },
                        "artifacts": {
                            "task_root": str(task_root),
                            "intake_dir": str(task_root / "intake"),
                            "request_dir": str(task_root / "requests"),
                            "response_dir": str(task_root / "responses"),
                            "state_dir": str(state_dir),
                        },
                        "operator_context": {"summary": "malformed"},
                        "phase_options": {
                            "with_harden": False,
                            "auto_advance": False,
                            "budget_profile_ref": "budget-bootstrap",
                        },
                        "selectors": {},
                        "assembly_options": {},
                        "metadata": {
                            "created_at": "2026-03-08T00:00:00Z",
                            "source_canonicalized_at": "2026-03-08T00:00:00Z",
                            "host": "claude_code",
                            "cwd": str(root),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(RequestValidationError):
                run_task_from_request(request_path=request_path, root_dir=root)


if __name__ == "__main__":
    unittest.main()
