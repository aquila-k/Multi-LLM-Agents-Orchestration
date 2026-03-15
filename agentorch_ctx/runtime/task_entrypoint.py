from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.artifact_store import ArtifactStore
from agentorch_ctx.runtime.config_loader import resolve_runtime_config
from agentorch_ctx.runtime.context_bridge import load_task_context
from agentorch_ctx.runtime.manifest_store import (
    build_manifest_snapshot,
    build_pause_confirm,
)
from agentorch_ctx.runtime.pathing import state_root
from agentorch_ctx.runtime.prompt_assembly import assemble_prompt_bundle
from agentorch_ctx.runtime.renderers.markdown import render_markdown_document
from agentorch_ctx.runtime.shell_digest import derive_shell_digest, persist_shell_digest

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
    "phase_options",
    "selectors",
    "assembly_options",
    "metadata",
}
STATE_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class EntryPointResult:
    task_id: str
    request_path: Path
    controller_state_path: Path
    intake_snapshot_dir: Path
    shell_summary: str
    stop_and_confirm: bool


class RequestValidationError(ValueError):
    pass


def run_task_from_request(*, request_path: Path, root_dir: Path) -> EntryPointResult:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    validate_request(request)
    task_id = request["task_id"]
    os.environ["CONTEXTS_CURRENT_TASK_ID"] = task_id
    try:
        if request["workflow_intent"] == "resume":
            return _run_resume_task_from_request(
                request=request,
                request_path=request_path,
                root_dir=root_dir,
            )

        stored = load_task_context(
            root_dir=root_dir,
            task_id=task_id,
            include_project=True,
            max_bytes=8000,
        )
        if stored:
            if not isinstance(request.get("operator_context"), dict):
                request["operator_context"] = {}
            revision = _extract_stored_revision(stored)
            request["operator_context"]["stored_context"] = stored
            request["operator_context"]["stored_context_revision"] = revision
            request["operator_context"]["_contexts_revision"] = revision
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        task_root = Path(request["artifacts"]["task_root"])
        state_dir = Path(request["artifacts"]["state_dir"])
        shell_digest_dir = task_root / "shell-digests"
        intake_snapshot_dir = task_root / "intake"
        shell_digest_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        approval_required = bool(request["constraints"].get("approvals_required"))
        approved_marker = request["selectors"].get("approval_continuation")
        now = _isoformat(datetime.now(timezone.utc))
        phase = _resolve_phase(request)
        artifact_store = ArtifactStore(root_dir)
        config_resolution = resolve_runtime_config(root_dir=root_dir, request=request)
        resolved_config_record = artifact_store.write_json_artifact(
            task_id=task_id,
            family="resolved-config",
            artifact_type="resolved_config",
            payload=config_resolution.resolved_config,
            filename="resolved-config-intake.json",
            phase=phase,
            step="intake",
        )
        routing_record = artifact_store.write_json_artifact(
            task_id=task_id,
            family="routing",
            artifact_type="routing_result",
            payload=config_resolution.routing_result,
            filename="routing-result-intake.json",
            phase=phase,
            step="intake",
        )
        prompt_bundle = assemble_prompt_bundle(
            request=request,
            resolved_config=config_resolution.resolved_config,
            routing_result=config_resolution.routing_result,
            summary_input_refs=[
                str(request_path),
                str(resolved_config_record.path),
                str(routing_record.path),
            ],
            step_id=request["selectors"].get("step", "intake"),
        )
        prompt_record = artifact_store.write_json_artifact(
            task_id=task_id,
            family="prompts",
            artifact_type="prompt_bundle",
            payload=prompt_bundle,
            filename="prompt-bundle-intake.json",
            phase=phase,
            step="intake",
        )

        selected_strategy = config_resolution.resolved_config["strategy"][
            "selectedStrategyId"
        ]
        selected_provider = config_resolution.resolved_config["provider"]["provider"]
        selected_model = config_resolution.resolved_config["provider"]["modelRef"]
        approval_stop = approval_required and not approved_marker
        routing_stop = bool(config_resolution.routing_result["requiresHumanConfirm"])
        stop_and_confirm = approval_stop or routing_stop
        blocked_reason = _blocked_reason(
            approval_stop=approval_stop,
            routing_stop=routing_stop,
            routing_result=config_resolution.routing_result,
        )
        shell_summary = _build_shell_summary(
            request,
            stop_and_confirm,
            selected_strategy=selected_strategy,
            selected_provider=selected_provider,
            selected_model=selected_model,
            blocked_reason=blocked_reason,
        )

        controller_state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "task_id": task_id,
            "active_phase": phase,
            "active_step": request["selectors"].get("step", "intake"),
            "active_strategy": selected_strategy,
            "current_status": "blocked" if stop_and_confirm else "running",
            "last_successful_artifact_refs": [
                str(request_path),
                str(resolved_config_record.path),
                str(routing_record.path),
                str(prompt_record.path),
            ],
            "pending_approval_state": {
                "required": approval_required,
                "status": _approval_status(approval_required, approved_marker),
                "marker": approved_marker,
                "updated_at": now,
            },
            "retry_counters": {},
            "resume_selectors": {
                **request["selectors"],
                "strategy": selected_strategy,
            },
            "latest_shell_digest_refs": [],
            "blocked_reason": blocked_reason,
            "failure_class": "",
            "resume_hint": request["selectors"].get("resume_from", ""),
            "updated_at": now,
        }
        controller_state_path = state_dir / "controller-state.json"
        controller_state_path.write_text(
            json.dumps(controller_state, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        persisted_shell_digest = persist_shell_digest(
            root_dir=root_dir,
            task_id=task_id,
            shell_digest=derive_shell_digest(
                task_id=task_id,
                concise_summary=shell_summary,
            ),
            phase=phase,
            step=request["selectors"].get("step", "intake"),
            filename="intake-shell-digest.json",
        )
        shell_digest_path = persisted_shell_digest.path
        manifest_path = task_root / "manifests" / "manifest.json"
        summary_path = task_root / "summaries" / "intake-summary.md"
        pause_confirm_path = task_root / "pause-confirm" / "pause-confirm.json"
        artifact_refs = {
            "request": str(request_path),
            "resolvedConfig": str(resolved_config_record.path),
            "routingResult": str(routing_record.path),
            "promptBundle": str(prompt_record.path),
            "shellDigest": str(shell_digest_path),
            "summary": str(summary_path),
            "manifest": str(manifest_path),
        }
        manifest_payload = build_manifest_snapshot(
            request=request,
            resolved_config=config_resolution.resolved_config,
            routing_result=config_resolution.routing_result,
            artifact_refs={
                **artifact_refs,
                "pauseConfirm": str(pause_confirm_path) if stop_and_confirm else "",
            },
            stop_and_confirm=stop_and_confirm,
            blocked_reason=blocked_reason,
        )
        pause_confirm_payload = None
        if stop_and_confirm:
            pause_confirm_payload = build_pause_confirm(
                request=request,
                resolved_config=config_resolution.resolved_config,
                routing_result=config_resolution.routing_result,
                blocked_reason=blocked_reason,
                artifact_refs=artifact_refs,
            )
            artifact_store.write_json_artifact(
                task_id=task_id,
                family="pause-confirm",
                artifact_type="pause_confirm",
                payload=pause_confirm_payload,
                filename="pause-confirm.json",
                phase=phase,
                step=request["selectors"].get("step", "intake"),
            )
            artifact_store.write_text_artifact(
                task_id=task_id,
                family="summaries",
                filename="pause-confirm.md",
                content=render_markdown_document(
                    title="Pause Confirm",
                    payload=pause_confirm_payload,
                ),
            )

        summary_payload = {
            "manifest": manifest_payload,
            "resolvedConfig": {
                "phase": config_resolution.resolved_config["phase"],
                "strategy": selected_strategy,
                "provider": selected_provider,
                "model": selected_model,
                "withHarden": config_resolution.resolved_config["phaseOptions"][
                    "withHarden"
                ],
                "autoAdvance": config_resolution.resolved_config["phaseOptions"][
                    "autoAdvance"
                ],
            },
            "routing": {
                "reasonCodes": config_resolution.routing_result.get("reasonCodes", []),
                "confidence": config_resolution.routing_result.get("confidence", 0.0),
                "hardFiltersApplied": config_resolution.routing_result.get(
                    "hardFiltersApplied", []
                ),
            },
            "pauseConfirm": pause_confirm_payload or {},
        }
        artifact_store.write_text_artifact(
            task_id=task_id,
            family="summaries",
            filename="intake-summary.md",
            content=render_markdown_document(
                title="Collab Intake Summary",
                payload=summary_payload,
            ),
        )
        artifact_store.write_json_artifact(
            task_id=task_id,
            family="manifests",
            artifact_type="manifest_snapshot",
            payload=manifest_payload,
            filename="manifest.json",
            phase=phase,
            step=request["selectors"].get("step", "intake"),
        )

        controller_state["latest_shell_digest_refs"] = [str(shell_digest_path)]
        controller_state["last_successful_artifact_refs"].extend(
            [
                str(manifest_path),
                str(summary_path),
            ]
        )
        controller_state_path.write_text(
            json.dumps(controller_state, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        known_information = {
            "schema_version": STATE_SCHEMA_VERSION,
            "task_id": task_id,
            "user_goal_summary": request["summary"],
            "confirmed_constraints": request["constraints"].get("hard", []),
            "accepted_assumptions": request["constraints"].get("soft", []),
            "rejected_options": [],
            "unresolved_blockers": ["approval required"] if stop_and_confirm else [],
            "source_references": [
                {
                    "source": request["source"]["path"],
                    "kind": "user",
                }
            ],
            "latest_phase_summary": {
                "phase": phase,
                "summary": shell_summary,
                "artifact_ref": str(summary_path),
            },
            "latest_validation_apply_summary": {
                "summary": "request accepted; validation deferred to later phases",
                "validation_ref": "",
                "apply_result_ref": "",
            },
            "latest_shell_digestion_summary": {
                "summary": shell_summary,
                "shell_digest_ref": str(shell_digest_path),
            },
            "entries": [
                {
                    "key": "requested_phase",
                    "value": phase,
                    "status": "observed",
                    "source": str(request_path),
                    "updated_at": now,
                    "affects": ["state", "routing"],
                },
                {
                    "key": "selected_strategy",
                    "value": selected_strategy,
                    "status": "observed",
                    "source": str(routing_record.path),
                    "updated_at": now,
                    "affects": ["routing", "state"],
                },
                {
                    "key": "selected_provider",
                    "value": selected_provider,
                    "status": "observed",
                    "source": str(routing_record.path),
                    "updated_at": now,
                    "affects": ["routing", "execution"],
                },
                {
                    "key": "selected_model",
                    "value": selected_model,
                    "status": "observed",
                    "source": str(routing_record.path),
                    "updated_at": now,
                    "affects": ["routing", "execution"],
                },
                {
                    "key": "resolved_config_ref",
                    "value": str(resolved_config_record.path),
                    "status": "observed",
                    "source": str(resolved_config_record.path),
                    "updated_at": now,
                    "affects": ["routing", "state"],
                },
                {
                    "key": "prompt_bundle_ref",
                    "value": str(prompt_record.path),
                    "status": "observed",
                    "source": str(prompt_record.path),
                    "updated_at": now,
                    "affects": ["prompt", "execution"],
                },
                {
                    "key": "manifest_ref",
                    "value": str(manifest_path),
                    "status": "observed",
                    "source": str(manifest_path),
                    "updated_at": now,
                    "affects": ["state", "resume"],
                },
            ],
            "updated_at": now,
        }
        if stop_and_confirm:
            known_information["entries"].append(
                {
                    "key": "stop_reason",
                    "value": blocked_reason,
                    "status": "observed",
                    "source": (
                        str(routing_record.path) if routing_stop else str(request_path)
                    ),
                    "updated_at": now,
                    "affects": ["approval", "resume", "routing"],
                }
            )
        if approval_stop:
            known_information["entries"].append(
                {
                    "key": "approval_required",
                    "value": request["constraints"].get("approvals_required", []),
                    "status": "observed",
                    "source": str(request_path),
                    "updated_at": now,
                    "affects": ["approval", "resume"],
                }
            )
        if stop_and_confirm:
            known_information["unresolved_blockers"] = [blocked_reason]
        (state_dir / "known-information.json").write_text(
            json.dumps(known_information, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        (state_dir / "approval-state.json").write_text(
            json.dumps(
                controller_state["pending_approval_state"], indent=2, ensure_ascii=True
            )
            + "\n",
            encoding="utf-8",
        )
        (state_dir / "resume-cursor.json").write_text(
            json.dumps(
                {
                    "schema_version": STATE_SCHEMA_VERSION,
                    "phase": phase,
                    "strategy": selected_strategy,
                    "step": request["selectors"].get("step", "intake"),
                    "resume_from": request["selectors"].get("resume_from", ""),
                    "approval_continuation": approved_marker or "",
                    "artifact_ref": str(manifest_path),
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (state_dir / "environment-signature.json").write_text(
            json.dumps(
                {
                    "cwd": str(root_dir.resolve()),
                    "platform": "python",
                    "python": f"{__import__('sys').version_info.major}.{__import__('sys').version_info.minor}",
                    "shell": "claude_code",
                    "timestamp": now,
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )

        _update_task_registry(
            root_dir=root_dir,
            request=request,
            status=controller_state["current_status"],
            updated_at=now,
        )

        return EntryPointResult(
            task_id=task_id,
            request_path=request_path,
            controller_state_path=controller_state_path,
            intake_snapshot_dir=intake_snapshot_dir,
            shell_summary=shell_summary,
            stop_and_confirm=stop_and_confirm,
        )
    finally:
        os.environ.pop("CONTEXTS_CURRENT_TASK_ID", None)


def _run_resume_task_from_request(
    *,
    request: dict[str, Any],
    request_path: Path,
    root_dir: Path,
) -> EntryPointResult:
    task_id = request["task_id"]
    os.environ["CONTEXTS_CURRENT_TASK_ID"] = task_id
    try:
        return _run_resume_task_from_request_impl(
            request=request,
            request_path=request_path,
            root_dir=root_dir,
        )
    finally:
        os.environ.pop("CONTEXTS_CURRENT_TASK_ID", None)


def _run_resume_task_from_request_impl(
    *,
    request: dict[str, Any],
    request_path: Path,
    root_dir: Path,
) -> EntryPointResult:
    from agentorch_ctx.runtime.context_bridge import load_task_context
    from agentorch_ctx.runtime.phase_runner import PhaseRunner
    from agentorch_ctx.runtime.task_runner import TaskRunner

    # [G02-resume] Refresh stored_context so resumed phases use the latest snapshot.
    task_id = request["task_id"]
    stored = load_task_context(
        root_dir=root_dir,
        task_id=task_id,
        include_project=True,
        max_bytes=8000,
    )
    if stored:
        if not isinstance(request.get("operator_context"), dict):
            request["operator_context"] = {}
        revision = _extract_stored_revision(stored)
        request["operator_context"]["stored_context"] = stored
        request["operator_context"]["stored_context_revision"] = revision
        request["operator_context"]["_contexts_revision"] = revision
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    task_id = request["task_id"]
    state_dir = Path(request["artifacts"]["state_dir"])
    controller_state_path = state_dir / "controller-state.json"
    known_information_path = state_dir / "known-information.json"
    if not controller_state_path.exists() or not known_information_path.exists():
        raise RequestValidationError(f"resume task state missing for {task_id}")

    controller_state = json.loads(controller_state_path.read_text(encoding="utf-8"))
    approval_state = controller_state.get("pending_approval_state", {})
    approval_marker = request["selectors"].get("approval_continuation")
    if approval_state.get("required") and not approval_marker:
        raise RequestValidationError(
            "approval-gated resume requires approval_continuation"
        )

    resumed_controller = TaskRunner(root_dir).resume(
        task_id=task_id,
        approval_outcome="approved_continue" if approval_marker else None,
        approval_marker=approval_marker,
        selectors=request.get("selectors", {}),
    )
    if resumed_controller.get("current_status") != "running":
        known_information = json.loads(
            known_information_path.read_text(encoding="utf-8")
        )
        shell_summary = known_information.get("latest_shell_digestion_summary", {}).get(
            "summary", ""
        )
        updated_at = _isoformat(datetime.now(timezone.utc))
        _update_task_registry(
            root_dir=root_dir,
            request=request,
            status=resumed_controller.get("current_status", "blocked"),
            updated_at=updated_at,
        )
        return EntryPointResult(
            task_id=task_id,
            request_path=request_path,
            controller_state_path=controller_state_path,
            intake_snapshot_dir=Path(request["artifacts"]["intake_dir"]),
            shell_summary=shell_summary,
            stop_and_confirm=resumed_controller.get("current_status") == "blocked",
        )
    phase_result = PhaseRunner(root_dir).run(request_path=request_path)
    known_information = json.loads(known_information_path.read_text(encoding="utf-8"))
    shell_summary = known_information.get("latest_shell_digestion_summary", {}).get(
        "summary", ""
    )
    updated_at = _isoformat(datetime.now(timezone.utc))
    _update_task_registry(
        root_dir=root_dir,
        request=request,
        status=phase_result.controller_status,
        updated_at=updated_at,
    )
    return EntryPointResult(
        task_id=task_id,
        request_path=request_path,
        controller_state_path=controller_state_path,
        intake_snapshot_dir=Path(request["artifacts"]["intake_dir"]),
        shell_summary=shell_summary,
        stop_and_confirm=phase_result.controller_status == "blocked",
    )


def validate_request(request: dict[str, Any]) -> None:
    missing = sorted(REQUEST_REQUIRED_KEYS.difference(request))
    if missing:
        raise RequestValidationError(f"missing request keys: {', '.join(missing)}")
    if request["workflow_intent"] not in {"plan", "impl", "review", "harden", "resume"}:
        raise RequestValidationError("invalid workflow_intent")
    if request["source"].get("kind") not in {"markdown", "json"}:
        raise RequestValidationError("invalid source kind")
    if not isinstance(request["summary"], str) or not request["summary"].strip():
        raise RequestValidationError("summary must be a non-empty string")
    if request["workflow_intent"] == "resume" and not any(
        request["selectors"].get(key) for key in ("phase", "step", "resume_from")
    ):
        raise RequestValidationError(
            "resume requests require phase, step, or resume_from"
        )
    if (
        request["workflow_intent"] == "resume"
        and request["source"].get("kind") != "json"
    ):
        raise RequestValidationError("resume requests require a JSON source kind")
    if (
        request["phase_options"].get("with_harden")
        and _resolve_phase(request) != "review"
    ):
        raise RequestValidationError("with_harden is only valid for review")


def _resolve_phase(request: dict[str, Any]) -> str:
    selector_phase = request["selectors"].get("phase")
    if selector_phase:
        return selector_phase
    workflow_intent = request["workflow_intent"]
    return "plan" if workflow_intent == "resume" else workflow_intent


def _approval_status(required: bool, approved_marker: str | None) -> str:
    if not required:
        return "not_required"
    if approved_marker:
        return "approved"
    return "pending"


def _blocked_reason(
    *,
    approval_stop: bool,
    routing_stop: bool,
    routing_result: dict[str, Any],
) -> str:
    if approval_stop:
        return "blocked_for_approval"
    if routing_stop:
        reason_codes = routing_result.get("reasonCodes", [])
        return reason_codes[0] if reason_codes else "provider_capability_mismatch"
    return ""


def _build_shell_summary(
    request: dict[str, Any],
    stop_and_confirm: bool,
    *,
    selected_strategy: str,
    selected_provider: str | None,
    selected_model: str | None,
    blocked_reason: str,
) -> str:
    phase = _resolve_phase(request)
    step = request["selectors"].get("step", "intake")
    provider_suffix = (
        f" strategy={selected_strategy} provider={selected_provider} model={selected_model}"
        if selected_provider and selected_model
        else f" strategy={selected_strategy}"
    )
    if stop_and_confirm:
        return (
            f"Intake accepted for {request['task_id']} but STOP_AND_CONFIRM is required "
            f"before phase={phase} step={step}; reason={blocked_reason}.{provider_suffix}"
        )
    return (
        f"Intake accepted for {request['task_id']}; phase={phase} step={step} is ready."
        f"{provider_suffix}"
    )


def _extract_stored_revision(stored: dict[str, Any]) -> int:
    top_level = stored.get("task_snapshot_revision")
    if isinstance(top_level, int):
        return top_level
    snapshot = stored.get("task_snapshot") or {}
    if isinstance(snapshot, dict):
        rev = snapshot.get("revision")
        if isinstance(rev, int):
            return rev
    return 0


def _update_task_registry(
    *, root_dir: Path, request: dict[str, Any], status: str, updated_at: str
) -> None:
    registry_path = state_root(root_dir) / "task-registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        registry = {
            "schema_version": STATE_SCHEMA_VERSION,
            "tasks": {},
            "updated_at": None,
        }
    registry.setdefault("tasks", {})[request["task_id"]] = {
        "summary": request["summary"],
        "workflow_intent": request["workflow_intent"],
        "phase": _resolve_phase(request),
        "status": status,
        "request_path": str(request["artifacts"]["request_dir"]),
        "state_dir": str(request["artifacts"]["state_dir"]),
        "updated_at": updated_at,
    }
    registry["updated_at"] = updated_at
    registry_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
