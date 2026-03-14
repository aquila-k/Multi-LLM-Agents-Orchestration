from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from collab.runtime.providers.base import ProviderAdapter

_COPILOT_PROMPT_BYTE_LIMIT = 48_000
_TRUNCATION_SUFFIX = " [TRUNCATED]"
LOGGER = logging.getLogger(__name__)


class CopilotAdapter(ProviderAdapter):
    provider = "copilot"

    def _build_provider_invocation(
        self,
        *,
        provider_config: dict[str, object],
        session_contract: dict[str, object],
    ) -> dict[str, object]:
        return {
            "command": provider_config.get("command"),
            "headlessPromptMode": True,
            "resumeFlag": {
                "flag": "--resume",
                "requested": session_contract.get("requestedMode") == "resume",
                "applied": session_contract.get("resolvedMode") == "resume",
            },
            "continueFlag": {
                "flag": "--continue",
                "requested": False,
            },
            "modelOption": {
                "flag": "--model",
                "value": provider_config.get("modelRef"),
            },
            "reasoningEffort": provider_config.get("options", {}).get(
                "reasoningEffort", ""
            ),
        }

    def _build_live_command_and_input(
        self,
        *,
        adapter_request: dict[str, Any],
        tmp_dir: Path,
    ) -> tuple[list[str], bytes | None, Path | None]:
        model_id = adapter_request.get("model") or "gpt-5-mini"
        session = adapter_request.get("session", {})
        is_resume = session.get("resolvedMode") == "resume"
        resume_ref = session.get("resumeRef", "")

        prompt_text = (
            adapter_request.get("promptText") or adapter_request.get("summary", "")
        ).strip()
        if not prompt_text:
            prompt_text = "say hello"

        prompt_text, was_truncated = _truncate_prompt_text(
            prompt_text, byte_limit=_COPILOT_PROMPT_BYTE_LIMIT
        )
        if was_truncated:
            LOGGER.warning(
                "copilot prompt exceeded %s bytes and was truncated",
                _COPILOT_PROMPT_BYTE_LIMIT,
            )

        cmd = [
            "copilot",
            "--model",
            model_id,
            "-p",
            prompt_text,
            "--silent",
            "--allow-all-tools",
            "--no-ask-user",
            "--no-color",
        ]

        if is_resume and resume_ref:
            cmd += ["--resume", resume_ref]

        return cmd, None, None

    def _parse_live_stdout(
        self,
        *,
        stdout: str,
        stderr: str,
        exit_code: int,
        adapter_request: dict[str, Any],
    ) -> dict[str, Any]:
        from collab.runtime.parser import parse_provider_output

        text = stdout.strip()
        if not text and exit_code != 0:
            return {
                "status": "failed",
                "mode": "report_only",
                "summary": f"copilot exited with code {exit_code}.",
                "warnings": [],
                "issues": [
                    {
                        "code": f"EXIT_{exit_code}",
                        "message": stderr[:500] if stderr else "No output captured.",
                        "severity": "error",
                    }
                ],
                "payload": {},
                "executionMeta": {"provider": "copilot", "exitCode": exit_code},
            }
        parsed = parse_provider_output(text)
        parsed["executionMeta"] = {
            "provider": "copilot",
            "exitCode": exit_code,
            "stderrSnippet": stderr[:200] if stderr else "",
        }
        return parsed

    def _generate_session_ref(self, adapter_request: dict[str, Any]) -> str:
        return (
            f"copilot-live-{adapter_request['taskId']}-"
            f"{adapter_request['phase']}-{adapter_request['step']}"
        )

    def _build_live_env(self, *, adapter_request: dict[str, Any]) -> dict[str, str]:
        reasoning_effort = _normalize_copilot_reasoning_effort(
            adapter_request.get("providerOptions", {}).get("reasoningEffort", "")
        )
        if not reasoning_effort:
            return {}
        # COPILOT_REASONING_EFFORT is not listed in official CLI docs (no CLI flag
        # exists for per-call effort override). However, live testing confirmed it
        # is honored at runtime: xhigh produces ~2x larger reasoningOpaque blobs
        # vs low/medium/high. Persistent fallback: `reasoning_effort` in
        # ~/.copilot/config.json. Note: gpt-5-mini/gpt-4.1 ignore it (no
        # extended thinking support on free-tier models).
        return {"COPILOT_REASONING_EFFORT": reasoning_effort}


def _truncate_prompt_text(text: str, *, byte_limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= byte_limit:
        return text, False

    suffix_bytes = _TRUNCATION_SUFFIX.encode("utf-8")
    available = max(0, byte_limit - len(suffix_bytes))
    truncated = encoded[:available].decode("utf-8", errors="ignore")
    truncated = _truncate_to_last_whitespace(truncated)
    if not truncated:
        truncated = encoded[:available].decode("utf-8", errors="ignore").rstrip()

    candidate = f"{truncated}{_TRUNCATION_SUFFIX}" if truncated else _TRUNCATION_SUFFIX
    while len(candidate.encode("utf-8")) > byte_limit and truncated:
        truncated = truncated[:-1].rstrip()
        candidate = (
            f"{truncated}{_TRUNCATION_SUFFIX}" if truncated else _TRUNCATION_SUFFIX
        )
    return candidate, True


def _truncate_to_last_whitespace(text: str) -> str:
    stripped = text.rstrip()
    last_space = max(
        stripped.rfind(" "),
        stripped.rfind("\n"),
        stripped.rfind("\t"),
        stripped.rfind("\r"),
    )
    if last_space > 0:
        return stripped[:last_space].rstrip()
    return stripped


def _normalize_copilot_reasoning_effort(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw == "mid":
        return "medium"
    return raw
