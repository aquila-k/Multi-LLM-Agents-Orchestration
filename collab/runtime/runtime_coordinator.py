from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from collab.runtime.apply_executor import ApplyExecutor
from collab.runtime.artifact_store import ArtifactStore
from collab.runtime.diff_capture import capture_git_diff, check_paths_in_allowlist
from collab.runtime.manifest_store import extend_manifest_snapshot
from collab.runtime.mutation_authority import (
    authority_allows_direct_write,
    authority_requires_apply_executor,
    resolve_mutation_authority,
)
from collab.runtime.normalizer import normalize_response
from collab.runtime.parser import parse_provider_output
from collab.runtime.providers import get_provider_adapter
from collab.runtime.retry_policy import classify_retry_candidate
from collab.runtime.review_gate import evaluate_review_gate
from collab.runtime.shell_digest import (
    derive_shell_digest,
    ingest_shell_digest,
    persist_shell_digest,
)
from collab.runtime.stop_categories import UNSAFE_APPLY
from collab.runtime.task_runner import TaskRunner
from collab.runtime.validator import validate_artifacts

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoordinationResult:
    adapter_request_path: Path
    adapter_result_path: Path
    raw_output_path: Path | None
    response_path: Path
    normalized_path: Path
    validation_path: Path
    execution_record_path: Path
    shell_digest_path: Path
    manifest_path: Path
    session_state_path: Path
    apply_result_path: Path | None
    apply_result: dict[str, Any] | None
    controller_status: str
    blocked_reason: str = ""


