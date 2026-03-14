"""Structured approval model for dangerous operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Operations that require explicit operator approval (§10.3)
DANGEROUS_OPERATION_TYPES: frozenset[str] = frozenset(
    {
        "file_delete",
        "file_rename",
        "file_move",
        "dependency_add",
        "dependency_update",
        "lockfile_update",
        "permission_change",
        "git_push",
        "git_history_rewrite",
        "network_install",
        "network_download",
        "db_migration",
        "external_api_write",
        "secret_create",
        "secret_update",
        "secret_delete",
        "cicd_config_change",
        "docker_env_change",
        "binary_file_add",
        "binary_file_update",
        "license_impacting_dependency",
        "large_diff",
    }
)


def build_approval_request(
    *,
    task_id: str,
    phase: str,
    step_id: str,
    operation_type: str,
    scope: dict[str, Any],
    rationale: str,
    impact: str = "",
    risk_level: str = "medium",
    pre_approved_in_plan: bool = False,
    pre_approval_ref: str = "",
    operation_types: list[str] | None = None,
    max_files: int = 0,
    max_bytes: int = 0,
    valid_phases: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "phase": phase,
        "stepId": step_id,
        "operationType": operation_type,
        "scope": scope,
        "operationTypes": operation_types or [],
        "maxFiles": max_files,
        "maxBytes": max_bytes,
        "validPhases": valid_phases or [],
        "rationale": rationale,
        "impact": impact,
        "riskLevel": risk_level,
        "preApprovedInPlan": pre_approved_in_plan,
        "preApprovalRef": pre_approval_ref,
    }


def build_approval_decision(
    *,
    task_id: str,
    approval_request_ref: str,
    decision: str,
    decided_by: str = "operator",
    conditions: list[str] | None = None,
    notes: str = "",
    approval_mode: str = "operation",
    scope_level: str = "exact",
    scope_match_policy: str = "strict",
    granted_by_user_explicitly: bool = False,
    valid_until_phase: str = "",
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "approvalRequestRef": approval_request_ref,
        "decision": decision,
        "approvalMode": approval_mode,
        "scopeLevel": scope_level,
        "scopeMatchPolicy": scope_match_policy,
        "grantedByUserExplicitly": granted_by_user_explicitly,
        "validUntilPhase": valid_until_phase,
        "decidedBy": decided_by,
        "decidedAt": _isoformat(datetime.now(timezone.utc)),
        "conditions": conditions or [],
        "notes": notes,
    }


def scope_match(operation: dict[str, Any], approval_decision: dict[str, Any]) -> bool:
    if approval_decision.get("decision") != "approved":
        return False

    scope = approval_decision.get("scope", {})
    if not isinstance(scope, dict):
        scope = {}

    scope_match_policy = str(approval_decision.get("scopeMatchPolicy") or "strict")
    target_path = str(operation.get("target_path") or operation.get("targetPath") or "")
    approved_paths = _scope_paths(scope)
    if scope_match_policy == "strict":
        if approved_paths:
            if target_path and target_path not in approved_paths:
                return False
        elif target_path:
            return False  # strict + no approved paths = nothing approved
    if scope_match_policy == "prefix_match" and approved_paths and target_path:
        if not any(
            target_path == path or target_path.startswith(f"{path}/")
            for path in approved_paths
        ):
            return False

    approval_mode = str(approval_decision.get("approvalMode") or "operation")
    operation_type = str(
        operation.get("operation_type")
        or classify_operation_type(operation)
        or ("large_diff" if operation.get("requires_approval") else "")
    )
    approved_type = str(approval_decision.get("operationType") or "")

    if approval_mode == "operation":
        if not operation_type:
            return False
        approved_types = _scope_operation_types(scope)
        if approved_type:
            return approved_type == operation_type
        return operation_type in approved_types

    if approval_mode in {"bundle", "phase", "task", "project"}:
        return bool(approval_decision.get("grantedByUserExplicitly"))

    return False


def classify_operation_type(operation: dict[str, Any]) -> str | None:
    """
    Infer a dangerous operation type from a normalized operation dict.
    Returns None if the operation is not recognized as dangerous.

    Checks:
    - mode == "delete" or kind == "delete" -> file_delete
    - mode == "rename" or kind == "rename" -> file_rename
    - mode == "move" or kind == "move" -> file_move
    - mode == "permission" or kind == "chmod" -> permission_change
    - mode == "binary_patch" or kind == "binary" -> binary_file_update
    - operation.get("requires_approval") == True and mode not in
      {"patch", "create_file", "full_file"} -> large_diff
    - operation.get("danger_class") present -> map to appropriate type
    """
    mode = str(operation.get("mode") or "").lower()
    kind = str(operation.get("kind") or "").lower()
    danger_class = str(operation.get("danger_class") or "").lower()

    direct_map = {
        "delete": "file_delete",
        "delete_file": "file_delete",
        "rename": "file_rename",
        "rename_file": "file_rename",
        "move": "file_move",
        "permission": "permission_change",
        "chmod": "permission_change",
        "binary_patch": "binary_file_update",
        "binary": "binary_file_update",
    }
    for key, op_type in direct_map.items():
        if mode == key or kind == key:
            return op_type

    danger_map = {
        "dependency_add": "dependency_add",
        "dependency_update": "dependency_update",
        "lockfile_update": "lockfile_update",
        "network_install": "network_install",
        "network_download": "network_download",
        "db_migration": "db_migration",
        "git_push": "git_push",
        "git_history": "git_history_rewrite",
        "external_write": "external_api_write",
        "secret": "secret_update",
        "secret_create": "secret_create",
        "secret_update": "secret_update",
        "secret_delete": "secret_delete",
        "cicd": "cicd_config_change",
        "docker": "docker_env_change",
        "license": "license_impacting_dependency",
        "binary_add": "binary_file_add",
        "binary_update": "binary_file_update",
        "large_diff": "large_diff",
    }
    if danger_class in danger_map:
        return danger_map[danger_class]

    if operation.get("requires_approval") and mode not in {
        "patch",
        "create_file",
        "full_file",
    }:
        return "large_diff"

    return None


def requires_approval(
    operation: dict[str, Any],
    approved_operations: list[dict[str, Any]] | None = None,
) -> bool:
    """
    True if this operation requires explicit approval and is NOT already
    pre-approved.

    `approved_operations` is a list of approval decision payloads from the
    request/normalized metadata.
    """
    op_type = classify_operation_type(operation)
    inferred_op_type = op_type or (
        "large_diff" if operation.get("requires_approval") else None
    )
    if inferred_op_type is None and not operation.get("requires_approval"):
        return False
    if inferred_op_type not in DANGEROUS_OPERATION_TYPES and not operation.get(
        "requires_approval"
    ):
        return False

    if approved_operations:
        for approval in approved_operations:
            if not isinstance(approval, dict):
                continue
            if approval.get("decision") != "approved":
                continue
            if str(approval.get("approvalMode") or "") in {
                "bundle",
                "phase",
                "task",
                "project",
            } and approval.get("grantedByUserExplicitly"):
                return False
            approval_op_type = str(approval.get("operationType") or "")
            if approval_op_type and approval_op_type == inferred_op_type:
                return False
            scope = approval.get("scope", {})
            if not isinstance(scope, dict):
                continue
            approved_types = scope.get("operationTypes", [])
            if (
                isinstance(approved_types, list)
                and inferred_op_type is not None
                and inferred_op_type in approved_types
            ):
                return False
    return True


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _scope_operation_types(scope: dict[str, Any]) -> set[str]:
    operation_types = scope.get("operationTypes", [])
    if not isinstance(operation_types, list):
        return set()
    return {
        str(operation_type)
        for operation_type in operation_types
        if isinstance(operation_type, str) and operation_type
    }


def _scope_paths(scope: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for key in ("targetFiles", "affectedPaths"):
        values = scope.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value:
                paths.add(value)
    return paths
