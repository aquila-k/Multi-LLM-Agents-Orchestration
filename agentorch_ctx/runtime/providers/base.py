from __future__ import annotations

import json
import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

ADAPTER_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class AdapterInvocation:
    result_payload: dict[str, Any]
    raw_output_text: str | None


class ProviderAdapter(ABC):
    provider: str = ""
    adapter_version = "1.0.0"

    def __init__(self, *, root_dir: Path, live_mode: bool = False) -> None:
        self.root_dir = root_dir.resolve()
        self.live_mode = live_mode

    def build_request(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        attempt: int,
        run: int,
        request: dict[str, Any],
        request_ref: str,
        resolved_config: dict[str, Any],
        resolved_config_ref: str,
        routing_result_ref: str,
        prompt_bundle: dict[str, Any],
        prompt_bundle_ref: str,
        manifest_ref: str,
        session_state: dict[str, Any] | None,
        session_state_ref: str,
        artifact_destinations: dict[str, str],
    ) -> dict[str, Any]:
        provider_config = resolved_config.get("provider", {})
        provider_options = dict(provider_config.get("options", {}))
        provider_options["model"] = provider_config.get("modelRef")
        session_contract = self._build_session_contract(
            request=request,
            resolved_config=resolved_config,
            session_state=session_state or {},
        )
        return {
            "schemaVersion": ADAPTER_SCHEMA_VERSION,
            "taskId": task_id,
            "phase": phase,
            "step": step,
            "attempt": attempt,
            "run": run,
            "workflowIntent": request.get("workflow_intent"),
            "provider": provider_config.get("provider"),
            "profile": provider_config.get("profile"),
            "modelRef": provider_config.get("modelRef"),
            "model": provider_config.get("model"),
            "providerOptions": provider_options,
            "supportedOptionKeys": provider_config.get("supportedOptionKeys", []),
            "timeouts": provider_config.get("timeoutDefaults", {}),
            "retryPolicy": provider_config.get("retryDefaults", {}),
            "outputContract": {
                "preferredMode": request.get("output", {}).get("preferred_mode"),
                "allowedModes": request.get("output", {}).get("allowed_modes", []),
                "operationsRequired": bool(
                    request.get("output", {}).get("operations_required")
                ),
                "strategyPreferredMode": resolved_config.get("strategy", {}).get(
                    "preferredOutputMode"
                ),
            },
            "phaseOptions": resolved_config.get("phaseOptions", {}),
            "targets": prompt_bundle.get("targets", {}),
            "summary": prompt_bundle.get("summary", ""),
            "promptText": prompt_bundle.get("promptText")
            or prompt_bundle.get("summary", ""),
            "operatorContext": prompt_bundle.get("operatorContext", {}),
            "inputRefs": {
                "request": request_ref,
                "resolvedConfig": resolved_config_ref,
                "routingResult": routing_result_ref,
                "promptBundle": prompt_bundle_ref,
                "manifest": manifest_ref,
                "sessionState": session_state_ref,
            },
            "artifactDestinations": artifact_destinations,
            "session": session_contract,
            "providerInvocation": self._build_provider_invocation(
                provider_config=provider_config,
                session_contract=session_contract,
            ),
            "stubMode": not self.live_mode,
        }

    def execute(self, *, adapter_request: dict[str, Any]) -> AdapterInvocation:
        if self._is_resume_blocked(adapter_request):
            return self._resume_blocked_invocation(adapter_request)
        if self.live_mode:
            return self._execute_live(adapter_request=adapter_request)
        return self._execute_stub(adapter_request=adapter_request)

    def execute_live(self, *, adapter_request: dict[str, Any]) -> AdapterInvocation:
        """Force live execution regardless of live_mode flag."""
        if self._is_resume_blocked(adapter_request):
            return self._resume_blocked_invocation(adapter_request)
        return self._execute_live(adapter_request=adapter_request)

    def _execute_stub(self, *, adapter_request: dict[str, Any]) -> AdapterInvocation:
        started_at = _isoformat(datetime.now(timezone.utc))
        parsed_envelope = self._build_parsed_envelope(adapter_request)
        completed_at = _isoformat(datetime.now(timezone.utc))
        session_result = self._build_session_result(adapter_request)
        raw_output_text = (
            json.dumps(parsed_envelope, indent=2, ensure_ascii=True) + "\n"
            if parsed_envelope
            else None
        )
        return AdapterInvocation(
            result_payload={
                "schemaVersion": ADAPTER_SCHEMA_VERSION,
                "taskId": adapter_request["taskId"],
                "provider": self.provider,
                "adapterVersion": self.adapter_version,
                "phase": adapter_request["phase"],
                "step": adapter_request["step"],
                "attempt": adapter_request["attempt"],
                "run": adapter_request["run"],
                "status": "succeeded",
                "executionMode": "stub",
                "startedAt": started_at,
                "completedAt": completed_at,
                "exitStatus": {
                    "code": 0,
                    "kind": "stub_success",
                },
                "rawOutput": {
                    "captured": raw_output_text is not None,
                    "redacted": raw_output_text is not None,
                    "omissionReason": (
                        "" if raw_output_text is not None else "stub_no_output"
                    ),
                },
                "session": session_result,
                "parsedEnvelope": parsed_envelope,
                "providerInvocation": adapter_request["providerInvocation"],
            },
            raw_output_text=raw_output_text,
        )

    def _execute_live(self, *, adapter_request: dict[str, Any]) -> AdapterInvocation:
        """Execute the provider CLI as a real subprocess and return the result."""
        started_at = _isoformat(datetime.now(timezone.utc))
        timeout_sec = max(
            30, adapter_request.get("timeouts", {}).get("defaultMs", 600000) // 1000
        )

        with tempfile.TemporaryDirectory(prefix="agentorch-live-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            try:
                cmd, stdin_bytes, output_file = self._build_live_command_and_input(
                    adapter_request=adapter_request,
                    tmp_dir=tmp_path,
                )
                env = _build_exec_env()
                env.update(self._build_live_env(adapter_request=adapter_request))
                proc = subprocess.run(
                    cmd,
                    input=stdin_bytes,
                    capture_output=True,
                    timeout=timeout_sec,
                    cwd=str(self.root_dir),
                    env=env,
                )
                exit_code = proc.returncode
                stdout_text = proc.stdout.decode("utf-8", errors="replace")
                stderr_text = proc.stderr.decode("utf-8", errors="replace")

                # If provider wrote to an output file, prefer that over stdout.
                raw_output = stdout_text
                if output_file is not None and output_file.exists():
                    raw_output = output_file.read_text(
                        encoding="utf-8", errors="replace"
                    )

                exit_kind = self._classify_exit_code(exit_code)
                status = "succeeded" if exit_code == 0 else "failed"
                parsed_envelope = self._parse_live_stdout(
                    stdout=raw_output,
                    stderr=stderr_text,
                    exit_code=exit_code,
                    adapter_request=adapter_request,
                )
            except subprocess.TimeoutExpired:
                exit_code = -1
                exit_kind = "timeout"
                status = "failed"
                stdout_text = ""
                stderr_text = "Process timed out."
                raw_output = ""
                parsed_envelope = _timeout_envelope(self.provider, timeout_sec)
            except FileNotFoundError:
                exit_code = -2
                exit_kind = "binary_not_found"
                status = "failed"
                stdout_text = ""
                stderr_text = f"Command not found: {cmd[0] if cmd else self.provider}"
                raw_output = ""
                parsed_envelope = _missing_binary_envelope(self.provider)
            except Exception as exc:  # noqa: BLE001
                exit_code = -3
                exit_kind = "execution_error"
                status = "failed"
                stdout_text = ""
                stderr_text = str(exc)
                raw_output = ""
                parsed_envelope = _error_envelope(self.provider, str(exc))

        completed_at = _isoformat(datetime.now(timezone.utc))
        session_result = self._build_live_session_result(
            adapter_request=adapter_request,
            stdout=stdout_text,
        )
        return AdapterInvocation(
            result_payload={
                "schemaVersion": ADAPTER_SCHEMA_VERSION,
                "taskId": adapter_request["taskId"],
                "provider": self.provider,
                "adapterVersion": self.adapter_version,
                "phase": adapter_request["phase"],
                "step": adapter_request["step"],
                "attempt": adapter_request["attempt"],
                "run": adapter_request["run"],
                "status": status,
                "executionMode": "live",
                "startedAt": started_at,
                "completedAt": completed_at,
                "exitStatus": {
                    "code": exit_code,
                    "kind": exit_kind,
                },
                "rawOutput": {
                    "captured": bool(raw_output),
                    "redacted": False,
                    "omissionReason": "" if raw_output else "no_output_captured",
                    "stderr": stderr_text[:4096] if stderr_text else "",
                },
                "session": session_result,
                "parsedEnvelope": parsed_envelope,
                "providerInvocation": adapter_request["providerInvocation"],
            },
            raw_output_text=raw_output or None,
        )

    def _classify_exit_code(self, code: int) -> str:
        if code == 0:
            return "success"
        if code == 124:
            return "timeout"
        return "error"

    def _build_live_session_result(
        self,
        *,
        adapter_request: dict[str, Any],
        stdout: str,
    ) -> dict[str, Any]:
        request_session = adapter_request.get("session", {})
        session_ref = self._extract_live_session_ref(
            stdout=stdout, adapter_request=adapter_request
        )
        return {
            "provider": self.provider,
            "requestedMode": request_session.get("requestedMode"),
            "resolvedMode": request_session.get("resolvedMode"),
            "resumeDecision": request_session.get("resumeDecision"),
            "resumeRefUsed": request_session.get("resumeRef") or "",
            "sessionRef": session_ref,
            "capabilityMetadata": request_session.get("capabilityMetadata", {}),
        }

    def _extract_live_session_ref(
        self, *, stdout: str, adapter_request: dict[str, Any]
    ) -> str:
        return self._generate_session_ref(adapter_request)

    @abstractmethod
    def _build_live_command_and_input(
        self,
        *,
        adapter_request: dict[str, Any],
        tmp_dir: Path,
    ) -> tuple[list[str], bytes | None, Path | None]:
        """Return (command_list, stdin_bytes_or_None, output_file_path_or_None)."""
        raise NotImplementedError

    def _build_live_env(self, *, adapter_request: dict[str, Any]) -> dict[str, str]:
        return {}

    def _parse_live_stdout(
        self,
        *,
        stdout: str,
        stderr: str,
        exit_code: int,
        adapter_request: dict[str, Any],
    ) -> dict[str, Any]:
        from agentorch_ctx.runtime.parser import parse_provider_output

        return parse_provider_output(stdout)

    def _build_session_contract(
        self,
        *,
        request: dict[str, Any],
        resolved_config: dict[str, Any],
        session_state: dict[str, Any],
    ) -> dict[str, Any]:
        facts = self._load_provider_facts(resolved_config)
        requested_mode = (
            "resume" if request.get("workflow_intent") == "resume" else "fresh"
        )
        prior_session_exists = bool(session_state)
        step_requires_resume = requested_mode == "resume"
        stored_session_ref = str(session_state.get("sessionRef") or "")
        resume_ref = self._resolve_resume_ref(
            stored_session_ref=stored_session_ref,
            facts=facts,
        )
        resume_state = self._capability_state(facts, "session.resume")
        resolved_mode = "fresh"
        resume_decision = "not_requested"
        fallback_reason = ""
        session_resume_blocked = False
        session_resume_blocked_reason = ""
        if requested_mode == "resume":
            if resume_state != "verified" and prior_session_exists:
                resolved_mode = "blocked"
                resume_decision = "blocked_provider_capability_mismatch"
                fallback_reason = "resume_not_verified"
                session_resume_blocked = True
                session_resume_blocked_reason = "provider_capability_mismatch"
            elif resume_state == "verified" and resume_ref:
                resolved_mode = "resume"
                resume_decision = "accepted"
            elif step_requires_resume and prior_session_exists:
                resolved_mode = "blocked"
                resume_decision = "blocked_missing_session_ref"
                fallback_reason = "resume_ref_unavailable"
                session_resume_blocked = True
                session_resume_blocked_reason = "missing_session_ref"
            else:
                resume_decision = "fresh_fallback"
                fallback_reason = self._resume_fallback_reason(
                    resume_state=resume_state,
                    stored_session_ref=stored_session_ref,
                    resume_ref=resume_ref,
                )
        return {
            "requestedMode": requested_mode,
            "resolvedMode": resolved_mode,
            "resumeDecision": resume_decision,
            "resumeRef": resume_ref,
            "fallbackReason": fallback_reason,
            "storedSessionRef": stored_session_ref,
            "resumeCursor": request.get("selectors", {}).get("resume_from", ""),
            "priorSessionExists": prior_session_exists,
            "stepRequiresResume": step_requires_resume,
            "sessionResumeBlocked": session_resume_blocked,
            "sessionResumeBlockedReason": session_resume_blocked_reason,
            "capabilityMetadata": {
                "resumeState": resume_state,
                "resumeInvokeShape": self._fact_value(
                    facts, "session.resume.headless", "invokeShape"
                ),
                "resumeLatestState": self._capability_state(
                    facts, "session.resume_latest"
                ),
                "resumeLatestInvokeShape": self._fact_value(
                    facts, "session.resume.latest", "invokeShape"
                ),
                "sessionIdFormat": self._fact_value(facts, "session.id.uuid", "format"),
                "sessionStoragePath": self._fact_value(
                    facts, "session.storage_path", "path"
                ),
            },
        }

    def _resolve_resume_ref(
        self,
        *,
        stored_session_ref: str,
        facts: list[dict[str, Any]],
    ) -> str | None:
        return stored_session_ref or None

    def _resume_fallback_reason(
        self,
        *,
        resume_state: str,
        stored_session_ref: str,
        resume_ref: str | None,
    ) -> str:
        if resume_state != "verified":
            return "resume_not_verified"
        if not stored_session_ref and not resume_ref:
            return "resume_ref_unavailable"
        return "fresh_execution_selected"

    def _build_session_result(self, adapter_request: dict[str, Any]) -> dict[str, Any]:
        request_session = adapter_request["session"]
        resume_ref = request_session.get("resumeRef")
        if request_session.get("sessionResumeBlocked"):
            session_ref = ""
        elif request_session.get("resolvedMode") == "resume" and resume_ref not in {
            None,
            "",
            "latest",
        }:
            session_ref = str(resume_ref)
        else:
            session_ref = self._generate_session_ref(adapter_request)
        return {
            "provider": self.provider,
            "requestedMode": request_session.get("requestedMode"),
            "resolvedMode": request_session.get("resolvedMode"),
            "resumeDecision": request_session.get("resumeDecision"),
            "resumeRefUsed": (
                (resume_ref or "")
                if request_session.get("resolvedMode") == "resume"
                else ""
            ),
            "sessionRef": session_ref,
            "sessionResumeBlocked": bool(request_session.get("sessionResumeBlocked")),
            "sessionResumeBlockedReason": request_session.get(
                "sessionResumeBlockedReason", ""
            ),
            "capabilityMetadata": request_session.get("capabilityMetadata", {}),
        }

    def _is_resume_blocked(self, adapter_request: dict[str, Any]) -> bool:
        session = adapter_request.get("session", {})
        return bool(session.get("sessionResumeBlocked"))

    def _resume_blocked_invocation(
        self, adapter_request: dict[str, Any]
    ) -> AdapterInvocation:
        started_at = _isoformat(datetime.now(timezone.utc))
        completed_at = _isoformat(datetime.now(timezone.utc))
        request_session = adapter_request.get("session", {})
        blocked_reason = str(
            request_session.get("sessionResumeBlockedReason")
            or "provider_capability_mismatch"
        )
        parsed_envelope = {
            "status": "blocked",
            "mode": "report_only",
            "summary": (
                "Resume blocked because an exact persisted sessionRef is required "
                f"({blocked_reason})."
            ),
            "warnings": [],
            "issues": [
                {
                    "code": blocked_reason,
                    "message": (
                        "Resume requested but no exact resumable session reference "
                        "is available for this task."
                    ),
                    "severity": "error",
                }
            ],
            "payload": {},
        }
        raw_output_text = (
            json.dumps(parsed_envelope, indent=2, ensure_ascii=True) + "\n"
        )
        return AdapterInvocation(
            result_payload={
                "schemaVersion": ADAPTER_SCHEMA_VERSION,
                "taskId": adapter_request["taskId"],
                "provider": self.provider,
                "adapterVersion": self.adapter_version,
                "phase": adapter_request["phase"],
                "step": adapter_request["step"],
                "attempt": adapter_request["attempt"],
                "run": adapter_request["run"],
                "status": "blocked",
                "executionMode": "live" if self.live_mode else "stub",
                "startedAt": started_at,
                "completedAt": completed_at,
                "exitStatus": {
                    "code": 0,
                    "kind": "blocked_preflight",
                },
                "rawOutput": {
                    "captured": True,
                    "redacted": False,
                    "omissionReason": "",
                },
                "session": self._build_session_result(adapter_request),
                "parsedEnvelope": parsed_envelope,
                "providerInvocation": adapter_request["providerInvocation"],
            },
            raw_output_text=raw_output_text,
        )

    def _build_parsed_envelope(self, adapter_request: dict[str, Any]) -> dict[str, Any]:
        operation = self._build_stub_operation(adapter_request)
        warnings = [
            {
                "code": "STUB_ADAPTER",
                "message": "Provider output was generated by a stub adapter.",
                "severity": "warning",
            }
        ]
        if operation:
            return {
                "status": "success",
                "mode": operation["mode"],
                "summary": (
                    f"{self.provider} stub prepared {operation['mode']} output for "
                    f"{operation['targetPath']}."
                ),
                "warnings": warnings,
                "issues": [],
                "payload": {"operations": [operation]},
            }
        if adapter_request.get("phase") == "plan":
            return {
                "status": "partial",
                "mode": "report_only",
                "summary": f"{self.provider} stub prepared plan guidance.",
                "warnings": warnings,
                "issues": [],
                "payload": {
                    "reports": [
                        {
                            "id": "stub-plan-1",
                            "summary": self._build_stub_plan_report(adapter_request),
                        }
                    ]
                },
            }
        summary = f"{self.provider} stub prepared {adapter_request['phase']} guidance."
        return {
            "status": "partial",
            "mode": "report_only",
            "summary": summary,
            "warnings": warnings,
            "issues": [],
            "payload": {
                "reports": [
                    {
                        "id": "stub-report-1",
                        "summary": (
                            f"{self.provider} stub executed in "
                            f"{adapter_request['session']['resolvedMode']} mode."
                        ),
                    }
                ],
                "findings": [
                    {
                        "id": "stub-finding-1",
                        "summary": (
                            f"model={adapter_request['modelRef']} "
                            f"strategy={adapter_request['phaseOptions'].get('budgetProfileRef', '')}"
                        ),
                    }
                ],
            },
        }

    def _build_stub_operation(
        self, adapter_request: dict[str, Any]
    ) -> dict[str, Any] | None:
        output_contract = adapter_request.get("outputContract", {})
        allowed_modes = set(output_contract.get("allowedModes", []))
        preferred_mode = output_contract.get("preferredMode")
        operations_required = bool(output_contract.get("operationsRequired"))
        target_paths = list(adapter_request.get("targets", {}).get("paths", []))
        if not target_paths:
            return None
        if adapter_request.get("phase") != "impl" and not operations_required:
            return None

        target_path = target_paths[0]
        absolute_target = (self.root_dir / target_path).resolve()
        if not str(absolute_target).startswith(str(self.root_dir)):
            return None

        marker = self._stub_marker(
            phase=adapter_request["phase"],
            step=adapter_request["step"],
            model_ref=adapter_request["modelRef"],
        )
        if absolute_target.exists() and "patch" in allowed_modes:
            try:
                current = absolute_target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return None
            content = current if marker in current else _append_line(current, marker)
            return {
                "operationId": "stub-op-1",
                "kind": "patch",
                "targetPath": target_path,
                "mode": "patch",
                "baseFingerprint": "sha256:stub-ok",
                "expectedExistingPathState": "present",
                "riskLevel": "low",
                "requiresApproval": False,
                "scopeCheck": "passed",
                "confidence": 0.95,
                "sourceRunRefs": [f"stub:{self.provider}:{adapter_request['phase']}"],
                "validationRefs": [],
                "estimatedChangedLines": 1 if marker not in current else 0,
                "estimatedChangedBytes": len(content.encode("utf-8"))
                - len(current.encode("utf-8")),
                "content": content,
            }
        if (
            not absolute_target.exists()
            and preferred_mode == "create_file"
            and "create_file" in allowed_modes
        ):
            content = marker + "\n"
            return {
                "operationId": "stub-op-1",
                "kind": "create_file",
                "targetPath": target_path,
                "mode": "create_file",
                "baseFingerprint": "sha256:stub-new",
                "expectedExistingPathState": "absent",
                "riskLevel": "low",
                "requiresApproval": False,
                "scopeCheck": "passed",
                "confidence": 0.95,
                "sourceRunRefs": [f"stub:{self.provider}:{adapter_request['phase']}"],
                "validationRefs": [],
                "estimatedChangedLines": 1,
                "estimatedChangedBytes": len(content.encode("utf-8")),
                "content": content,
            }
        return None

    def _build_stub_plan_report(self, adapter_request: dict[str, Any]) -> str:
        target_paths = self._stub_plan_target_paths(adapter_request)
        plan_payload = {
            "summary": str(adapter_request.get("summary") or "Stub plan output"),
            "implementationSteps": [
                {
                    "id": "S01",
                    "description": "Review the task context and map the work into concrete steps",
                    "targetFiles": target_paths,
                    "dependsOn": [],
                }
            ],
            "targetPaths": target_paths,
            "checklist": [
                {
                    "id": "C001",
                    "description": "Confirm the scoped files and execution order",
                    "category": "impl",
                    "status": "pending",
                    "targetFiles": target_paths,
                    "dependsOn": [],
                }
            ],
        }
        return (
            "```json\n"
            + json.dumps(plan_payload, indent=2, ensure_ascii=True)
            + "\n```"
        )

    def _stub_plan_target_paths(self, adapter_request: dict[str, Any]) -> list[str]:
        target_paths = [
            str(path).strip()
            for path in adapter_request.get("targets", {}).get("paths", [])
            if str(path).strip()
        ]
        if target_paths:
            return target_paths

        request_ref = str(
            adapter_request.get("inputRefs", {}).get("request", "")
        ).strip()
        if request_ref:
            try:
                request_payload = json.loads(
                    Path(request_ref).read_text(encoding="utf-8")
                )
            except (OSError, ValueError, TypeError):
                request_payload = {}
            source_path = str(request_payload.get("source", {}).get("path", "")).strip()
            if source_path:
                resolved_source = Path(source_path).expanduser()
                try:
                    return [
                        resolved_source.resolve().relative_to(self.root_dir).as_posix()
                    ]
                except ValueError:
                    return [resolved_source.as_posix()]

        return ["task-input.md"]

    def _stub_marker(self, *, phase: str, step: str, model_ref: str | None) -> str:
        return f"stub:{self.provider}:{phase}:{step}:{model_ref or 'default'}"

    def _generate_session_ref(self, adapter_request: dict[str, Any]) -> str:
        seed = (
            f"{self.provider}:{adapter_request['taskId']}:{adapter_request['phase']}:"
            f"{adapter_request['step']}:{adapter_request['attempt']}:{adapter_request['run']}"
        )
        return str(uuid5(NAMESPACE_URL, seed))

    def _load_provider_facts(
        self, resolved_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for ref in resolved_config.get("facts", {}).get("verifiedFactRefs", []):
            path = Path(ref)
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            for record in payload.get("records", []):
                if record.get("provider") == self.provider:
                    facts.append(record)
        return facts

    def _capability_state(self, facts: list[dict[str, Any]], capability_id: str) -> str:
        for record in facts:
            if record.get("capabilityId") == capability_id:
                return str(record.get("state", "unknown"))
        return "unknown"

    def _fact_value(self, facts: list[dict[str, Any]], fact_id: str, field: str) -> str:
        for record in facts:
            if record.get("factId") == fact_id:
                value = record.get("value", {})
                if isinstance(value, dict):
                    extracted = value.get(field, "")
                    return "" if extracted is None else str(extracted)
        return ""

    @abstractmethod
    def _build_provider_invocation(
        self,
        *,
        provider_config: dict[str, Any],
        session_contract: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


def _append_line(content: str, line: str) -> str:
    if not content:
        return line + "\n"
    if content.endswith("\n"):
        return content + line + "\n"
    return content + "\n" + line + "\n"


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _timeout_envelope(provider: str, timeout_sec: int) -> dict[str, Any]:
    return {
        "status": "failed",
        "mode": "report_only",
        "summary": f"{provider} execution timed out after {timeout_sec}s.",
        "warnings": [],
        "issues": [
            {
                "code": "TIMEOUT",
                "message": f"Provider CLI timed out after {timeout_sec} seconds.",
                "severity": "error",
            }
        ],
        "payload": {},
    }


def _missing_binary_envelope(provider: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "mode": "report_only",
        "summary": f"{provider} CLI binary not found on PATH.",
        "warnings": [],
        "issues": [
            {
                "code": "BINARY_NOT_FOUND",
                "message": f"Provider CLI '{provider}' is not installed or not on PATH.",
                "severity": "error",
            }
        ],
        "payload": {},
    }


def _error_envelope(provider: str, message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "mode": "report_only",
        "summary": f"{provider} execution error: {message[:200]}",
        "warnings": [],
        "issues": [
            {
                "code": "EXECUTION_ERROR",
                "message": message[:500],
                "severity": "error",
            }
        ],
        "payload": {},
    }


def _build_exec_env() -> dict[str, str]:
    """Build an environment for live subprocess calls with augmented PATH."""
    env = dict(os.environ)
    current_path = env.get("PATH", "")
    extra_paths = []
    repo_root = Path(__file__).resolve().parents[3]
    if (repo_root / "agentorch").is_file():
        extra_paths.append(str(repo_root))
    # NVM node versions (all installed versions, newest first).
    nvm_versions_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_versions_dir.is_dir():
        for version_dir in sorted(nvm_versions_dir.iterdir(), reverse=True):
            bin_dir = version_dir / "bin"
            if bin_dir.is_dir():
                extra_paths.append(str(bin_dir))
    # Other common tool locations.
    for candidate in [
        str(Path.home() / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]:
        if Path(candidate).is_dir():
            extra_paths.append(candidate)
    existing = [p for p in current_path.split(os.pathsep) if p]
    seen: set[str] = set()
    merged: list[str] = []
    for p in extra_paths + existing:
        if p not in seen:
            seen.add(p)
            merged.append(p)
    env["PATH"] = os.pathsep.join(merged)
    return env
