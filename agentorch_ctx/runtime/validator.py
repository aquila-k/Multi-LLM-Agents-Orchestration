from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

APPROVAL_REQUIRED_MODES = {
    "full_file",
    "mixed",
    "rename_file",
    "delete_file",
    "move",
    "chmod",
    "binary_patch",
}
REQUEST_REQUIRED_KEYS = {
    "schema_version",
    "task_id",
    "source",
    "workflow_intent",
    "summary",
    "targets",
    "constraints",
    "output",
    "artifacts",
    "operator_context",
    "selectors",
    "assembly_options",
    "metadata",
}
RESPONSE_REQUIRED_KEYS = {
    "schema_version",
    "task_id",
    "status",
    "mode",
    "summary",
    "warnings",
    "issues",
    "metadata",
}
NORMALIZED_REQUIRED_KEYS = {
    "schema_version",
    "task_id",
    "status",
    "mode",
    "payload_family",
    "safety",
    "validation_summary",
    "metadata",
}


def validate_artifacts(
    *,
    request: dict[str, Any],
    response: dict[str, Any],
    normalized: dict[str, Any],
    execution: dict[str, Any] | None = None,
    forbidden_paths: list[str] | None = None,
    max_files: int = 3,
    max_bytes: int = 20 * 1024,
) -> dict[str, Any]:
    forbidden_paths = forbidden_paths or []
    stages = [
        _request_stage(request),
        _execution_stage(execution),
        _response_analysis_stage(response),
        _response_schema_stage(response),
        _normalization_stage(normalized),
        _scope_stage(normalized, forbidden_paths),
    ]
    apply_readiness = _apply_readiness_stage(
        normalized, forbidden_paths, max_files, max_bytes
    )
    stages.append(apply_readiness["stage"])

    overall_outcome = _aggregate_outcome(stage["outcome"] for stage in stages)
    return {
        "schema_version": "1.0.0",
        "task_id": request.get("task_id")
        or response.get("task_id")
        or normalized.get("task_id")
        or "",
        "overall_outcome": overall_outcome,
        "stages": stages,
        "apply_readiness": {
            "ready": apply_readiness["ready"],
            "codes": apply_readiness["codes"],
            "summary": apply_readiness["summary"],
        },
        "metadata": {
            "validator_version": "1.0.0",
            "created_at": _isoformat(datetime.now(timezone.utc)),
            "normalized_ref": normalized.get("metadata", {}).get(
                "source_response_ref", ""
            ),
            "response_ref": response.get("metadata", {}).get("run_ref", ""),
        },
    }


def _request_stage(request: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUEST_REQUIRED_KEYS.difference(request))
    if missing:
        return _stage(
            "request_validation",
            "failed_unusable",
            [f"missing request keys: {', '.join(missing)}"],
        )
    if not request.get("summary"):
        return _stage("request_validation", "failed_unusable", ["summary is required"])
    return _stage("request_validation", "passed", [])


def _execution_stage(execution: dict[str, Any] | None) -> dict[str, Any]:
    if not execution:
        return _stage(
            "execution_validation",
            "passed_with_warnings",
            ["execution metadata not supplied; shell summary and digest not verified"],
        )
    messages: list[str] = []
    outcome = "passed"
    if not execution.get("shell_summary"):
        outcome = "failed_but_meaningful"
        messages.append("missing concise shell summary")
    if not execution.get("shell_digest_ref"):
        outcome = "failed_but_meaningful" if outcome == "passed" else outcome
        messages.append("missing shell digest ref")
    return _stage("execution_validation", outcome, messages)


def _response_analysis_stage(response: dict[str, Any]) -> dict[str, Any]:
    meaningful = (
        bool(response.get("summary"))
        or bool(response.get("payload"))
        or bool(response.get("raw_output_ref"))
    )
    if meaningful:
        return _stage("response_analysis_validation", "passed", [])
    return _stage(
        "response_analysis_validation",
        "failed_unusable",
        ["response has no meaningful output"],
    )


