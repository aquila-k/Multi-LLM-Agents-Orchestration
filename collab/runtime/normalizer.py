from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

NORMALIZER_VERSION = "1.0.0"


def normalize_response(
    *,
    task_id: str,
    parsed_response: dict[str, Any],
    source_response_ref: str,
) -> dict[str, Any]:
    payload = parsed_response.get("payload", {})
    operations = _extract_operations(payload)
    approved_operations = _extract_approved_operations(payload)
    payload_family = _detect_family(payload, operations)
    confidence = float(parsed_response.get("parser_confidence", 0.0))
    normalized_status = _normalized_status(parsed_response)
    scope_check = _scope_check(operations)

    normalized = {
        "schema_version": "1.0.0",
        "task_id": task_id,
        "status": normalized_status,
        "mode": parsed_response.get("mode", "report_only"),
        "payload_family": payload_family,
        "operations": operations,
        "approved_operations": approved_operations,
        "findings": payload.get("findings", []),
        "recommendations": payload.get("recommendations", []),
        "reports": _reports(payload, parsed_response, payload_family),
        "condensed_context": payload.get("condensed_context", []),
        "safety": {
            "requires_operator_review": parsed_response.get("mode")
            not in {"patch", "create_file", "full_file"}
            or normalized_status != "succeeded",
            "scope_check": scope_check,
            "confidence": confidence,
        },
        "validation_summary": {
            "outcome": _validation_outcome(parsed_response),
            "validation_ref": "",
        },
        "metadata": {
            "source_response_ref": source_response_ref,
            "normalizer_version": NORMALIZER_VERSION,
            "created_at": _isoformat(datetime.now(timezone.utc)),
        },
    }
    return normalized


def _extract_operations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_operations = payload.get("operations", [])
    if not isinstance(raw_operations, list):
        return []
    operations: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_operations, start=1):
        if not isinstance(raw, dict):
            continue
        operations.append(
            {
                "operation_id": raw.get("operation_id")
                or raw.get("operationId")
                or f"op-{index}",
                "kind": raw.get("kind", "patch"),
                "target_path": raw.get("target_path") or raw.get("targetPath") or "",
                "mode": raw.get("mode", "patch"),
                "base_fingerprint": raw.get("base_fingerprint")
                or raw.get("baseFingerprint")
                or "",
                "expected_existing_path_state": raw.get("expected_existing_path_state")
                or raw.get("expectedExistingPathState")
                or "unknown",
                "risk_level": raw.get("risk_level") or raw.get("riskLevel") or "medium",
                "requires_approval": bool(
                    raw.get("requires_approval", raw.get("requiresApproval", False))
                ),
                "scope_check": raw.get("scope_check")
                or raw.get("scopeCheck")
                or "unknown",
                "danger_class": raw.get("danger_class") or raw.get("dangerClass") or "",
                "confidence": float(raw.get("confidence", 0.0)),
                "source_run_refs": raw.get("source_run_refs")
                or raw.get("sourceRunRefs")
                or [],
                "validation_refs": raw.get("validation_refs")
                or raw.get("validationRefs")
                or [],
                "content": raw.get("content", ""),
                "patch": raw.get("patch", ""),
                "estimated_changed_lines": int(
                    raw.get(
                        "estimated_changed_lines", raw.get("estimatedChangedLines", 0)
                    )
                ),
                "estimated_changed_bytes": int(
                    raw.get(
                        "estimated_changed_bytes", raw.get("estimatedChangedBytes", 0)
                    )
                ),
            }
        )
    return operations


def _extract_approved_operations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_approvals = payload.get(
        "approved_operations", payload.get("approvedOperations")
    )
    if not isinstance(raw_approvals, list):
        return []
    approvals: list[dict[str, Any]] = []
    for item in raw_approvals:
        if isinstance(item, dict):
            approvals.append(item)
    return approvals


def _detect_family(payload: dict[str, Any], operations: list[dict[str, Any]]) -> str:
    if operations:
        return "operations"
    for key in ("findings", "recommendations", "reports", "condensed_context"):
        if isinstance(payload.get(key), list) and payload.get(key):
            return key
    return "reports"


def _reports(
    payload: dict[str, Any], parsed_response: dict[str, Any], payload_family: str
) -> list[dict[str, Any]]:
    if (
        payload_family == "reports"
        and isinstance(payload.get("reports"), list)
        and payload.get("reports")
    ):
        return payload["reports"]
    if isinstance(payload.get("report"), str):
        return [{"id": "report-1", "summary": payload["report"][:500]}]
    if isinstance(payload.get("patch"), str):
        return [
            {
                "id": "report-1",
                "summary": parsed_response.get("summary", "Patch captured"),
            }
        ]
    return []


def _normalized_status(parsed_response: dict[str, Any]) -> str:
    status = parsed_response.get("status")
    if status == "success":
        return "succeeded"
    if status == "blocked":
        return "blocked"
    if parsed_response.get("meaningful"):
        return "failed_but_meaningful" if status == "failed" else "partial"
    return "failed_unusable"


def _validation_outcome(parsed_response: dict[str, Any]) -> str:
    if (
        parsed_response.get("status") == "success"
        and parsed_response.get("parser_confidence", 0) >= 0.95
    ):
        return "passed"
    if parsed_response.get("meaningful"):
        return (
            "failed_but_meaningful"
            if parsed_response.get("status") == "failed"
            else "passed_with_warnings"
        )
    return "failed_unusable"


def _scope_check(operations: list[dict[str, Any]]) -> str:
    if not operations:
        return "unknown"
    if all(operation.get("scope_check") == "passed" for operation in operations):
        return "passed"
    if any(operation.get("scope_check") == "failed" for operation in operations):
        return "failed"
    return "unknown"


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
