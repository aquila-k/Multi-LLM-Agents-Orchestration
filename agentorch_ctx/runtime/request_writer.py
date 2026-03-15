from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentorch_ctx.interfaces.skill_entry import (
    ArtifactDestinations,
    AssemblyOptions,
    CanonicalDispatchRequest,
    ConstraintSpec,
    DispatchSelectors,
    OperatorContext,
    OutputSpec,
    PhaseOptions,
    SourceKind,
    TargetSpec,
    WorkflowIntent,
)
from agentorch_ctx.runtime.pathing import task_artifacts_dir, task_state_dir

SCHEMA_VERSION = "1.0.0"
PROMPT_VERSION = "1.0.0"
HOST_NAME = "claude_code"


@dataclass(frozen=True)
class PreparedRequest:
    task_id: str
    request: CanonicalDispatchRequest
    request_path: Path
    intake_snapshot_dir: Path
    controller_state_path: Path
    state_dir: Path
    shell_digest_dir: Path


@dataclass(frozen=True)
class TaskPaths:
    task_root: Path
    intake_dir: Path
    request_dir: Path
    response_dir: Path
    state_dir: Path
    shell_digest_dir: Path
    controller_state_path: Path


def prepare_request(
    *,
    root_dir: Path,
    source_path: Path,
    workflow_intent: WorkflowIntent,
    source_kind: SourceKind,
    selectors: DispatchSelectors | None = None,
    targets: TargetSpec | None = None,
    constraints: ConstraintSpec | None = None,
    operator_context: OperatorContext | None = None,
    phase_options: PhaseOptions | None = None,
    assembly_options: AssemblyOptions | None = None,
) -> PreparedRequest:
    resolved_source = source_path.expanduser().resolve()
    if not resolved_source.exists():
        raise FileNotFoundError(f"task source not found: {resolved_source}")

    now = datetime.now(timezone.utc)
    source_payload = _load_source_payload(resolved_source, source_kind)
    task_id = _resolve_task_id(
        root_dir=root_dir,
        source_payload=source_payload,
        source_path=resolved_source,
        source_kind=source_kind,
        workflow_intent=workflow_intent,
        now=now,
    )
    task_paths = _ensure_task_paths(root_dir, task_id)
    merged_selectors = {**(source_payload.get("selectors") or {}), **(selectors or {})}
    merged_targets = _merge_dicts(source_payload.get("targets"), targets)
    merged_constraints = _merge_dicts(source_payload.get("constraints"), constraints)
    merged_operator_context = _merge_dicts(
        source_payload.get("operator_context"), operator_context
    )
    merged_phase_options = _merge_phase_options(
        source_payload.get("phase_options"), phase_options, workflow_intent
    )
    merged_assembly_options = _merge_assembly_options(
        source_payload.get("assembly_options"),
        assembly_options,
    )
    output_spec = _merge_output(source_payload.get("output"), workflow_intent)

    summary = _derive_summary(source_payload, resolved_source, source_kind)
    request: CanonicalDispatchRequest = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "source": {
            "path": str(resolved_source),
            "kind": source_kind,
        },
        "workflow_intent": workflow_intent,
        "summary": summary,
        "targets": merged_targets,
        "constraints": merged_constraints,
        "output": output_spec,
        "artifacts": _artifact_destinations(task_paths),
        "operator_context": merged_operator_context,
        "phase_options": merged_phase_options,
        "selectors": merged_selectors,
        "assembly_options": merged_assembly_options,
        "metadata": {
            "created_at": _isoformat(now),
            "source_canonicalized_at": _isoformat(now),
            "host": HOST_NAME,
            "cwd": str(root_dir.resolve()),
        },
    }

    request_file = (
        task_paths.request_dir / f"request-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    request_file.write_text(json.dumps(request, indent=2, ensure_ascii=True) + "\n")

    snapshot_suffix = ".md" if source_kind == "markdown" else ".json"
    snapshot_path = task_paths.intake_dir / f"source-snapshot{snapshot_suffix}"
    snapshot_path.write_text(resolved_source.read_text(), encoding="utf-8")

    intake_metadata = {
        "task_id": task_id,
        "source_path": str(resolved_source),
        "source_kind": source_kind,
        "workflow_intent": workflow_intent,
        "snapshot_path": str(snapshot_path),
        "request_path": str(request_file),
        "selectors": merged_selectors,
        "created_at": _isoformat(now),
    }
    (task_paths.intake_dir / "intake-metadata.json").write_text(
        json.dumps(intake_metadata, indent=2, ensure_ascii=True) + "\n"
    )

    return PreparedRequest(
        task_id=task_id,
        request=request,
        request_path=request_file,
        intake_snapshot_dir=task_paths.intake_dir,
        controller_state_path=task_paths.controller_state_path,
        state_dir=task_paths.state_dir,
        shell_digest_dir=task_paths.shell_digest_dir,
    )


def _build_task_id(source_path: Path, now: datetime) -> str:
    stem = _slugify(source_path.stem) or "task"
    return f"{stem}-{now.strftime('%Y%m%dT%H%M%SZ')}"


def _resolve_task_id(
    *,
    root_dir: Path,
    source_payload: dict[str, Any],
    source_path: Path,
    source_kind: SourceKind,
    workflow_intent: WorkflowIntent,
    now: datetime,
) -> str:
    if workflow_intent != "resume":
        return _build_task_id(source_path, now)
    if source_kind != "json":
        raise ValueError("resume requests require a JSON source payload")
    resume_task_id = source_payload.get("task_id")
    if not isinstance(resume_task_id, str) or not resume_task_id.strip():
        raise ValueError("resume requests require source JSON with task_id")
    controller_path = task_state_dir(root_dir, resume_task_id) / "controller-state.json"
    if not controller_path.exists():
        raise FileNotFoundError(f"resume task state not found: {resume_task_id}")
    return resume_task_id.strip()


def _ensure_task_paths(root_dir: Path, task_id: str) -> TaskPaths:
    task_root = task_artifacts_dir(root_dir, task_id)
    intake_dir = task_root / "intake"
    request_dir = task_root / "requests"
    response_dir = task_root / "responses"
    shell_digest_dir = task_root / "shell-digests"
    state_dir = task_state_dir(root_dir, task_id)
    for path in (intake_dir, request_dir, response_dir, shell_digest_dir, state_dir):
        path.mkdir(parents=True, exist_ok=True)
    return TaskPaths(
        task_root=task_root,
        intake_dir=intake_dir,
        request_dir=request_dir,
        response_dir=response_dir,
        state_dir=state_dir,
        shell_digest_dir=shell_digest_dir,
        controller_state_path=state_dir / "controller-state.json",
    )


def _load_source_payload(source_path: Path, source_kind: SourceKind) -> dict[str, Any]:
    if source_kind == "json":
        loaded = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("json task source must be an object")
        return loaded
    return {"summary": _first_non_empty_line(source_path.read_text(encoding="utf-8"))}


def _merge_dicts(base: Any, override: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(base, dict):
        merged.update(base)
    if isinstance(override, dict):
        merged.update(override)
    return merged


def _merge_output(base: Any, workflow_intent: WorkflowIntent) -> OutputSpec:
    payload = base if isinstance(base, dict) else {}
    preferred = payload.get("preferred_mode", _default_preferred_mode(workflow_intent))
    allowed = payload.get("allowed_modes", [preferred])
    if preferred not in allowed:
        allowed = [preferred, *[mode for mode in allowed if mode != preferred]]
    return {
        "preferred_mode": preferred,
        "allowed_modes": allowed,
        "operations_required": bool(
            payload.get("operations_required", workflow_intent == "impl")
        ),
    }


def _merge_phase_options(
    base: Any, override: Any, workflow_intent: WorkflowIntent
) -> PhaseOptions:
    payload = _merge_dicts(base, override)
    with_harden = bool(payload.get("with_harden", False))
    auto_advance = bool(payload.get("auto_advance", False))
    budget_profile_ref = payload.get("budget_profile_ref", "budget-bootstrap")
    if workflow_intent != "review":
        with_harden = False
    return {
        "with_harden": with_harden,
        "auto_advance": auto_advance,
        "budget_profile_ref": budget_profile_ref,
    }


def _merge_assembly_options(base: Any, override: Any) -> AssemblyOptions:
    payload = _merge_dicts(base, override)
    return {
        "prompt_version": str(payload.get("prompt_version", PROMPT_VERSION)),
        "schema_version": str(payload.get("schema_version", SCHEMA_VERSION)),
        "concise_shell_summary": bool(payload.get("concise_shell_summary", True)),
    }


def _derive_summary(
    source_payload: dict[str, Any], source_path: Path, source_kind: SourceKind
) -> str:
    summary = source_payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if source_kind == "markdown":
        return _first_non_empty_line(source_path.read_text(encoding="utf-8"))
    return source_path.stem


def _artifact_destinations(task_paths: TaskPaths) -> ArtifactDestinations:
    return {
        "task_root": str(task_paths.task_root),
        "intake_dir": str(task_paths.intake_dir),
        "request_dir": str(task_paths.request_dir),
        "response_dir": str(task_paths.response_dir),
        "state_dir": str(task_paths.state_dir),
    }


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return "Untitled task"


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return normalized.strip("-")


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _default_preferred_mode(workflow_intent: WorkflowIntent) -> str:
    if workflow_intent == "impl":
        return "patch"
    return "report_only"
