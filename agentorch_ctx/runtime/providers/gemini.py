from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.providers.base import AdapterInvocation, ProviderAdapter

_GEMINI3_THINKING_LEVELS = {
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
}

_GEMINI25_THINKING_BUDGETS = {
    "minimal": 0,
    "low": 2048,
    "medium": 8192,
    "high": -1,
    "xhigh": -1,
}

_GEMINI_MODEL_FALLBACKS = {
    "gemini-3.1-pro-preview": "gemini-3-pro-preview",
}


def _detect_gemini_series(model_id: str) -> str:
    m = str(model_id or "").lower()
    if "gemini-3" in m or m in ("flash", "auto", "pro"):
        return "3"
    return "2.5"


def _build_gemini_thinking_config(model_id: str, effort: str) -> dict[str, object]:
    normalized_effort = str(effort or "").strip().lower()
    series = _detect_gemini_series(model_id)
    if series == "3":
        return {
            "thinkingLevel": _GEMINI3_THINKING_LEVELS.get(normalized_effort, "medium")
        }
    return {"thinkingBudget": _GEMINI25_THINKING_BUDGETS.get(normalized_effort, -1)}


def _gemini_fallback_model(model_id: str) -> str | None:
    normalized = str(model_id or "").strip()
    return _GEMINI_MODEL_FALLBACKS.get(normalized)


def _gemini_model_not_found(invocation: AdapterInvocation) -> bool:
    payload = invocation.result_payload
    if payload.get("status") != "failed":
        return False
    parsed = payload.get("parsedEnvelope", {})
    raw_output = payload.get("rawOutput", {})
    issue_messages = [
        str(issue.get("message", ""))
        for issue in parsed.get("issues", [])
        if isinstance(issue, dict)
    ]
    haystack = "\n".join(
        [
            str(parsed.get("summary", "")),
            str(raw_output.get("stderr", "")),
            *issue_messages,
        ]
    ).lower()
    return (
        "modelnotfounderror" in haystack
        or "requested entity was not found" in haystack
        or "model not found" in haystack
    )


def _annotate_gemini_fallback_result(
    *,
    invocation: AdapterInvocation,
    original_model: str,
    fallback_model: str,
) -> AdapterInvocation:
    payload = deepcopy(invocation.result_payload)
    parsed = payload.setdefault("parsedEnvelope", {})
    warnings = list(parsed.get("warnings", []))
    warnings.append(
        {
            "code": "MODEL_FALLBACK",
            "message": (
                "gemini model fallback applied: "
                f"{original_model} -> {fallback_model}"
            ),
            "severity": "warning",
        }
    )
    parsed["warnings"] = warnings
    execution_meta = parsed.setdefault("executionMeta", {})
    if isinstance(execution_meta, dict):
        execution_meta["modelFallback"] = {
            "from": original_model,
            "to": fallback_model,
            "reason": "model_not_found",
        }
    provider_invocation = payload.setdefault("providerInvocation", {})
    if isinstance(provider_invocation, dict):
        provider_invocation["fallbackFromModel"] = original_model
        model_option = provider_invocation.get("modelOption")
        if isinstance(model_option, dict):
            model_option["value"] = fallback_model
    payload["modelRef"] = fallback_model
    payload["model"] = fallback_model
    return AdapterInvocation(
        result_payload=payload,
        raw_output_text=invocation.raw_output_text,
    )


