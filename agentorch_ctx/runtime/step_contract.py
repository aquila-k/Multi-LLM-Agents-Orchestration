"""Step input/output contract checking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STEP_ARTIFACT_REF_KEYS = (
    "responseRef",
    "normalizedRef",
    "applyResultRef",
    "validationRef",
)


def check_input_contract(
    *,
    task_root: Path,
    step_def: dict[str, Any],
    prior_step_records: list[dict[str, Any]],
) -> tuple[bool, str]:
    """
    Returns (ok, reason). ok=True means contract is satisfied.
    reason is empty string if ok, or description of failure.

    Checks that all requiredArtifacts in inputContract exist.
    A required artifact can be:
    - A family directory like "plans/" (directory must be non-empty)
    - An exact relative path from task_root
    - A step output ref from prior_step_records
    """
    contract = step_def.get("inputContract", {})
    if not isinstance(contract, dict):
        return True, ""

    required = contract.get("requiredArtifacts", [])
    if not isinstance(required, list) or not required:
        return True, ""

    on_missing = str(contract.get("onMissingRequired", "stop")).strip().lower()
    if on_missing != "stop":
        return True, ""

    missing: list[str] = []
    for artifact_spec in required:
        if not isinstance(artifact_spec, str):
            continue
        if not _check_artifact_exists(
            task_root=task_root,
            artifact_spec=artifact_spec,
            prior_step_records=prior_step_records,
        ):
            missing.append(artifact_spec)

    if missing:
        return False, f"missing_required_artifacts: {', '.join(missing)}"
    return True, ""


def inject_artifact_refs(
    *,
    request: dict[str, Any],
    task_root: Path,
    step_def: dict[str, Any],  # kept for future contract-specific mapping
    prior_step_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Inject explicit artifact refs from prior steps into request.operator_context.
    Returns a deep copy of request with refs injected.
    """
    _ = step_def
    updated = json.loads(json.dumps(request))
    operator_context = updated.setdefault("operator_context", {})
    if not isinstance(operator_context, dict):
        operator_context = {}
        updated["operator_context"] = operator_context

    artifact_refs: list[dict[str, str]] = []
    for record in prior_step_records:
        if not isinstance(record, dict):
            continue
        step_id = str(record.get("step", "")).strip()
        for ref_key in _STEP_ARTIFACT_REF_KEYS:
            ref_val = str(record.get(ref_key, "")).strip()
            if ref_val:
                artifact_refs.append(
                    {"step": step_id, "refType": ref_key, "ref": ref_val}
                )

    if artifact_refs:
        operator_context["prior_step_artifact_refs"] = artifact_refs

    plan_family_dir = task_root / "plans"
    if plan_family_dir.exists() and plan_family_dir.is_dir():
        plan_files = sorted(
            path for path in plan_family_dir.glob("*.json") if path.is_file()
        )
        if plan_files:
            operator_context["plan_artifact_ref"] = str(plan_files[-1])

    checklist_family_dir = task_root / "checklists"
    if checklist_family_dir.exists() and checklist_family_dir.is_dir():
        checklist_files = sorted(
            path for path in checklist_family_dir.glob("*.json") if path.is_file()
        )
        if checklist_files:
            operator_context["checklist_artifact_ref"] = str(checklist_files[-1])

    merge_inputs_dir = task_root / "merge-inputs"
    if merge_inputs_dir.exists() and merge_inputs_dir.is_dir():
        merge_files = sorted(
            path for path in merge_inputs_dir.glob("*.json") if path.is_file()
        )
        if merge_files:
            operator_context["merge_input_ref"] = str(merge_files[-1])

    return updated


def check_output_contract(
    *,
    task_root: Path,
    step_def: dict[str, Any],
    step_record: dict[str, Any],
) -> tuple[bool, str]:
    """
    Returns (ok, reason). ok=True means the output contract is satisfied.

    Checks that all producedArtifacts declared in outputContract exist after
    step execution.  Also checks completionSignal if declared.
    """
    contract = step_def.get("outputContract", {})
    if not isinstance(contract, dict):
        return True, ""

    produced = contract.get("producedArtifacts", [])
    if not isinstance(produced, list):
        produced = []

    missing: list[str] = []
    for artifact_spec in produced:
        if not isinstance(artifact_spec, str) or not artifact_spec.strip():
            continue
        if not _check_artifact_exists(
            task_root=task_root,
            artifact_spec=artifact_spec,
            prior_step_records=[step_record],
        ):
            missing.append(artifact_spec)

    if missing:
        return False, f"missing_produced_artifacts: {', '.join(missing)}"

    completion_signal = str(contract.get("completionSignal", "")).strip()
    if completion_signal.startswith("controller_status:"):
        expected_status = completion_signal.split(":", 1)[1].strip()
        actual_status = str(step_record.get("controllerStatus", "")).strip()
        # "partial" and "running" are valid successful completion statuses
        # in the runtime; treat them as compatible with "completed".
        # "running" means the controller moved to the next step (multi-step
        # strategies); "partial" indicates intermediate successful results.
        compatible_statuses = {expected_status}
        if expected_status == "completed":
            compatible_statuses.update({"partial", "running", "succeeded"})
        if (
            expected_status
            and actual_status
            and actual_status not in compatible_statuses
        ):
            return (
                False,
                f"completion_signal_mismatch: expected={expected_status} actual={actual_status}",
            )

    return True, ""


def _check_artifact_exists(
    *,
    task_root: Path,
    artifact_spec: str,
    prior_step_records: list[dict[str, Any]],
) -> bool:
    """True if the artifact spec is satisfied."""
    spec = artifact_spec.strip()
    if not spec:
        return False

    if spec.endswith("/"):
        family_dir = task_root / spec.rstrip("/")
        return family_dir.exists() and family_dir.is_dir() and any(family_dir.iterdir())

    for record in prior_step_records:
        if not isinstance(record, dict):
            continue
        for ref_key in _STEP_ARTIFACT_REF_KEYS:
            if str(record.get(ref_key, "")).strip() == spec:
                return True

    candidate = task_root / spec
    return candidate.exists()
