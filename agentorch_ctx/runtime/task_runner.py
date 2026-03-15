from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from agentorch_ctx.runtime.artifact_store import ArtifactStore
from agentorch_ctx.runtime.decisions import DecisionLog
from agentorch_ctx.runtime.events import EventLog
from agentorch_ctx.runtime.manifest_store import (
    build_runtime_pause_confirm,
    extend_manifest_snapshot,
)
from agentorch_ctx.runtime.pathing import task_artifacts_dir, task_state_dir
from agentorch_ctx.runtime.renderers.markdown import render_markdown_document
from agentorch_ctx.runtime.shell_digest import (
    derive_shell_digest,
    ingest_shell_digest,
    persist_shell_digest,
)
from agentorch_ctx.runtime.state_machine import StateMachine
from agentorch_ctx.runtime.suppression import SuppressionTracker


class TaskRunner:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.store = ArtifactStore(self.root_dir)
        self.events = EventLog(self.root_dir)
        self.decisions = DecisionLog(self.root_dir)
        self.state_machine = StateMachine()
        self.suppression = SuppressionTracker()

    def start_phase(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        strategy: str,
        attempt: int = 1,
        run: int = 1,
    ) -> dict[str, Any]:
        controller = self._load_controller(task_id)
        before = controller.get("current_status", "pending")
        if before == "pending":
            self.state_machine.ensure_task_transition("pending", "running")
        elif before in {"blocked", "partial"}:
            self.state_machine.ensure_task_transition(before, "running")
        controller.update(
            {
                "active_phase": phase,
                "active_step": step,
                "active_strategy": strategy,
                "current_status": "running",
                "updated_at": _isoformat(datetime.now(timezone.utc)),
            }
        )
        self._write_controller(task_id, controller)
        self._write_approval_state(
            task_id, controller.get("pending_approval_state", {})
        )
        self._write_resume_cursor(task_id, controller, attempt=attempt, run=run)
        self._sync_manifest_snapshot(task_id)
        self._append_event(
            task_id=task_id,
            event_type="phase_started",
            phase=phase,
            step=step,
            payload={"strategy": strategy},
        )
        return controller

    def pause_step(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        reason: str,
        resume_from: str,
    ) -> dict[str, Any]:
        controller = self._load_controller(task_id)
        self.state_machine.ensure_step_transition(
            controller.get("current_status", "running"), "blocked"
        )
        now = _isoformat(datetime.now(timezone.utc))
        digest_filename = f"shell-digest-{phase}-{step}-{_compact_timestamp(now)}.json"
        persisted_digest = persist_shell_digest(
            root_dir=self.root_dir,
            task_id=task_id,
            shell_digest=derive_shell_digest(
                task_id=task_id,
                concise_summary=f"Task paused; phase={phase} step={step} blocked reason={reason}.",
            ),
            phase=phase,
            step=step,
            filename=digest_filename,
        )
        latest_shell_digest_refs = list(controller.get("latest_shell_digest_refs", []))
        latest_shell_digest_refs.append(str(persisted_digest.path))
        controller.update(
            {
                "active_phase": phase,
                "active_step": step,
                "current_status": "blocked",
                "blocked_reason": reason,
                "resume_hint": resume_from,
                "resume_selectors": {
                    **controller.get("resume_selectors", {}),
                    "phase": phase,
                    "step": step,
                    "resume_from": resume_from,
                },
                "latest_shell_digest_refs": latest_shell_digest_refs,
                "updated_at": now,
            }
        )
        self._write_controller(task_id, controller)
        known_information = self._load_known_information(task_id)
        known_information.setdefault("unresolved_blockers", [])
        if reason not in known_information["unresolved_blockers"]:
            known_information["unresolved_blockers"].append(reason)
        known_information = ingest_shell_digest(
            known_information=known_information,
            shell_digest=persisted_digest.payload,
        )
        self._write_known_information(task_id, known_information)
        self._write_approval_state(
            task_id, controller.get("pending_approval_state", {})
        )
        self._write_resume_cursor(task_id, controller)
        self._sync_manifest_snapshot(
            task_id,
            blocker_refs=[str(persisted_digest.path)],
        )
        self._append_event(
            task_id=task_id,
            event_type="step_paused",
            phase=phase,
            step=step,
            payload={"reason": reason, "resume_from": resume_from},
        )
        return controller

    def resume(
        self,
        *,
        task_id: str,
        approval_outcome: str | None = None,
        approval_marker: str | None = None,
        selectors: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        controller = self._load_controller(task_id)
        blocked_reason = str(controller.get("blocked_reason", ""))
        if (
            "approval" in blocked_reason
            and not approval_outcome
            and not approval_marker
        ):
            logger.warning(
                "resume requested without required approval decision",
                extra={"task_id": task_id, "blocked_reason": blocked_reason},
            )
            controller["current_status"] = "blocked"
            controller["resume_hint"] = "provide_approval_decision"
            self._write_controller(task_id, controller)
            return controller
        known_information = self._load_known_information(task_id)
        if not known_information.get("latest_phase_summary"):
            raise ValueError("known information is insufficient for resume")
        before = controller.get("current_status", "blocked")
        if before not in {"blocked", "partial"}:
            raise ValueError(f"task is not resumable from state {before}")
        approval_state = controller.get("pending_approval_state", {})
        latest_shell_summary = known_information.get(
            "latest_shell_digestion_summary", {}
        ).get("summary", "")
        latest_shell_refs = controller.get("latest_shell_digest_refs", [])
        if approval_state.get("required") and (
            not latest_shell_summary or not latest_shell_refs
        ):
            raise ValueError(
                "approval resume requires persisted shell digestion summary"
            )
        if selectors:
            conflict_reason = self._resume_override_conflict(controller, selectors)
            if conflict_reason:
                self._record_resume_override_conflict(
                    task_id=task_id,
                    controller=controller,
                    selectors=selectors,
                    reason=conflict_reason,
                )
                return controller
        # §11.4: propagate unresolved blocker invariants into resume cursor
        unresolved = known_information.get("unresolved_blockers", [])
        if unresolved:
            logger.info(
                "resuming with unresolved blockers; propagating to resume cursor",
                extra={"task_id": task_id, "unresolved_blockers": unresolved},
            )
            controller["unresolved_blockers_at_resume"] = list(unresolved)
        self.state_machine.ensure_task_transition(before, "running")
        previous_phase = controller.get("active_phase", "")
        previous_step = controller.get("active_step", "")
        previous_strategy = controller.get("active_strategy", "")
        controller["current_status"] = "running"
        controller["blocked_reason"] = ""
        if selectors:
            merged_selectors = {
                **controller.get("resume_selectors", {}),
                **selectors,
            }
            controller["resume_selectors"] = merged_selectors
            if merged_selectors.get("phase"):
                controller["active_phase"] = merged_selectors["phase"]
            if merged_selectors.get("step"):
                controller["active_step"] = merged_selectors["step"]
            if merged_selectors.get("strategy"):
                controller["active_strategy"] = merged_selectors["strategy"]
            if merged_selectors.get("resume_from"):
                controller["resume_hint"] = merged_selectors["resume_from"]
        controller["pending_approval_state"] = {
            **approval_state,
            "status": (
                "approved"
                if approval_outcome
                else controller.get("pending_approval_state", {}).get(
                    "status", "not_required"
                )
            ),
            "marker": approval_marker
            or controller.get("pending_approval_state", {}).get("marker", ""),
            "updated_at": _isoformat(datetime.now(timezone.utc)),
        }
        controller["updated_at"] = _isoformat(datetime.now(timezone.utc))
        self._write_controller(task_id, controller)
        self._write_approval_state(task_id, controller["pending_approval_state"])
        self._write_resume_cursor(task_id, controller)
        if self._is_mid_phase_strategy_switch(
            previous_phase=previous_phase,
            previous_step=previous_step,
            previous_strategy=previous_strategy,
            next_strategy=controller.get("active_strategy", ""),
        ):
            self._record_strategy_switch(
                task_id=task_id,
                from_phase=previous_phase,
                from_strategy=previous_strategy,
                to_phase=controller.get("active_phase", previous_phase),
                to_strategy=controller.get("active_strategy", previous_strategy),
                reason_code="resume_selector_override",
            )
            return self.pause_step(
                task_id=task_id,
                phase=controller.get("active_phase", previous_phase),
                step=controller.get("active_step", previous_step or "intake"),
                reason="strategy_changed_requires_redo",
                resume_from=controller.get("active_step", previous_step or "intake"),
            )
        self._sync_manifest_snapshot(task_id)
        if approval_outcome:
            self._append_decision(
                task_id=task_id,
                decision_type="approval_resume",
                phase=controller.get("active_phase", "unknown"),
                step=controller.get("active_step", "unknown"),
                outcome=approval_outcome,
                payload={
                    "approval_marker": approval_marker or "",
                    "selectors": selectors or {},
                },
            )
        self._append_event(
            task_id=task_id,
            event_type="task_resumed",
            phase=controller.get("active_phase", "unknown"),
            step=controller.get("active_step", "unknown"),
            payload={
                "resume_from": controller.get("resume_selectors", {}).get(
                    "resume_from", ""
                ),
                "selectors": selectors or {},
            },
        )
        return controller

    def complete_step(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        artifact_ref: str,
        partial: bool = False,
    ) -> dict[str, Any]:
        controller = self._load_controller(task_id)
        next_status = "partial" if partial else "running"
        current_status = controller.get("current_status", "running")
        if current_status != next_status:
            self.state_machine.ensure_step_transition(current_status, next_status)
        now = _isoformat(datetime.now(timezone.utc))
        refs = list(controller.get("last_successful_artifact_refs", []))
        refs.append(artifact_ref)
        controller.update(
            {
                "active_phase": phase,
                "active_step": step,
                "current_status": next_status,
                "last_successful_artifact_refs": refs,
                "updated_at": now,
            }
        )
        self._write_controller(task_id, controller)
        known_information = self._load_known_information(task_id)
        known_information["latest_phase_summary"] = {
            "phase": phase,
            "summary": f"step {step} completed",
            "artifact_ref": artifact_ref,
        }
        known_information["updated_at"] = now
        self._write_known_information(task_id, known_information)
        self._write_approval_state(
            task_id, controller.get("pending_approval_state", {})
        )
        self._write_resume_cursor(task_id, controller, artifact_ref=artifact_ref)
        self._sync_manifest_snapshot(task_id)
        self._append_event(
            task_id=task_id,
            event_type="step_completed",
            phase=phase,
            step=step,
            payload={"artifact_ref": artifact_ref, "partial": partial},
        )
        return controller

    def record_retry_analysis(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        attempt: int,
        run: int,
        retry_analysis: dict[str, Any],
        artifact_ref: str,
    ) -> dict[str, Any]:
        controller = self._load_controller(task_id)
        retry_counters = controller.get("retry_counters", {})
        if not isinstance(retry_counters, dict):
            retry_counters = {}
        key = f"{phase}:{step}"
        current = retry_counters.get(key, {})
        if not isinstance(current, dict):
            current = {}
        total = int(current.get("total", 0)) + 1
        auto_eligible = int(current.get("auto_retry_eligible", 0))
        if retry_analysis.get("auto_retry_eligible"):
            auto_eligible += 1
        by_condition = current.get("by_condition", {})
        if not isinstance(by_condition, dict):
            by_condition = {}
        condition = str(retry_analysis.get("retry_condition", "default"))
        by_condition[condition] = int(by_condition.get(condition, 0)) + 1
        retry_counters[key] = {
            "phase": phase,
            "step": step,
            "latest_attempt": attempt,
            "latest_run": run,
            "latest_analysis_ref": artifact_ref,
            "latest_reason": str(retry_analysis.get("reason", "")),
            "latest_retry_condition": condition,
            "total": total,
            "auto_retry_eligible": auto_eligible,
            "by_condition": by_condition,
        }
        controller["retry_counters"] = retry_counters
        controller["updated_at"] = _isoformat(datetime.now(timezone.utc))
        self._write_controller(task_id, controller)
        return controller

    def _load_controller(self, task_id: str) -> dict[str, Any]:
        path = self._state_dir(task_id) / "controller-state.json"
        if not path.exists():
            raise FileNotFoundError(f"missing controller state for task {task_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_controller(self, task_id: str, payload: dict[str, Any]) -> None:
        path = self._state_dir(task_id) / "controller-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )

    def _load_known_information(self, task_id: str) -> dict[str, Any]:
        path = self._state_dir(task_id) / "known-information.json"
        if not path.exists():
            raise FileNotFoundError(f"missing known information for task {task_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_known_information(self, task_id: str, payload: dict[str, Any]) -> None:
        path = self._state_dir(task_id) / "known-information.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )

    def _write_approval_state(self, task_id: str, payload: dict[str, Any]) -> None:
        path = self._state_dir(task_id) / "approval-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )

    def _write_resume_cursor(
        self,
        task_id: str,
        controller: dict[str, Any],
        *,
        artifact_ref: str | None = None,
        attempt: int | None = None,
        run: int | None = None,
    ) -> None:
        existing = self._load_optional_json(
            self._state_dir(task_id) / "resume-cursor.json"
        )
        payload = {
            "schema_version": "1.0.0",
            "phase": controller.get("active_phase", existing.get("phase", "")),
            "strategy": controller.get("active_strategy", existing.get("strategy", "")),
            "step": controller.get("active_step", existing.get("step", "")),
            "attempt": attempt if attempt is not None else existing.get("attempt", 1),
            "run": run if run is not None else existing.get("run", 1),
            "resume_from": controller.get("resume_selectors", {}).get(
                "resume_from", existing.get("resume_from", "")
            ),
            "approval_continuation": controller.get("pending_approval_state", {}).get(
                "marker", existing.get("approval_continuation", "")
            ),
            "artifact_ref": artifact_ref or existing.get("artifact_ref", ""),
            "unresolved_blockers": controller.get(
                "unresolved_blockers_at_resume",
                existing.get("unresolved_blockers", []),
            ),
            "updated_at": controller.get(
                "updated_at", _isoformat(datetime.now(timezone.utc))
            ),
        }
        path = self._state_dir(task_id) / "resume-cursor.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )

    def _state_dir(self, task_id: str) -> Path:
        return task_state_dir(self.root_dir, task_id)

    def _load_optional_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _sync_manifest_snapshot(
        self,
        task_id: str,
        *,
        blocker_refs: list[str] | None = None,
        artifact_refs: dict[str, str] | None = None,
        plan_artifact_refs: dict[str, str] | None = None,
        final_report_ref: str | None = None,
    ) -> None:
        manifest_path = (
            task_artifacts_dir(self.root_dir, task_id) / "manifests" / "manifest.json"
        )
        if not manifest_path.exists():
            return
        controller = self._load_controller(task_id)
        known_information = self._load_known_information(task_id)
        approval_state = self._load_optional_json(
            self._state_dir(task_id) / "approval-state.json"
        )
        resume_cursor = self._load_optional_json(
            self._state_dir(task_id) / "resume-cursor.json"
        )
        session_state = self._load_optional_json(
            self._state_dir(task_id) / "session-state.json"
        )
        manifest_envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = manifest_envelope.get("payload", manifest_envelope)
        updated = extend_manifest_snapshot(
            manifest=manifest,
            phase=controller.get(
                "active_phase", manifest.get("activePhase", "unknown")
            ),
            step=controller.get("active_step", manifest.get("activeStep", "unknown")),
            attempt=int(resume_cursor.get("attempt", manifest.get("attempt", 1))),
            run=int(resume_cursor.get("run", manifest.get("run", 1))),
            blocked_reason=controller.get("blocked_reason", ""),
            session_refs={
                "provider": session_state.get(
                    "provider", manifest.get("sessionRefs", {}).get("provider")
                ),
                "sessionRef": session_state.get(
                    "sessionRef", manifest.get("sessionRefs", {}).get("sessionRef")
                ),
            },
            artifact_refs=artifact_refs or {},
            active_strategy_id=controller.get(
                "active_strategy", manifest.get("activeStrategyId")
            ),
            controller_status=controller.get(
                "current_status", manifest.get("controllerStatus")
            ),
            approval_state=approval_state or manifest.get("approvalState", {}),
            resume_cursor={
                "phase": resume_cursor.get("phase", controller.get("active_phase", "")),
                "strategy": resume_cursor.get(
                    "strategy", controller.get("active_strategy", "")
                ),
                "step": resume_cursor.get("step", controller.get("active_step", "")),
                "attempt": resume_cursor.get("attempt", manifest.get("attempt", 1)),
                "run": resume_cursor.get("run", manifest.get("run", 1)),
                "resumeFrom": resume_cursor.get("resume_from", ""),
                "approvalContinuation": resume_cursor.get("approval_continuation", ""),
                "artifactRef": resume_cursor.get("artifact_ref", str(manifest_path)),
            },
            last_successful_artifact_refs=list(
                controller.get("last_successful_artifact_refs", [])
            ),
            latest_validation_apply_summary={
                "summary": known_information.get(
                    "latest_validation_apply_summary", {}
                ).get("summary", ""),
                "validationRef": known_information.get(
                    "latest_validation_apply_summary", {}
                ).get("validation_ref", ""),
                "applyResultRef": known_information.get(
                    "latest_validation_apply_summary", {}
                ).get("apply_result_ref", ""),
            },
            latest_phase_summary={
                "phase": known_information.get("latest_phase_summary", {}).get(
                    "phase", ""
                ),
                "summary": known_information.get("latest_phase_summary", {}).get(
                    "summary", ""
                ),
                "artifactRef": known_information.get("latest_phase_summary", {}).get(
                    "artifact_ref", ""
                ),
            },
            latest_shell_digest_refs=list(
                controller.get("latest_shell_digest_refs", [])
            ),
            blocker_refs=(
                blocker_refs
                if blocker_refs is not None
                else manifest.get("blockerRefs", [])
            ),
            composition_mode=manifest.get("compositionMode"),
            plan_artifact_refs=plan_artifact_refs,
            final_report_ref=final_report_ref,
        )
        self.store.write_json_artifact(
            task_id=task_id,
            family="manifests",
            artifact_type="manifest_snapshot",
            payload=updated,
            filename=manifest_path.name,
            phase=controller.get("active_phase", "unknown"),
            step=controller.get("active_step", "unknown"),
            retention_class="audit",
        )

    def sync_manifest_snapshot(
        self,
        task_id: str,
        *,
        blocker_refs: list[str] | None = None,
        artifact_refs: dict[str, str] | None = None,
        plan_artifact_refs: dict[str, str] | None = None,
        final_report_ref: str | None = None,
    ) -> None:
        self._sync_manifest_snapshot(
            task_id,
            blocker_refs=blocker_refs,
            artifact_refs=artifact_refs,
            plan_artifact_refs=plan_artifact_refs,
            final_report_ref=final_report_ref,
        )

    def _resume_override_conflict(
        self,
        controller: dict[str, Any],
        selectors: dict[str, Any],
    ) -> str:
        if controller.get("active_step", "") in {"", "intake"}:
            return ""
        blocked_reason = controller.get("blocked_reason", "")
        if not blocked_reason:
            return ""
        if "approval_continuation" in selectors and selectors.get(
            "approval_continuation"
        ):
            return ""
        invariant_pairs = {
            "phase": controller.get("active_phase", ""),
            "strategy": controller.get("active_strategy", ""),
            "step": controller.get("active_step", ""),
            "resume_from": controller.get("resume_selectors", {}).get(
                "resume_from", ""
            ),
        }
        for key, current_value in invariant_pairs.items():
            requested = selectors.get(key)
            if requested and current_value and requested != current_value:
                return "resume_override_conflict"
        return ""

    def _record_resume_override_conflict(
        self,
        *,
        task_id: str,
        controller: dict[str, Any],
        selectors: dict[str, Any],
        reason: str,
    ) -> None:
        phase = controller.get("active_phase", "unknown")
        step = controller.get("active_step", "unknown")
        payload = {
            "schemaVersion": "1.0.0",
            "taskId": task_id,
            "decisionType": "resume_override",
            "phase": phase,
            "step": step,
            "requestedSelectors": selectors,
            "currentSelectors": controller.get("resume_selectors", {}),
            "outcome": "blocked",
            "reasonCode": reason,
        }
        decision_record = self.store.write_json_artifact(
            task_id=task_id,
            family="option-decisions",
            artifact_type="option_decision",
            payload=payload,
            filename=f"resume-override-{phase}-{step}.json",
            phase=phase,
            step=step,
        )
        self._append_decision(
            task_id=task_id,
            decision_type="resume_override",
            phase=phase,
            step=step,
            outcome="blocked",
            payload=payload,
        )
        pause_payload = build_runtime_pause_confirm(
            task_id=task_id,
            phase=phase,
            step=step,
            strategy=controller.get("active_strategy", ""),
            blocked_reason=reason,
            reason_code=reason,
            artifact_refs={
                "manifest": str(
                    task_artifacts_dir(self.root_dir, task_id)
                    / "manifests"
                    / "manifest.json"
                ),
                "applyResult": "",
                "validation": "",
                "response": "",
                "request": "",
                "resolvedConfig": "",
                "routingResult": "",
                "promptBundle": "",
            },
            severity="high",
        )
        pause_record = self.store.write_json_artifact(
            task_id=task_id,
            family="pause-confirm",
            artifact_type="pause_confirm",
            payload=pause_payload,
            filename=f"pause-confirm-resume-override-{phase}-{step}.json",
            phase=phase,
            step=step,
        )
        self.store.write_text_artifact(
            task_id=task_id,
            family="summaries",
            filename=f"pause-confirm-resume-override-{phase}-{step}.md",
            content=render_markdown_document(
                title="Pause Confirm",
                payload=pause_payload,
            ),
        )
        self._sync_manifest_snapshot(
            task_id,
            blocker_refs=[str(decision_record.path), str(pause_record.path)],
            artifact_refs={"pauseConfirm": str(pause_record.path)},
        )

    def _record_strategy_switch(
        self,
        *,
        task_id: str,
        from_phase: str,
        from_strategy: str,
        to_phase: str,
        to_strategy: str,
        reason_code: str,
    ) -> Path:
        record = self.store.write_json_artifact(
            task_id=task_id,
            family="strategy-switches",
            artifact_type="strategy_switch",
            payload={
                "schemaVersion": "1.0.0",
                "taskId": task_id,
                "fromPhase": from_phase,
                "fromStrategy": from_strategy,
                "toPhase": to_phase,
                "toStrategy": to_strategy,
                "reasonCode": reason_code,
            },
            filename=f"strategy-switch-{from_phase}-{to_phase}.json",
            phase=to_phase,
            step="strategy-switch",
        )
        self._append_decision(
            task_id=task_id,
            decision_type="strategy_switch",
            phase=to_phase,
            step="strategy-switch",
            outcome="applied",
            payload={
                "from_phase": from_phase,
                "from_strategy": from_strategy,
                "to_phase": to_phase,
                "to_strategy": to_strategy,
                "reason_code": reason_code,
            },
        )
        return record.path

    def _is_mid_phase_strategy_switch(
        self,
        *,
        previous_phase: str,
        previous_step: str,
        previous_strategy: str,
        next_strategy: str,
    ) -> bool:
        if not previous_strategy or not next_strategy:
            return False
        if previous_strategy == next_strategy:
            return False
        if previous_phase in {"", "intake"}:
            return False
        if previous_step in {"", "intake"}:
            return False
        return True

    def _append_event(
        self,
        *,
        task_id: str,
        event_type: str,
        phase: str,
        step: str,
        payload: dict[str, Any],
    ) -> None:
        if self.suppression.should_emit(
            "event", f"{task_id}:{event_type}:{phase}:{step}", payload
        ):
            self.events.append(
                task_id=task_id,
                event_type=event_type,
                phase=phase,
                step=step,
                payload=payload,
            )

    def _append_decision(
        self,
        *,
        task_id: str,
        decision_type: str,
        phase: str,
        step: str,
        outcome: str,
        payload: dict[str, Any],
    ) -> None:
        if self.suppression.should_emit(
            "decision", f"{task_id}:{decision_type}:{phase}:{step}:{outcome}", payload
        ):
            self.decisions.append(
                task_id=task_id,
                decision_type=decision_type,
                phase=phase,
                step=step,
                outcome=outcome,
                payload=payload,
            )


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _compact_timestamp(value: str) -> str:
    return value.replace("-", "").replace(":", "").replace("+00:00", "Z")