class GeminiAdapter(ProviderAdapter):
    provider = "gemini"

    def _execute_live(self, *, adapter_request: dict[str, Any]) -> AdapterInvocation:
        invocation = super()._execute_live(adapter_request=adapter_request)
        original_model = str(adapter_request.get("model") or "")
        fallback_model = _gemini_fallback_model(original_model)
        if not fallback_model or not _gemini_model_not_found(invocation):
            return invocation

        fallback_request = deepcopy(adapter_request)
        fallback_request["modelRef"] = fallback_model
        fallback_request["model"] = fallback_model
        fallback_request.setdefault("providerOptions", {})["model"] = fallback_model
        provider_invocation = deepcopy(fallback_request.get("providerInvocation", {}))
        model_option = provider_invocation.get("modelOption")
        if isinstance(model_option, dict):
            model_option["value"] = fallback_model
        fallback_request["providerInvocation"] = provider_invocation

        fallback_invocation = super()._execute_live(adapter_request=fallback_request)
        return _annotate_gemini_fallback_result(
            invocation=fallback_invocation,
            original_model=original_model,
            fallback_model=fallback_model,
        )

    def _resolve_resume_ref(
        self,
        *,
        stored_session_ref: str,
        facts: list[dict[str, object]],
    ) -> str | None:
        if stored_session_ref:
            return stored_session_ref
        return None

    def _build_provider_invocation(
        self,
        *,
        provider_config: dict[str, object],
        session_contract: dict[str, object],
    ) -> dict[str, object]:
        return {
            "command": provider_config.get("command"),
            "resumeFlag": {
                "flag": "--resume",
                "value": session_contract.get("resumeRef") or "",
            },
            "modelOption": {
                "flag": "--model",
                "value": provider_config.get("modelRef"),
            },
            "outputFormat": "json",
            "mode": provider_config.get("options", {}).get("mode", "default"),
        }

    def _build_live_command_and_input(
        self,
        *,
        adapter_request: dict[str, Any],
        tmp_dir: Path,
    ) -> tuple[list[str], bytes | None, Path | None]:
        model_id = adapter_request.get("model") or "gemini-2.5-flash-lite"
        effort = (
            str(adapter_request.get("providerOptions", {}).get("reasoningEffort", ""))
            .strip()
            .lower()
        )
        session = adapter_request.get("session", {})
        resume_ref = session.get("resumeRef", "")
        is_resume = session.get("resolvedMode") == "resume" and bool(resume_ref)

        prompt_text = adapter_request.get("promptText") or adapter_request.get(
            "summary", ""
        )

        effective_model = model_id
        self._pending_settings_path = ""
        if effort:
            thinking_config = _build_gemini_thinking_config(model_id, effort)
            alias_name = "_collab_thinking"
            settings = {
                "modelConfigs": {
                    "customAliases": {
                        alias_name: {
                            "modelConfig": {
                                "model": model_id,
                                "generateContentConfig": {
                                    "thinkingConfig": thinking_config
                                },
                            }
                        }
                    }
                }
            }
            settings_path = tmp_dir / "gemini-thinking-settings.json"
            settings_path.write_text(
                json.dumps(settings, ensure_ascii=True), encoding="utf-8"
            )
            self._pending_settings_path = str(settings_path)
            effective_model = alias_name

        cmd = [
            "gemini",
            "--model",
            effective_model,
            "--output-format",
            "json",
            "--yolo",
        ]
        if is_resume:
            cmd += ["--resume", resume_ref]

        stdin_bytes = prompt_text.encode("utf-8") if prompt_text else b"say hello"
        return cmd, stdin_bytes, None

    def _build_live_env(self, *, adapter_request: dict[str, Any]) -> dict[str, str]:
        path = getattr(self, "_pending_settings_path", "")
        self._pending_settings_path = ""
        if path:
            return {"GEMINI_CLI_SYSTEM_SETTINGS_PATH": path}
        return {}

    def _parse_live_stdout(
        self,
        *,
        stdout: str,
        stderr: str,
        exit_code: int,
        adapter_request: dict[str, Any],
    ) -> dict[str, Any]:
        exit_codes = {
            0: "success",
            1: "general_error",
            42: "input_error",
            53: "turn_limit_exceeded",
        }
        exit_kind = exit_codes.get(exit_code, f"exit_{exit_code}")

        if exit_code != 0:
            return {
                "status": "failed",
                "mode": "report_only",
                "summary": f"gemini exited with code {exit_code} ({exit_kind}).",
                "warnings": [],
                "issues": [
                    {
                        "code": f"EXIT_{exit_code}",
                        "message": stderr[:500] if stderr else stdout[:200],
                        "severity": "error",
                    }
                ],
                "payload": {},
                "executionMeta": {
                    "provider": "gemini",
                    "exitCode": exit_code,
                    "exitKind": exit_kind,
                },
            }

        text = stdout.strip()
        try:
            data = json.loads(text)
            response_text = data.get("response", "")
            stats = data.get("stats", {})
            error = data.get("error")
            if error:
                return {
                    "status": "failed",
                    "mode": "report_only",
                    "summary": f"gemini reported an error: {error}",
                    "warnings": [],
                    "issues": [
                        {
                            "code": "PROVIDER_ERROR",
                            "message": str(error)[:500],
                            "severity": "error",
                        }
                    ],
                    "payload": {},
                    "executionMeta": {
                        "provider": "gemini",
                        "exitCode": exit_code,
                        "stats": stats,
                    },
                }
            from agentorch_ctx.runtime.parser import parse_provider_output

            parsed = parse_provider_output(response_text)
            parsed["executionMeta"] = {
                "provider": "gemini",
                "exitCode": exit_code,
                "tokenStats": stats,
                "rawResponseLength": len(response_text),
            }
            return parsed
        except (json.JSONDecodeError, ValueError):
            from agentorch_ctx.runtime.parser import parse_provider_output

            parsed = parse_provider_output(text)
            parsed["executionMeta"] = {
                "provider": "gemini",
                "exitCode": exit_code,
                "warning": "output was not valid JSON; parsed as plain text",
            }
            return parsed

    def _extract_live_session_ref(
        self, *, stdout: str, adapter_request: dict[str, Any]
    ) -> str:
        text = stdout.strip()
        if not text:
            return self._generate_session_ref(adapter_request)
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
                if event.get("type") == "init" and "session_id" in event:
                    return str(event["session_id"])
            except (json.JSONDecodeError, ValueError):
                continue
        return self._generate_session_ref(adapter_request)


GeminiProvider = GeminiAdapter
