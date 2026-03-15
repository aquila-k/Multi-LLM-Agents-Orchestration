from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentorch_ctx.runtime.apply_executor import ApplyExecutor
from agentorch_ctx.runtime.pathing import task_artifacts_dir, task_state_dir


class ApplyGateIntegrationTest(unittest.TestCase):
    def test_applies_safe_patch_and_writes_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src" / "hello.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")

            executor = ApplyExecutor(root)
            normalized = {
                "metadata": {"source_response_ref": "response-1"},
                "operations": [
                    {
                        "operation_id": "op-1",
                        "target_path": "src/hello.txt",
                        "mode": "patch",
                        "risk_level": "low",
                        "requires_approval": False,
                        "confidence": 0.95,
                        "scope_check": "passed",
                        "content": "after\n",
                    }
                ],
            }
            validation = {
                "overall_outcome": "passed",
                "apply_readiness": {"codes": []},
                "metadata": {"response_ref": "validation-1"},
            }

            result = executor.apply(
                task_id="task-1",
                normalized=normalized,
                validation=validation,
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "applied")
            self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
            self.assertTrue(result["checkpoint_ref"])
            self.assertTrue(Path(result["checkpoint_ref"]).exists())
            apply_artifact = (
                task_artifacts_dir(root, "task-1")
                / "apply-results"
                / "apply-result-impl-apply.json"
            )
            self.assertTrue(apply_artifact.exists())
            self.assertFalse((task_state_dir(root, "task-1") / "apply.lock").exists())

    def test_blocks_approval_required_operation_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src" / "danger.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("keep\n", encoding="utf-8")

            executor = ApplyExecutor(root)
            normalized = {
                "metadata": {"source_response_ref": "response-2"},
                "operations": [
                    {
                        "operation_id": "op-1",
                        "target_path": "src/danger.txt",
                        "mode": "full_file",
                        "risk_level": "medium",
                        "requires_approval": True,
                        "confidence": 0.95,
                        "scope_check": "passed",
                        "content": "changed\n",
                    }
                ],
            }
            validation = {
                "overall_outcome": "failed_but_meaningful",
                "apply_readiness": {"codes": ["APPLY_MODE_REQUIRES_APPROVAL"]},
                "metadata": {"response_ref": "validation-2"},
            }

            result = executor.apply(
                task_id="task-2",
                normalized=normalized,
                validation=validation,
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "blocked_for_approval")
            self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")
            self.assertEqual(result["applied_operations"], [])
            artifact = (
                task_artifacts_dir(root, "task-2")
                / "apply-results"
                / "apply-result-impl-apply.json"
            )
            stored = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual(stored["payload"]["result"], "blocked_for_approval")


if __name__ == "__main__":
    unittest.main()
