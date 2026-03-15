from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.approval_model import (
    DANGEROUS_OPERATION_TYPES,
    build_approval_request,
    classify_operation_type,
    requires_approval,
    scope_match,
)
from agentorch_ctx.runtime.artifact_store import ArtifactStore
from agentorch_ctx.runtime.checkpoint import CheckpointManager
from agentorch_ctx.runtime.locks import FileLock

AUTO_APPLY_OUTCOMES = {"passed", "passed_with_warnings"}
ALLOWED_MODES = {"patch", "create_file"}


class ApplyExecutor:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.store = ArtifactStore(self.root_dir)
        self.checkpoints = CheckpointManager(self.root_dir)

    def apply(
        self,
        *,
        task_id: str,
        normalized: dict[str, Any],
        validation: dict[str, Any],
        phase: str,
        step: str,
        attempt: int = 1,
        run: int = 1,
    ) -> dict[str, Any]:
        from agentorch_ctx.runtime.pathing import task_state_dir

        lock_path = task_state_dir(self.root_dir, task_id) / "apply.lock"
        with FileLock(lock_path):
            result = self._evaluate(
                task_id=task_id,
                normalized=normalized,
                validation=validation,
                phase=phase,
                step=step,
            )
            checkpoint_path = ""
            if result["result"] == "applied":
                target_paths = [
                    self._resolve_target_path(operation["target_path"])
                    for operation in normalized.get("operations", [])
                ]
                checkpoint_path = str(
                    self.checkpoints.create_checkpoint(
                        task_id=task_id,
                        target_paths=target_paths,
                        phase=phase,
                        step=step,
                        attempt=attempt,
                        run=run,
                    )
                )
                for operation in normalized.get("operations", []):
                    try:
                        self._apply_operation(operation)
                    except Exception as exc:
                        failure_result = {
                            "schema_version": "1.0.0",
                            "task_id": task_id,
                            "result": "failed_with_exception",
                            "reason": "apply_operation_exception",
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc)[:500],
                            "operation_id": operation.get("operation_id", ""),
                            "target_path": operation.get("target_path", ""),
                            "checkpoint_ref": checkpoint_path,
                            "blocked_reasons": ["unsafe_apply"],
                        }
                        self.store.write_json_artifact(
                            task_id=task_id,
                            family="apply-results",
                            artifact_type="apply_result",
                            payload=failure_result,
                            filename=(
                                f"apply-result-{phase}-{step}-{attempt}-{run}"
                                "-failure.json"
                            ),
                            phase=phase,
                            step=step,
                            attempt=attempt,
                            run=run,
                        )
                        raise
            result["checkpoint_ref"] = checkpoint_path
            result["metadata"] = {
                "created_at": _isoformat(datetime.now(timezone.utc)),
                "normalized_ref": normalized.get("metadata", {}).get(
                    "source_response_ref", ""
                ),
                "validation_ref": validation.get("metadata", {}).get(
                    "response_ref", ""
                ),
                "operator_decision_ref": "",
            }
            self.store.write_json_artifact(
                task_id=task_id,
                family="apply-results",
                artifact_type="apply_result",
                payload=result,
                filename=f"apply-result-{phase}-{step}.json",
                phase=phase,
                step=step,
                attempt=attempt,
                run=run,
            )
            return result

    def _evaluate(
        self,
        *,
        task_id: str,
        normalized: dict[str, Any],
        validation: dict[str, Any],
        phase: str = "",
        step: str = "",
    ) -> dict[str, Any]:
        validation_outcome = validation.get("overall_outcome")
        codes = validation.get("apply_readiness", {}).get("codes", [])
        operations = normalized.get("operations", [])
        if validation_outcome not in AUTO_APPLY_OUTCOMES:
            return self._blocked_result(task_id, self._blocked_reason(codes))
        if not operations:
            return self._blocked_result(task_id, "denied_by_policy")

        approved_operations = normalized.get("approved_operations", [])
        if not isinstance(approved_operations, list):
            approved_operations = []
        dangerous_operations = []
        for operation in operations:
            if not requires_approval(operation, approved_operations):
                continue
            if any(
                scope_match(operation, approval)
                for approval in approved_operations
                if isinstance(approval, dict)
            ):
                continue
            operation_type = classify_operation_type(operation) or "large_diff"
            if operation_type not in DANGEROUS_OPERATION_TYPES:
                operation_type = "large_diff"
            dangerous_operations.append(
                {
                    "operation_id": operation.get("operation_id", ""),
                    "operation_type": operation_type,
                    "target_path": operation.get("target_path", ""),
                    "requires_explicit_approval": True,
                }
            )
        if dangerous_operations:
            blocked = self._blocked_result(task_id, "blocked_for_approval")
            blocked["reason"] = "dangerous_operations_require_approval"
            blocked["dangerous_operations"] = dangerous_operations
            blocked["approvalRequestRef"] = self._write_approval_request_artifact(
                task_id=task_id,
                phase=phase,
                step=step,
                operations=operations,
                dangerous_operations=dangerous_operations,
            )
            return blocked

        full_file_operations = [
            {
                "operation_id": op.get("operation_id", ""),
                "operation_type": "full_file",
                "target_path": op.get("target_path", ""),
                "requires_explicit_approval": True,
            }
            for op in operations
            if op.get("mode") == "full_file"
        ]
        if full_file_operations:
            blocked = self._blocked_result(task_id, "blocked_for_approval")
            blocked["reason"] = "full_file_requires_approval"
            blocked["dangerous_operations"] = full_file_operations
            return blocked

        for operation in operations:
            if operation.get("mode") not in ALLOWED_MODES:
                return self._blocked_result(task_id, "blocked_for_approval")
            if operation.get("risk_level") not in {"low", "medium"}:
                return self._blocked_result(task_id, "denied_by_policy")
            if float(operation.get("confidence", 0.0)) < 0.85:
                return self._blocked_result(task_id, "denied_by_policy")
            if operation.get("scope_check") != "passed":
                return self._blocked_result(task_id, "blocked_for_scope")
        return {
            "schema_version": "1.0.0",
            "task_id": task_id,
            "result": "applied",
            "applied_operations": [
                operation["operation_id"] for operation in operations
            ],
            "blocked_reasons": [],
        }

    def _blocked_reason(self, codes: list[str]) -> str:
        if (
            "APPLY_MODE_REQUIRES_APPROVAL" in codes
            or "APPLY_DELETE_REQUIRES_APPROVAL" in codes
        ):
            return "blocked_for_approval"
        if "APPLY_UNRESOLVED_CONFLICT" in codes:
            return "blocked_for_conflict"
        if "APPLY_SCOPE_FAILED" in codes or "APPLY_FORBIDDEN_PATH" in codes:
            return "blocked_for_scope"
        if "APPLY_FINGERPRINT_MISMATCH" in codes:
            return "blocked_for_fingerprint"
        if "APPLY_BUDGET_BLOCKED" in codes:
            return "blocked_for_budget"
        return "denied_by_policy"

    def _blocked_result(self, task_id: str, reason: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "task_id": task_id,
            "result": reason,
            "applied_operations": [],
            "blocked_reasons": [reason],
        }

    def _write_approval_request_artifact(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        operations: list[dict[str, Any]],
        dangerous_operations: list[dict[str, Any]],
    ) -> str:
        operations_by_id = {
            str(operation.get("operation_id", "")): operation
            for operation in operations
        }
        scoped_operations = [
            operations_by_id.get(str(item.get("operation_id", "")), {})
            for item in dangerous_operations
        ]
        target_paths = _unique_non_empty_strings(
            item.get("target_path", "") for item in dangerous_operations
        )
        operation_types = _unique_non_empty_strings(
            item.get("operation_type", "") for item in dangerous_operations
        )
        max_bytes = sum(
            int(operation.get("estimated_changed_bytes", 0) or 0)
            for operation in scoped_operations
            if isinstance(operation, dict)
        )
        estimated_changed_lines = sum(
            int(operation.get("estimated_changed_lines", 0) or 0)
            for operation in scoped_operations
            if isinstance(operation, dict)
        )
        primary_operation_type = (
            operation_types[0] if len(operation_types) == 1 else "large_diff"
        )
        approval_request = build_approval_request(
            task_id=task_id,
            phase=phase,
            step_id=step,
            operation_type=primary_operation_type,
            scope={
                "targetFiles": target_paths,
                "affectedPaths": target_paths,
                "estimatedChangedFiles": len(target_paths),
                "estimatedChangedLines": estimated_changed_lines,
            },
            rationale="Dangerous operations require explicit approval before apply.",
            impact=(
                f"Blocked {len(dangerous_operations)} approval-sensitive operation(s)"
                f" affecting {len(target_paths)} file(s)."
            ),
            risk_level="high",
            operation_types=operation_types,
            max_files=len(target_paths),
            max_bytes=max_bytes,
            valid_phases=[phase] if phase else [],
        )
        artifact = self.store.write_json_artifact(
            task_id=task_id,
            family="approval-requests",
            artifact_type="approval_request",
            payload=approval_request,
            filename=f"approval-request-{phase}-{step}.json",
            phase=phase,
            step=step,
        )
        return str(artifact.path)

    def _apply_operation(self, operation: dict[str, Any]) -> None:
        target_path = self._resolve_target_path(operation["target_path"])
        mode = operation.get("mode", "patch")

        if mode == "full_file":
            raise ValueError("full_file requires explicit approval before apply")

        content = operation.get("content") or operation.get("patch")
        if not isinstance(content, str):
            raise ValueError(
                f"operation {operation['operation_id']} is missing content"
            )

        if mode == "patch":
            target_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_text_atomic(target_path, content)
            return

        if mode == "create_file":
            if target_path.exists():
                raise FileExistsError(
                    f"create_file target already exists: {target_path}"
                )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_text_atomic(target_path, content)
            return

        raise ValueError(f"unsupported apply mode: {mode}")

    def _write_text_atomic(self, target_path: Path, content: str) -> None:
        """Write content to target_path atomically via a temp-file rename.

        For both ``patch`` and ``create_file`` modes, ``content`` is the
        **full final file content** (not a diff or partial update).
        """
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        temp_path.replace(target_path)

    def _resolve_target_path(self, target_path: str) -> Path:
        candidate = (self.root_dir / target_path).resolve()
        try:
            candidate.relative_to(self.root_dir)
        except ValueError:
            raise ValueError(f"target path escapes root: {target_path}")
        if any(
            part in {"artifacts", "state"}
            for part in candidate.relative_to(self.root_dir).parts[:2]
        ):
            raise ValueError(f"target path touches runtime state: {target_path}")
        return candidate


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _unique_non_empty_strings(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
