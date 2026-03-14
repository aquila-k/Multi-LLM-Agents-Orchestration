from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collab.runtime.apply_executor import ApplyExecutor


class ApplyExecutorUnitTest(unittest.TestCase):
    def test_apply_full_file_mode_blocked_for_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-full-file-write",
                normalized={
                    "metadata": {"source_response_ref": "response-1"},
                    "operations": [
                        {
                            "operation_id": "op-1",
                            "target_path": "src/new.txt",
                            "mode": "full_file",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                            "content": "new content\n",
                        }
                    ],
                },
                validation=self._validation("validation-1"),
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "blocked_for_approval")
            self.assertEqual(result.get("reason"), "full_file_requires_approval")
            self.assertFalse((root / "src" / "new.txt").exists())

    def test_apply_full_file_mode_blocked_when_overwriting_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src" / "overwrite.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-full-file-overwrite",
                normalized={
                    "metadata": {"source_response_ref": "response-2"},
                    "operations": [
                        {
                            "operation_id": "op-1",
                            "target_path": "src/overwrite.txt",
                            "mode": "full_file",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                            "content": "after\n",
                        }
                    ],
                },
                validation=self._validation("validation-2"),
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "blocked_for_approval")
            self.assertEqual(result.get("reason"), "full_file_requires_approval")
            self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

    def test_full_file_with_empty_content_and_patch_also_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src" / "fallback.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-full-file-fallback",
                normalized={
                    "metadata": {"source_response_ref": "response-3"},
                    "operations": [
                        {
                            "operation_id": "op-1",
                            "target_path": "src/fallback.txt",
                            "mode": "full_file",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                            "content": "",
                            "patch": "from patch\n",
                        }
                    ],
                },
                validation=self._validation("validation-3"),
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "blocked_for_approval")
            self.assertEqual(result.get("reason"), "full_file_requires_approval")
            self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

    def test_apply_blocks_delete_mode_operation_for_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-delete-block",
                normalized={
                    "metadata": {"source_response_ref": "response-delete"},
                    "operations": [
                        {
                            "operation_id": "op-1",
                            "target_path": "src/remove.txt",
                            "mode": "delete",
                            "kind": "delete",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                        }
                    ],
                },
                validation=self._validation("validation-delete"),
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "blocked_for_approval")
            self.assertEqual(
                result.get("reason"), "dangerous_operations_require_approval"
            )
            self.assertEqual(
                result.get("dangerous_operations", [{}])[0].get("operation_type"),
                "file_delete",
            )

    def test_apply_blocks_dependency_add_danger_class_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-dependency-block",
                normalized={
                    "metadata": {"source_response_ref": "response-dependency"},
                    "operations": [
                        {
                            "operation_id": "op-1",
                            "target_path": "pyproject.toml",
                            "mode": "patch",
                            "kind": "patch",
                            "danger_class": "dependency_add",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                            "content": "[project]\n",
                        }
                    ],
                },
                validation=self._validation("validation-dependency"),
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "blocked_for_approval")
            self.assertEqual(
                result.get("dangerous_operations", [{}])[0].get("operation_type"),
                "dependency_add",
            )

    def test_dangerous_operation_writes_approval_request_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-approval-artifact",
                normalized={
                    "metadata": {"source_response_ref": "response-approval-artifact"},
                    "operations": [
                        {
                            "operation_id": "op-1",
                            "target_path": "pyproject.toml",
                            "mode": "patch",
                            "kind": "patch",
                            "danger_class": "dependency_add",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                            "content": "[project]\n",
                            "estimated_changed_lines": 4,
                            "estimated_changed_bytes": 128,
                        }
                    ],
                },
                validation=self._validation("validation-approval-artifact"),
                phase="impl",
                step="apply",
            )

            approval_artifact = (
                root
                / "collab"
                / "artifacts"
                / "tasks"
                / "task-approval-artifact"
                / "approval-requests"
                / "approval-request-impl-apply.json"
            )
            self.assertEqual(result["result"], "blocked_for_approval")
            self.assertTrue(approval_artifact.exists())
            envelope = json.loads(approval_artifact.read_text(encoding="utf-8"))
            payload = envelope.get("payload", {})
            self.assertEqual(payload.get("operationType"), "dependency_add")
            self.assertEqual(payload.get("operationTypes"), ["dependency_add"])
            self.assertEqual(payload.get("maxFiles"), 1)
            self.assertEqual(payload.get("maxBytes"), 128)
            self.assertEqual(payload.get("validPhases"), ["impl"])

    def test_approval_request_ref_in_blocked_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-approval-ref",
                normalized={
                    "metadata": {"source_response_ref": "response-approval-ref"},
                    "operations": [
                        {
                            "operation_id": "op-1",
                            "target_path": "src/remove.txt",
                            "mode": "delete",
                            "kind": "delete",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                        }
                    ],
                },
                validation=self._validation("validation-approval-ref"),
                phase="impl",
                step="apply",
            )

            approval_artifact = (
                root
                / "collab"
                / "artifacts"
                / "tasks"
                / "task-approval-ref"
                / "approval-requests"
                / "approval-request-impl-apply.json"
            )
            self.assertEqual(
                result.get("reason"), "dangerous_operations_require_approval"
            )
            self.assertEqual(
                Path(result.get("approvalRequestRef", "")).resolve(),
                approval_artifact.resolve(),
            )

    def test_apply_allows_regular_patch_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src" / "safe.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-safe-patch",
                normalized={
                    "metadata": {"source_response_ref": "response-safe"},
                    "operations": [
                        {
                            "operation_id": "op-1",
                            "target_path": "src/safe.txt",
                            "mode": "patch",
                            "kind": "patch",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                            "content": "after\n",
                        }
                    ],
                },
                validation=self._validation("validation-safe"),
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "applied")
            self.assertEqual(target.read_text(encoding="utf-8"), "after\n")

    def test_apply_operation_exception_writes_failure_artifact_then_reraises(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = ApplyExecutor(root)

            def _raise_apply(_operation: dict[str, object]) -> None:
                raise RuntimeError("simulated apply failure")

            executor._apply_operation = _raise_apply  # type: ignore[method-assign]

            with self.assertRaises(RuntimeError):
                executor.apply(
                    task_id="task-apply-failure-artifact",
                    normalized={
                        "metadata": {"source_response_ref": "response-failure"},
                        "operations": [
                            {
                                "operation_id": "op-fail-1",
                                "target_path": "src/fail.txt",
                                "mode": "patch",
                                "risk_level": "low",
                                "requires_approval": False,
                                "confidence": 0.95,
                                "scope_check": "passed",
                                "content": "after\n",
                            }
                        ],
                    },
                    validation=self._validation("validation-failure"),
                    phase="impl",
                    step="apply",
                    attempt=2,
                    run=3,
                )

            failure_artifact = (
                root
                / "collab"
                / "artifacts"
                / "tasks"
                / "task-apply-failure-artifact"
                / "apply-results"
                / "apply-result-impl-apply-2-3-failure.json"
            )
            self.assertTrue(failure_artifact.exists())
            envelope = json.loads(failure_artifact.read_text(encoding="utf-8"))
            payload = envelope.get("payload", {})
            self.assertEqual(payload.get("result"), "failed_with_exception")
            self.assertEqual(payload.get("reason"), "apply_operation_exception")
            self.assertEqual(payload.get("operation_id"), "op-fail-1")
            self.assertEqual(payload.get("target_path"), "src/fail.txt")
            self.assertTrue(payload.get("checkpoint_ref", ""))

    def test_full_file_blocked_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-full-file-no-approval",
                normalized={
                    "metadata": {"source_response_ref": "response-ff"},
                    "operations": [
                        {
                            "operation_id": "op-ff-1",
                            "target_path": "src/blocked.txt",
                            "mode": "full_file",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                            "content": "blocked content\n",
                        }
                    ],
                },
                validation=self._validation("validation-ff"),
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "blocked_for_approval")
            self.assertEqual(result.get("reason"), "full_file_requires_approval")
            dangerous = result.get("dangerous_operations", [])
            self.assertTrue(len(dangerous) >= 1)
            self.assertEqual(dangerous[0].get("operation_id"), "op-ff-1")

    def test_patch_safe_apply_still_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src" / "patch_safe.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("original\n", encoding="utf-8")
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-patch-safe",
                normalized={
                    "metadata": {"source_response_ref": "response-patch"},
                    "operations": [
                        {
                            "operation_id": "op-patch-1",
                            "target_path": "src/patch_safe.txt",
                            "mode": "patch",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                            "content": "patched\n",
                        }
                    ],
                },
                validation=self._validation("validation-patch"),
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "applied")
            self.assertEqual(target.read_text(encoding="utf-8"), "patched\n")

    def test_create_file_bounded_safe_apply_still_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src" / "brand_new.txt"
            executor = ApplyExecutor(root)

            result = executor.apply(
                task_id="task-create-file-safe",
                normalized={
                    "metadata": {"source_response_ref": "response-create"},
                    "operations": [
                        {
                            "operation_id": "op-create-1",
                            "target_path": "src/brand_new.txt",
                            "mode": "create_file",
                            "risk_level": "low",
                            "requires_approval": False,
                            "confidence": 0.95,
                            "scope_check": "passed",
                            "content": "new file content\n",
                        }
                    ],
                },
                validation=self._validation("validation-create"),
                phase="impl",
                step="apply",
            )

            self.assertEqual(result["result"], "applied")
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "new file content\n")

    def _validation(self, response_ref: str) -> dict[str, object]:
        return {
            "overall_outcome": "passed",
            "apply_readiness": {"codes": []},
            "metadata": {"response_ref": response_ref},
        }


if __name__ == "__main__":
    unittest.main()