class RuntimeCoordinator:
    def __init__(self, root_dir: Path, *, live_mode: bool = False) -> None:
        self.root_dir = root_dir.resolve()
        self.live_mode = live_mode
        self.store = ArtifactStore(self.root_dir)
        self.apply_executor = ApplyExecutor(self.root_dir)
        self.task_runner = TaskRunner(self.root_dir)

    def execute_phase(
        self,
        *,
        task_id: str,
        request_path: Path,
        phase: str,
        step: str,
        resolved_config_path: Path | None = None,
        routing_result_path: Path | None = None,
        prompt_bundle_path: Path | None = None,
        manifest_path: Path | None = None,
        attempt: int = 1,
        run: int = 1,
        auto_apply: bool = True,
        state_updates_enabled: bool = True,
        forbidden_paths: list[str] | None = None,
        max_files: int = 3,
        max_bytes: int = 20 * 1024,
    ) -> CoordinationResult:
        request = self._load_artifact_payload(request_path)
        task_root = self.store.task_root(task_id)
        state_dir = self.root_dir / "collab" / "state" / "tasks" / task_id
        resolved_config_path = resolved_config_path or (
            task_root / "resolved-config" / "resolved-config-intake.json"
        )
        routing_result_path = routing_result_path or (
            task_root / "routing" / "routing-result-intake.json"
        )
        prompt_bundle_path = prompt_bundle_path or (
            task_root / "prompts" / "prompt-bundle-intake.json"
        )
        manifest_path = manifest_path or (task_root / "manifests" / "manifest.json")
        session_state_path = state_dir / "session-state.json"

        resolved_config = self._load_artifact_payload(resolved_config_path)
        prompt_bundle = self._load_artifact_payload(prompt_bundle_path)
        manifest = (
            self._load_artifact_payload(manifest_path) if manifest_path.exists() else {}
        )
        provider = resolved_config["provider"]["provider"]
        raw_step_config = resolved_config.get("step", {})
        step_config = raw_step_config if isinstance(raw_step_config, dict) else {}
        effective_authority = resolve_mutation_authority(step_config, provider)
        requires_apply_executor = authority_requires_apply_executor(effective_authority)
        allows_direct_write = authority_allows_direct_write(effective_authority)
        adapter = get_provider_adapter(
            provider, root_dir=self.root_dir, live_mode=self.live_mode
        )

        adapter_request_filename = (
            f"adapter-request-{phase}-{step}-{attempt}-{run}.json"
        )
        adapter_result_filename = f"adapter-result-{phase}-{step}-{attempt}-{run}.json"
        raw_output_filename = f"raw-output-{phase}-{step}-{attempt}-{run}.txt"
        response_filename = f"response-{phase}-{step}-{attempt}-{run}.json"
        normalized_filename = f"normalized-{phase}-{step}-{attempt}-{run}.json"
        validation_filename = f"validation-{phase}-{step}-{attempt}-{run}.json"
        execution_filename = f"execution-record-{phase}-{step}-{attempt}-{run}.json"
        shell_digest_filename = f"shell-digest-{phase}-{step}-{attempt}-{run}.json"
        apply_result_filename = f"apply-result-{phase}-{step}.json"

        adapter_request_path = self._artifact_path(
            task_id, "adapter", adapter_request_filename
        )
        adapter_result_path = self._artifact_path(
            task_id, "adapter", adapter_result_filename
        )
        raw_output_path = self._artifact_path(task_id, "adapter", raw_output_filename)
        response_path = self._artifact_path(task_id, "responses", response_filename)
        normalized_path = self._artifact_path(
            task_id, "normalized", normalized_filename
        )
        validation_path = self._artifact_path(
            task_id, "validation", validation_filename
        )
        execution_record_path = self._artifact_path(
            task_id, "execution-records", execution_filename
        )
        shell_digest_path = self._artifact_path(
            task_id, "shell-digests", shell_digest_filename
        )
        apply_result_path = self._artifact_path(
            task_id, "apply-results", apply_result_filename
        )

        artifact_destinations = {
            "adapterRequest": str(adapter_request_path),
            "adapterResult": str(adapter_result_path),
            "rawOutput": str(raw_output_path),
            "response": str(response_path),
            "normalized": str(normalized_path),
            "validation": str(validation_path),
            "executionRecord": str(execution_record_path),
            "shellDigest": str(shell_digest_path),
            "applyResult": str(apply_result_path),
            "manifest": str(manifest_path),
            "sessionState": str(session_state_path),
        }

        session_state = (
            self._load_json(session_state_path) if session_state_path.exists() else None
        )
        adapter_request = adapter.build_request(
            task_id=task_id,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
            request=request,
            request_ref=str(request_path),
            resolved_config=resolved_config,
            resolved_config_ref=str(resolved_config_path),
            routing_result_ref=str(routing_result_path),
            prompt_bundle=prompt_bundle,
            prompt_bundle_ref=str(prompt_bundle_path),
            manifest_ref=str(manifest_path),
            session_state=session_state,
            session_state_ref=str(session_state_path) if session_state else "",
            artifact_destinations=artifact_destinations,
        )
        self.store.write_json_artifact(
            task_id=task_id,
            family="adapter",
            artifact_type="adapter_request",
            payload=adapter_request,
            filename=adapter_request_filename,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
        )

        invocation = adapter.execute(adapter_request=adapter_request)
        effective_raw_output_path: Path | None = None
        if invocation.raw_output_text is not None:
            effective_raw_output_path = self.store.write_text_artifact(
                task_id=task_id,
                family="adapter",
                filename=raw_output_filename,
                content=invocation.raw_output_text,
            )

        adapter_result = {
            **invocation.result_payload,
            "artifacts": {
                "adapterRequestRef": str(adapter_request_path),
                "rawOutputRef": (
                    str(effective_raw_output_path) if effective_raw_output_path else ""
                ),
            },
        }
        self.store.write_json_artifact(
            task_id=task_id,
            family="adapter",
            artifact_type="adapter_result",
            payload=adapter_result,
            filename=adapter_result_filename,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
        )

        parsed = adapter_result.get("parsedEnvelope")
        if not isinstance(parsed, dict):
            parsed = parse_provider_output(invocation.raw_output_text or "")
        shell_summary = self._build_shell_summary(
            phase=phase,
            step=step,
            provider=provider,
            parsed=parsed,
            adapter_result=adapter_result,
        )
        run_ref = f"{task_id}:{phase}:{step}:{attempt}:{run}"

        response = self._build_response(
            task_id=task_id,
            parsed=parsed,
            provider=provider,
            adapter_version=adapter_result["adapterVersion"],
            started_at=adapter_result["startedAt"],
            completed_at=adapter_result["completedAt"],
            run_ref=run_ref,
            shell_digest_ref=str(shell_digest_path),
            raw_output_ref=(
                str(effective_raw_output_path) if effective_raw_output_path else ""
            ),
            parsed_payload_ref=str(adapter_result_path),
            exit_code=adapter_result.get("exitStatus", {}).get("code"),
        )
        self.store.write_json_artifact(
            task_id=task_id,
            family="responses",
            artifact_type="response",
            payload=response,
            filename=response_filename,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
        )

        normalized = normalize_response(
            task_id=task_id,
            parsed_response=response,
            source_response_ref=str(response_path),
        )
        self.store.write_json_artifact(
            task_id=task_id,
            family="normalized",
            artifact_type="normalized",
            payload=normalized,
            filename=normalized_filename,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
        )
        review_gate_result = None
        if phase in {"review", "harden"} and auto_apply:
            try:
                review_gate_result = evaluate_review_gate(normalized)
                self.store.write_json_artifact(
                    task_id=task_id,
                    family="findings",
                    artifact_type="findings-gate",
                    payload={
                        "can_complete": review_gate_result.can_complete,
                        "blocking_found": review_gate_result.blocking_found,
                        "findings_summary": review_gate_result.summary,
                        "findings": review_gate_result.findings,
                        "fixable_operations_count": len(
                            review_gate_result.fixable_operations
                        ),
                    },
                    filename=f"findings-gate-{phase}-{step}-{attempt}-{run}.json",
                    phase=phase,
                    step=step,
                    attempt=attempt,
                    run=run,
                )
                if review_gate_result.fixable_operations:
                    normalized = dict(normalized)
                    normalized["operations"] = review_gate_result.fixable_operations
            except Exception:  # noqa: BLE001
                logger.exception(
                    "review gate evaluation failed; continuing without gate",
                    extra={"task_id": task_id, "phase": phase, "step": step},
                )

        persisted_shell_digest = persist_shell_digest(
            root_dir=self.root_dir,
            task_id=task_id,
            shell_digest=derive_shell_digest(
                task_id=task_id,
                concise_summary=shell_summary,
                execution_record_ref=str(execution_record_path),
                response_ref=str(response_path),
                validation_ref=str(validation_path),
            ),
            phase=phase,
            step=step,
            filename=shell_digest_filename,
            attempt=attempt,
            run=run,
        )

        validation = validate_artifacts(
            request=request,
            response=response,
            normalized=normalized,
            execution={
                "shell_summary": shell_summary,
                "shell_digest_ref": str(persisted_shell_digest.path),
            },
            forbidden_paths=forbidden_paths
            or request.get("constraints", {}).get("disallowed_paths", []),
            max_files=max_files,
            max_bytes=max_bytes,
        )
        self.store.write_json_artifact(
            task_id=task_id,
            family="validation",
            artifact_type="validation",
            payload=validation,
            filename=validation_filename,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
        )

        forced_blocked_reason = self._response_blocked_reason(response, adapter_result)
        execution_record = self._build_execution_record(
            task_id=task_id,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
            provider=provider,
            adapter_version=adapter_result["adapterVersion"],
            status=self._execution_status(response, validation),
            started_at=adapter_result["startedAt"],
            completed_at=adapter_result["completedAt"],
            shell_summary=shell_summary,
            request_ref=str(request_path),
            adapter_request_ref=str(adapter_request_path),
            adapter_result_ref=str(adapter_result_path),
            response_ref=str(response_path),
            normalized_ref=str(normalized_path),
            validation_ref=str(validation_path),
            shell_digest_ref=str(persisted_shell_digest.path),
            exit_code=adapter_result.get("exitStatus", {}).get("code"),
            session_ref=adapter_result.get("session", {}).get("sessionRef", ""),
            effective_mutation_authority=effective_authority,
        )
        self.store.write_json_artifact(
            task_id=task_id,
            family="execution-records",
            artifact_type="execution_record",
            payload=execution_record,
            filename=execution_filename,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
            retention_class="audit",
        )

        apply_result = None
        effective_apply_path: Path | None = None
        if auto_apply and requires_apply_executor and not forced_blocked_reason:
            apply_result = self.apply_executor.apply(
                task_id=task_id,
                normalized=normalized,
                validation=validation,
                phase=phase,
                step=step,
                attempt=attempt,
                run=run,
            )
            effective_apply_path = apply_result_path
        if (
            review_gate_result
            and review_gate_result.blocking_found
            and not review_gate_result.can_complete
        ):
            apply_succeeded = allows_direct_write or (
                apply_result is not None and apply_result.get("result") == "applied"
            )
            if not review_gate_result.fixable_operations or not apply_succeeded:
                forced_blocked_reason = "review_blocking_findings"
        if allows_direct_write:
            try:
                diff_result = capture_git_diff(self.root_dir)
                allowed_dirs = resolved_config.get("scope", {}).get(
                    "allow",
                    manifest.get("scope", {}).get("allow", ["src/", "tests/"]),
                )
                scope_check = check_paths_in_allowlist(
                    diff_result.get("changedFiles", []),
                    (
                        allowed_dirs
                        if isinstance(allowed_dirs, list)
                        else ["src/", "tests/"]
                    ),
                )
                diff_artifact = {**diff_result, "scopeCheck": scope_check}
                self.store.write_json_artifact(
                    task_id=task_id,
                    family="diff-captures",
                    artifact_type="diff_capture",
                    payload=diff_artifact,
                    filename=f"diff-capture-{phase}-{step}-{attempt}-{run}.json",
                    phase=phase,
                    step=step,
                    attempt=attempt,
                    run=run,
                )
                if not scope_check.get("allInScope", True):
                    forced_blocked_reason = UNSAFE_APPLY
            except Exception:  # noqa: BLE001
                logger.exception(
                    "diff capture failed; continuing without diff artifact",
                    extra={"task_id": task_id, "phase": phase, "step": step},
                )
        blocked_reason = forced_blocked_reason or (
            apply_result["result"]
            if apply_result and apply_result["result"].startswith("blocked_")
            else ""
        )
        if state_updates_enabled:
            self._write_session_state(
                task_id=task_id,
                phase=phase,
                step=step,
                attempt=attempt,
                run=run,
                session=adapter_result.get("session", {}),
                adapter_request_path=adapter_request_path,
                adapter_result_path=adapter_result_path,
                session_state_path=session_state_path,
            )
            self._write_execution_manifest(
                task_id=task_id,
                manifest=manifest,
                manifest_path=manifest_path,
                phase=phase,
                step=step,
                attempt=attempt,
                run=run,
                blocked_reason=blocked_reason,
                provider=provider,
                session_ref=adapter_result.get("session", {}).get("sessionRef", ""),
                artifact_refs={
                    "request": str(request_path),
                    "adapterRequest": str(adapter_request_path),
                    "adapterResult": str(adapter_result_path),
                    "rawOutput": (
                        str(effective_raw_output_path)
                        if effective_raw_output_path
                        else ""
                    ),
                    "response": str(response_path),
                    "normalized": str(normalized_path),
                    "validation": str(validation_path),
                    "executionRecord": str(execution_record_path),
                    "shellDigest": str(persisted_shell_digest.path),
                    "applyResult": (
                        str(effective_apply_path) if effective_apply_path else ""
                    ),
                    "sessionState": str(session_state_path),
                },
            )

            self._update_state_after_execution(
                task_id=task_id,
                phase=phase,
                step=step,
                response=response,
                response_path=response_path,
                validation=validation,
                validation_path=validation_path,
                apply_result=apply_result,
                apply_result_path=effective_apply_path,
                forced_blocked_reason=forced_blocked_reason,
                persisted_shell_digest=persisted_shell_digest.payload,
                shell_digest_path=persisted_shell_digest.path,
                completed_at=adapter_result["completedAt"],
            )

            controller = self._load_json(state_dir / "controller-state.json")
            blocked_reason = str(controller.get("blocked_reason", ""))
            if controller.get("current_status") == "blocked":
                retry_analysis = classify_retry_candidate(
                    coordination_result_summary={
                        "controller_status": controller.get("current_status", ""),
                        "blocked_reason": blocked_reason,
                        "phase": phase,
                        "step": step,
                        "attempt": attempt,
                        "run": run,
                        "response_status": response.get("status", ""),
                        "issue_codes": _issue_codes(response),
                    },
                    apply_result=apply_result,
                    normalized=normalized,
                )
                retry_record = self.store.write_json_artifact(
                    task_id=task_id,
                    family="retry-analyses",
                    artifact_type="retry_analysis",
                    payload={
                        "schema_version": "1.0.0",
                        "task_id": task_id,
                        "phase": phase,
                        "step": step,
                        "attempt": attempt,
                        "run": run,
                        "controller_status": controller.get("current_status", ""),
                        "blocked_reason": blocked_reason,
                        "retry_analysis": retry_analysis,
                        "response_ref": str(response_path),
                        "normalized_ref": str(normalized_path),
                        "validation_ref": str(validation_path),
                        "apply_result_ref": (
                            str(effective_apply_path) if effective_apply_path else ""
                        ),
                    },
                    filename=f"retry-analysis-{phase}-{step}-{attempt}-{run}.json",
                    phase=phase,
                    step=step,
                    attempt=attempt,
                    run=run,
                )
                self.task_runner.record_retry_analysis(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    attempt=attempt,
                    run=run,
                    retry_analysis=retry_analysis,
                    artifact_ref=str(retry_record.path),
                )
                controller = self._load_json(state_dir / "controller-state.json")
            effective_controller_status = controller["current_status"]
        else:
            if blocked_reason:
                effective_controller_status = "blocked"
            else:
                effective_controller_status = (
                    "running" if response.get("status") == "success" else "partial"
                )
        return CoordinationResult(
            adapter_request_path=adapter_request_path,
            adapter_result_path=adapter_result_path,
            raw_output_path=effective_raw_output_path,
            response_path=response_path,
            normalized_path=normalized_path,
            validation_path=validation_path,
            execution_record_path=execution_record_path,
            shell_digest_path=persisted_shell_digest.path,
            manifest_path=manifest_path,
            session_state_path=session_state_path,
            apply_result_path=effective_apply_path,
            apply_result=apply_result,
            controller_status=effective_controller_status,
            blocked_reason=blocked_reason,
        )

    def _update_state_after_execution(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        response: dict[str, Any],
        response_path: Path,
        validation: dict[str, Any],
        validation_path: Path,
        apply_result: dict[str, Any] | None,
        apply_result_path: Path | None,
        forced_blocked_reason: str,
        persisted_shell_digest: dict[str, Any],
        shell_digest_path: Path,
        completed_at: str,
    ) -> None:
        state_dir = self.root_dir / "collab" / "state" / "tasks" / task_id
        controller_path = state_dir / "controller-state.json"
        known_information_path = state_dir / "known-information.json"

        controller = self._load_json(controller_path)
        shell_refs = list(controller.get("latest_shell_digest_refs", []))
        shell_refs.append(str(shell_digest_path))
        controller.update(
            {
                "active_phase": phase,
                "active_step": step,
                "latest_shell_digest_refs": _unique(shell_refs),
                "updated_at": completed_at,
            }
        )
        self._write_json(controller_path, controller)

        known_information = self._load_json(known_information_path)
        known_information["latest_phase_summary"] = {
            "phase": phase,
            "summary": response["summary"],
            "artifact_ref": str(response_path),
        }

        apply_summary = apply_result["result"] if apply_result else "not_applied"
        known_information["latest_validation_apply_summary"] = {
            "summary": f"validation={validation['overall_outcome']} apply={apply_summary}",
            "validation_ref": str(validation_path),
            "apply_result_ref": str(apply_result_path) if apply_result_path else "",
        }

        if apply_result and apply_result["result"].startswith("blocked_"):
            known_information.setdefault("unresolved_blockers", [])
            if apply_result["result"] not in known_information["unresolved_blockers"]:
                known_information["unresolved_blockers"].append(apply_result["result"])

        known_information = ingest_shell_digest(
            known_information=known_information,
            shell_digest=persisted_shell_digest,
        )
        self._write_json(known_information_path, known_information)

        if forced_blocked_reason:
            self.task_runner.pause_step(
                task_id=task_id,
                phase=phase,
                step=step,
                reason=forced_blocked_reason,
                resume_from=step,
            )
            return

        if apply_result and apply_result["result"] == "applied":
            self.task_runner.complete_step(
                task_id=task_id,
                phase=phase,
                step=step,
                artifact_ref=str(apply_result_path),
                partial=False,
            )
            return

        if apply_result and apply_result["result"].startswith("blocked_"):
            self.task_runner.pause_step(
                task_id=task_id,
                phase=phase,
                step=step,
                reason=apply_result["result"],
                resume_from=step,
            )
            return

        self.task_runner.complete_step(
            task_id=task_id,
            phase=phase,
            step=step,
            artifact_ref=str(validation_path),
            partial=True,
        )

    def _response_blocked_reason(
        self, response: dict[str, Any], adapter_result: dict[str, Any]
    ) -> str:
        if _is_missing_tool_or_auth(response, adapter_result):
            return "missing_tool_or_auth"
        if response.get("status") != "blocked":
            return ""
        known_stop_codes = {
            "missing_session_ref",
            "provider_capability_mismatch",
        }
        for issue in response.get("issues", []):
            if not isinstance(issue, dict):
                continue
            code = str(issue.get("code", "")).strip()
            if code in known_stop_codes:
                return code
        return "provider_capability_mismatch"

    def _artifact_path(self, task_id: str, family: str, filename: str) -> Path:
        return self.store.family_dir(task_id, family) / filename

    def _build_response(
        self,
        *,
        task_id: str,
        parsed: dict[str, Any],
        provider: str,
        adapter_version: str,
        started_at: str,
        completed_at: str,
        run_ref: str,
        shell_digest_ref: str,
        raw_output_ref: str,
        parsed_payload_ref: str,
        exit_code: int | None,
    ) -> dict[str, Any]:
        response = {
            "schema_version": "1.0.0",
            "task_id": task_id,
            "status": parsed["status"],
            "mode": parsed["mode"],
            "summary": parsed["summary"],
            "warnings": parsed.get("warnings", []),
            "issues": parsed.get("issues", []),
            "payload": parsed.get("payload", {}),
            "metadata": {
                "provider": provider,
                "adapter_version": adapter_version,
                "started_at": started_at,
                "completed_at": completed_at,
                "run_ref": run_ref,
                "exit_code": exit_code,
                "shell_digest_ref": shell_digest_ref,
            },
        }
        if raw_output_ref:
            response["raw_output_ref"] = raw_output_ref
        if parsed_payload_ref:
            response["parsed_payload_ref"] = parsed_payload_ref
        return response

    def _build_execution_record(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        attempt: int,
        run: int,
        provider: str,
        adapter_version: str,
        status: str,
        started_at: str,
        completed_at: str,
        shell_summary: str,
        request_ref: str,
        adapter_request_ref: str,
        adapter_result_ref: str,
        response_ref: str,
        normalized_ref: str,
        validation_ref: str,
        shell_digest_ref: str,
        exit_code: int | None,
        session_ref: str,
        effective_mutation_authority: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "task_id": task_id,
            "phase": phase,
            "step": step,
            "attempt": attempt,
            "run": run,
            "status": status,
            "actor": {
                "kind": "provider",
                "name": provider,
                "adapter_version": adapter_version,
            },
            "started_at": started_at,
            "completed_at": completed_at,
            "exit_code": exit_code,
            "shell_summary": shell_summary,
            "artifacts": {
                "request_ref": request_ref,
                "adapter_request_ref": adapter_request_ref,
                "adapter_result_ref": adapter_result_ref,
                "response_ref": response_ref,
                "normalized_ref": normalized_ref,
                "validation_ref": validation_ref,
                "shell_digest_ref": shell_digest_ref,
            },
            "session": {
                "provider": provider,
                "session_ref": session_ref,
            },
            "effectiveMutationAuthority": effective_mutation_authority,
        }

    def _execution_status(
        self, response: dict[str, Any], validation: dict[str, Any]
    ) -> str:
        if validation["overall_outcome"] == "failed_unusable":
            return "failed"
        if response["status"] == "success":
            return "succeeded"
        if response["status"] == "partial":
            return "partial"
        if response["status"] == "failed":
            return "failed"
        return "running"

    def _load_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_artifact_payload(self, path: Path) -> dict[str, Any]:
        envelope = self._load_json(path)
        return envelope.get("payload", envelope)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )

    def _build_shell_summary(
        self,
        *,
        phase: str,
        step: str,
        provider: str,
        parsed: dict[str, Any],
        adapter_result: dict[str, Any],
    ) -> str:
        return (
            f"Task ready; phase={phase} step={step} provider={provider} "
            f"status={parsed.get('status', adapter_result.get('status', 'partial'))} "
            f"session={adapter_result.get('session', {}).get('resolvedMode', 'fresh')}."
        )

    def _write_session_state(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        attempt: int,
        run: int,
        session: dict[str, Any],
        adapter_request_path: Path,
        adapter_result_path: Path,
        session_state_path: Path,
    ) -> None:
        payload = {
            "schema_version": "1.0.0",
            "task_id": task_id,
            "phase": phase,
            "step": step,
            "attempt": attempt,
            "run": run,
            "provider": session.get("provider") or "",
            "sessionRef": session.get("sessionRef", ""),
            "requestedMode": session.get("requestedMode", "fresh"),
            "resolvedMode": session.get("resolvedMode", "fresh"),
            "resumeDecision": session.get("resumeDecision", "not_requested"),
            "resumeRefUsed": session.get("resumeRefUsed", ""),
            "capabilityMetadata": session.get("capabilityMetadata", {}),
            "adapterRequestRef": str(adapter_request_path),
            "adapterResultRef": str(adapter_result_path),
        }
        self._write_json(session_state_path, payload)

    def _write_execution_manifest(
        self,
        *,
        task_id: str,
        manifest: dict[str, Any],
        manifest_path: Path,
        phase: str,
        step: str,
        attempt: int,
        run: int,
        blocked_reason: str,
        provider: str,
        session_ref: str,
        artifact_refs: dict[str, str],
    ) -> None:
        effective_manifest = extend_manifest_snapshot(
            manifest=manifest,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
            blocked_reason=blocked_reason,
            session_refs={
                "provider": provider
                or manifest.get("sessionRefs", {}).get("provider", ""),
                "sessionRef": session_ref,
            },
            artifact_refs=artifact_refs,
        )
        self.store.write_json_artifact(
            task_id=task_id,
            family="manifests",
            artifact_type="manifest_snapshot",
            payload=effective_manifest,
            filename=manifest_path.name,
            phase=phase,
            step=step,
            attempt=attempt,
            run=run,
        )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _issue_codes(response: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for issue in response.get("issues", []):
        if not isinstance(issue, dict):
            continue
        code = str(issue.get("code", "")).strip()
        if code:
            codes.append(code)
    return codes


def _is_missing_tool_or_auth(
    response: dict[str, Any], adapter_result: dict[str, Any]
) -> bool:
    missing_codes = {
        "BINARY_NOT_FOUND",
        "MISSING_BINARY",
        "TOOL_NOT_FOUND",
        "AUTH_FAILED",
        "AUTHENTICATION_FAILED",
        "PERMISSION_DENIED",
    }
    issue_codes = {code.upper() for code in _issue_codes(response)}
    if issue_codes.intersection(missing_codes):
        return True

    issue_messages = " ".join(
        str(issue.get("message", ""))
        for issue in response.get("issues", [])
        if isinstance(issue, dict)
    ).lower()
    if any(
        token in issue_messages
        for token in ("binary not found", "tool not found", "not installed", "auth")
    ):
        return True

    exit_kind = str(adapter_result.get("exitStatus", {}).get("kind", "")).lower()
    if exit_kind in {"binary_not_found", "auth_failed", "tool_not_found"}:
        return True
    return False