def _response_schema_stage(response: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(RESPONSE_REQUIRED_KEYS.difference(response))
    if missing:
        return _stage(
            "response_schema_validation",
            "failed_unusable",
            [f"missing response keys: {', '.join(missing)}"],
        )
    return _stage("response_schema_validation", "passed", [])


def _normalization_stage(normalized: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(NORMALIZED_REQUIRED_KEYS.difference(normalized))
    if missing:
        return _stage(
            "normalization_validation",
            "failed_unusable",
            [f"missing normalized keys: {', '.join(missing)}"],
        )
    if normalized.get("payload_family") == "operations" and not normalized.get(
        "operations"
    ):
        return _stage(
            "normalization_validation",
            "failed_but_meaningful",
            ["operations family requires operations[]"],
        )
    return _stage("normalization_validation", "passed", [])


def _scope_stage(
    normalized: dict[str, Any], forbidden_paths: list[str]
) -> dict[str, Any]:
    messages: list[str] = []
    outcome = "passed"
    operations = normalized.get("operations", [])
    for operation in operations:
        target = operation.get("target_path", "")
        if operation.get("scope_check") == "failed":
            outcome = "failed_but_meaningful"
            messages.append(f"scope check failed for {target}")
        if any(target.startswith(prefix) for prefix in forbidden_paths):
            outcome = "failed_but_meaningful"
            messages.append(f"forbidden path touched: {target}")
    if not operations and normalized.get("safety", {}).get("scope_check") == "unknown":
        outcome = "passed_with_warnings"
        messages.append("scope validation deferred because no operations were produced")
    return _stage("scope_validation", outcome, messages)


def _apply_readiness_stage(
    normalized: dict[str, Any],
    forbidden_paths: list[str],
    max_files: int,
    max_bytes: int,
) -> dict[str, Any]:
    operations = normalized.get("operations", [])
    codes: list[str] = []
    touched_paths = {
        operation.get("target_path", "")
        for operation in operations
        if operation.get("target_path")
    }
    total_bytes = sum(
        int(operation.get("estimated_changed_bytes", 0)) for operation in operations
    )

    if not operations:
        codes.append("APPLY_MISSING_ARTIFACT")
    for operation in operations:
        mode = operation.get("mode")
        target = operation.get("target_path", "")
        if operation.get("base_fingerprint") in {"", "mismatch", "unknown"}:
            codes.append("APPLY_FINGERPRINT_MISMATCH")
        if mode in APPROVAL_REQUIRED_MODES or operation.get("requires_approval"):
            codes.append("APPLY_MODE_REQUIRES_APPROVAL")
        if operation.get("scope_check") != "passed":
            codes.append("APPLY_SCOPE_FAILED")
        if any(target.startswith(prefix) for prefix in forbidden_paths):
            codes.append("APPLY_FORBIDDEN_PATH")
        if mode == "delete_file":
            codes.append("APPLY_DELETE_REQUIRES_APPROVAL")
        if operation.get("expected_existing_path_state") == "conflict":
            codes.append("APPLY_UNRESOLVED_CONFLICT")
    if len(touched_paths) > max_files:
        codes.append("APPLY_TOO_MANY_FILES")
    if total_bytes > max_bytes:
        codes.append("APPLY_TOO_MANY_BYTES")

    unique_codes = list(dict.fromkeys(codes))
    ready = not unique_codes
    stage_outcome = "passed" if ready else "failed_but_meaningful"
    summary = "apply ready" if ready else ", ".join(unique_codes)
    return {
        "ready": ready,
        "codes": unique_codes,
        "summary": summary,
        "stage": _stage(
            "apply_readiness_validation",
            stage_outcome,
            [summary] if unique_codes else [],
        ),
    }


def _stage(name: str, outcome: str, messages: list[str]) -> dict[str, Any]:
    return {"name": name, "outcome": outcome, "messages": messages}


def _aggregate_outcome(outcomes: Any) -> str:
    outcome_list = list(outcomes)
    if any(outcome == "failed_unusable" for outcome in outcome_list):
        return "failed_unusable"
    if any(outcome == "failed_but_meaningful" for outcome in outcome_list):
        return "failed_but_meaningful"
    if any(outcome == "passed_with_warnings" for outcome in outcome_list):
        return "passed_with_warnings"
    return "passed"


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
