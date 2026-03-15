from __future__ import annotations

from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.providers.base import ProviderAdapter


class CodexAdapter(ProviderAdapter):
    provider = "codex"

    def _build_provider_invocation(
        self,
        *,
        provider_config: dict[str, Any],
        session_contract: dict[str, Any],
    ) -> dict[str, Any]:
        subcommand = ["exec"]
        if session_contract.get("resolvedMode") == "resume":
            subcommand.append("resume")
        return {
            "command": provider_config.get("command"),
            "subcommand": subcommand,
            "modelOption": {
                "flag": "--model",
                "value": provider_config.get("modelRef"),
            },
            "reasoningEffort": provider_config.get("options", {}).get(
                "reasoningEffort", ""
            ),
            "structuredOutput": {
                "mode": "output_last_message",
                "liveValidated": False,
            },
            "resumeRef": session_contract.get("resumeRef", ""),
        }

    def _build_live_command_and_input(
        self,
        *,
        adapter_request: dict[str, Any],
        tmp_dir: Path,
    ) -> tuple[list[str], bytes | None, Path | None]:
        model_id = adapter_request.get("model") or "gpt-5.1-codex-mini"
        session = adapter_request.get("session", {})
        is_resume = session.get("resolvedMode") == "resume"
        resume_ref = session.get("resumeRef", "")
        phase = str(adapter_request.get("phase", ""))
        sandbox_mode = "workspace-write" if phase == "impl" else "read-only"
        prompt_text = adapter_request.get("promptText") or adapter_request.get(
            "summary", ""
        )
        reasoning_effort = _normalize_codex_reasoning_effort(
            adapter_request.get("providerOptions", {}).get("reasoningEffort", "")
        )

        output_file = tmp_dir / "codex-output.txt"
        shared_args = [
            "--model",
            model_id,
            "--output-last-message",
            str(output_file),
            "--sandbox",
            sandbox_mode,
        ]
        if adapter_request.get("providerOptions", {}).get("skipGitRepoCheck"):
            shared_args.append("--skip-git-repo-check")
        if reasoning_effort:
            shared_args += ["-c", f"model_reasoning_effort={reasoning_effort}"]
        if phase == "impl":
            shared_args.append("--dangerously-bypass-approvals-and-sandbox")

        if is_resume and resume_ref:
            resume_args = ["codex", "exec", "resume"]
            if resume_ref == "latest":
                resume_args.append("--last")
            else:
                resume_args.append(resume_ref)
            cmd = [*resume_args, *shared_args]
            stdin_bytes = prompt_text.encode("utf-8") if prompt_text else None
        else:
            cmd = ["codex", "exec", "-", *shared_args]
            stdin_bytes = prompt_text.encode("utf-8") if prompt_text else b""

        return cmd, stdin_bytes, output_file

    def _parse_live_stdout(
        self,
        *,
        stdout: str,
        stderr: str,
        exit_code: int,
        adapter_request: dict[str, Any],
    ) -> dict[str, Any]:
        from agentorch_ctx.runtime.parser import parse_provider_output

        text = stdout.strip()
        if not text:
            return {
                "status": "failed" if exit_code != 0 else "partial",
                "mode": "report_only",
                "summary": f"codex returned no output (exit={exit_code}).",
                "warnings": [],
                "issues": [
                    {
                        "code": "NO_OUTPUT",
                        "message": stderr[:500] if stderr else "No output captured.",
                        "severity": "warning" if exit_code == 0 else "error",
                    }
                ],
                "payload": {},
            }
        parsed = parse_provider_output(text)
        parsed["executionMeta"] = {
            "provider": "codex",
            "exitCode": exit_code,
            "stderrSnippet": stderr[:200] if stderr else "",
        }
        return parsed


def _normalize_codex_reasoning_effort(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw == "mid":
        return "medium"
    return raw
