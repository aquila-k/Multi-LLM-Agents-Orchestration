from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collab.runtime.mutation_authority import (
    authority_allows_direct_write,
    authority_requires_apply_executor,
    resolve_mutation_authority,
)
from collab.runtime.providers import get_provider_adapter
from collab.runtime.providers.gemini import _build_gemini_thinking_config


class ProviderAdaptersUnitTest(unittest.TestCase):
    def test_codex_resume_uses_persisted_session_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = get_provider_adapter("codex", root_dir=root)

            request_payload = self._build_request_payload(
                "codex", workflow_intent="resume"
            )
            adapter_request = adapter.build_request(
                task_id="task-1",
                phase="impl",
                step="apply",
                attempt=1,
                run=1,
                request=request_payload,
                request_ref="/tmp/request.json",
                resolved_config=self._build_resolved_config("codex"),
                resolved_config_ref="/tmp/resolved-config.json",
                routing_result_ref="/tmp/routing.json",
                prompt_bundle=self._build_prompt_bundle(),
                prompt_bundle_ref="/tmp/prompt.json",
                manifest_ref="/tmp/manifest.json",
                session_state={"sessionRef": "11111111-2222-3333-4444-555555555555"},
                session_state_ref="/tmp/session-state.json",
                artifact_destinations={"adapterRequest": "/tmp/adapter-request.json"},
            )

            self.assertEqual(adapter_request["session"]["requestedMode"], "resume")
            self.assertEqual(adapter_request["session"]["resolvedMode"], "resume")
            self.assertEqual(
                adapter_request["session"]["resumeRef"],
                "11111111-2222-3333-4444-555555555555",
            )
            self.assertEqual(
                adapter_request["providerInvocation"]["subcommand"],
                ["exec", "resume"],
            )

    def test_gemini_resume_without_stored_ref_uses_none_and_fresh_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = get_provider_adapter("gemini", root_dir=root)

            adapter_request = adapter.build_request(
                task_id="task-2",
                phase="plan",
                step="analysis",
                attempt=1,
                run=1,
                request=self._build_request_payload("gemini", workflow_intent="resume"),
                request_ref="/tmp/request.json",
                resolved_config=self._build_resolved_config("gemini"),
                resolved_config_ref="/tmp/resolved-config.json",
                routing_result_ref="/tmp/routing.json",
                prompt_bundle=self._build_prompt_bundle(),
                prompt_bundle_ref="/tmp/prompt.json",
                manifest_ref="/tmp/manifest.json",
                session_state=None,
                session_state_ref="",
                artifact_destinations={"adapterRequest": "/tmp/adapter-request.json"},
            )

            self.assertEqual(adapter_request["session"]["resolvedMode"], "fresh")
            self.assertIsNone(adapter_request["session"]["resumeRef"])
            self.assertEqual(
                adapter_request["providerInvocation"]["resumeFlag"]["value"], ""
            )

    def test_gemini_resume_blocks_when_prior_session_exists_without_exact_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = get_provider_adapter("gemini", root_dir=root)
            adapter_request = adapter.build_request(
                task_id="task-2b",
                phase="plan",
                step="analysis",
                attempt=1,
                run=1,
                request=self._build_request_payload("gemini", workflow_intent="resume"),
                request_ref="/tmp/request.json",
                resolved_config=self._build_resolved_config("gemini"),
                resolved_config_ref="/tmp/resolved-config.json",
                routing_result_ref="/tmp/routing.json",
                prompt_bundle=self._build_prompt_bundle(),
                prompt_bundle_ref="/tmp/prompt.json",
                manifest_ref="/tmp/manifest.json",
                session_state={
                    "provider": "gemini",
                    "requestedMode": "resume",
                    "resolvedMode": "resume",
                    "sessionRef": "",
                },
                session_state_ref="/tmp/session-state.json",
                artifact_destinations={"adapterRequest": "/tmp/adapter-request.json"},
            )
            self.assertEqual(adapter_request["session"]["resolvedMode"], "blocked")
            self.assertTrue(adapter_request["session"]["sessionResumeBlocked"])
            self.assertEqual(
                adapter_request["session"]["sessionResumeBlockedReason"],
                "missing_session_ref",
            )

            invocation = adapter.execute(adapter_request=adapter_request)
            self.assertEqual(invocation.result_payload["status"], "blocked")
            self.assertEqual(
                invocation.result_payload["parsedEnvelope"]["issues"][0]["code"],
                "missing_session_ref",
            )
            self.assertEqual(
                invocation.result_payload["session"]["sessionRef"],
                "",
            )

    def test_copilot_resume_without_verified_capability_blocks_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = get_provider_adapter("copilot", root_dir=root)

            adapter_request = adapter.build_request(
                task_id="task-3",
                phase="review",
                step="analysis",
                attempt=1,
                run=1,
                request=self._build_request_payload(
                    "copilot", workflow_intent="resume"
                ),
                request_ref="/tmp/request.json",
                resolved_config=self._build_resolved_config("copilot"),
                resolved_config_ref="/tmp/resolved-config.json",
                routing_result_ref="/tmp/routing.json",
                prompt_bundle=self._build_prompt_bundle(),
                prompt_bundle_ref="/tmp/prompt.json",
                manifest_ref="/tmp/manifest.json",
                session_state={"sessionRef": "copilot-session-001"},
                session_state_ref="/tmp/session-state.json",
                artifact_destinations={"adapterRequest": "/tmp/adapter-request.json"},
            )

            self.assertEqual(adapter_request["session"]["requestedMode"], "resume")
            self.assertEqual(adapter_request["session"]["resolvedMode"], "blocked")
            self.assertEqual(
                adapter_request["session"]["fallbackReason"], "resume_not_verified"
            )
            self.assertEqual(
                adapter_request["session"]["sessionResumeBlockedReason"],
                "provider_capability_mismatch",
            )

    def test_gemini_thinking_config_gemini3_effort_low(self) -> None:
        self.assertEqual(
            _build_gemini_thinking_config("gemini-3-flash-preview", "low"),
            {"thinkingLevel": "low"},
        )

    def test_gemini_thinking_config_gemini25_effort_medium(self) -> None:
        self.assertEqual(
            _build_gemini_thinking_config("gemini-2.5-pro", "medium"),
            {"thinkingBudget": 8192},
        )

    def test_gemini_thinking_config_xhigh_normalized(self) -> None:
        self.assertEqual(
            _build_gemini_thinking_config("gemini-3.1-pro-preview", "xhigh"),
            {"thinkingLevel": "high"},
        )
        self.assertEqual(
            _build_gemini_thinking_config("gemini-2.5-flash", "xhigh"),
            {"thinkingBudget": -1},
        )

    def test_gemini_thinking_config_minimal_disables_thinking(self) -> None:
        self.assertEqual(
            _build_gemini_thinking_config("gemini-2.5-flash-lite", "minimal"),
            {"thinkingBudget": 0},
        )
        self.assertEqual(
            _build_gemini_thinking_config("gemini-3-flash-preview", "minimal"),
            {"thinkingLevel": "minimal"},
        )

    def test_gemini_adapter_writes_settings_file_when_effort_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = get_provider_adapter("gemini", root_dir=root, live_mode=True)
            adapter_request = {
                "model": "gemini-3-flash-preview",
                "providerOptions": {"reasoningEffort": "low"},
                "session": {"resolvedMode": "fresh", "resumeRef": ""},
                "promptText": "hello",
                "summary": "hello",
            }

            cmd, stdin_bytes, output_file = adapter._build_live_command_and_input(
                adapter_request=adapter_request,
                tmp_dir=root,
            )

            self.assertIn("--model", cmd)
            self.assertEqual(cmd[cmd.index("--model") + 1], "_collab_thinking")
            self.assertEqual(stdin_bytes, b"hello")
            self.assertIsNone(output_file)

            settings_path = root / "gemini-thinking-settings.json"
            self.assertTrue(settings_path.exists())
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")),
                {
                    "modelConfigs": {
                        "customAliases": {
                            "_collab_thinking": {
                                "modelConfig": {
                                    "model": "gemini-3-flash-preview",
                                    "generateContentConfig": {
                                        "thinkingConfig": {"thinkingLevel": "low"}
                                    },
                                }
                            }
                        }
                    }
                },
            )
            self.assertEqual(
                adapter._build_live_env(adapter_request=adapter_request),
                {"GEMINI_CLI_SYSTEM_SETTINGS_PATH": str(settings_path)},
            )

    def test_gemini_adapter_no_settings_file_when_no_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = get_provider_adapter("gemini", root_dir=root, live_mode=True)
            adapter_request = {
                "model": "gemini-3-flash-preview",
                "providerOptions": {},
                "session": {"resolvedMode": "fresh", "resumeRef": ""},
                "promptText": "hello",
                "summary": "hello",
            }

            cmd, _, _ = adapter._build_live_command_and_input(
                adapter_request=adapter_request,
                tmp_dir=root,
            )

            self.assertIn("--model", cmd)
            self.assertEqual(cmd[cmd.index("--model") + 1], "gemini-3-flash-preview")
            self.assertFalse((root / "gemini-thinking-settings.json").exists())
            self.assertEqual(
                adapter._build_live_env(adapter_request=adapter_request), {}
            )

    def test_gemini_live_falls_back_from_31_preview_to_3_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = get_provider_adapter("gemini", root_dir=root, live_mode=True)
            adapter_request = {
                "taskId": "task-gemini-fallback",
                "phase": "review",
                "step": "R0_standard_review",
                "attempt": 1,
                "run": 1,
                "modelRef": "gemini-3.1-pro-preview",
                "model": "gemini-3.1-pro-preview",
                "providerOptions": {"model": "gemini-3.1-pro-preview"},
                "timeouts": {"defaultMs": 600000},
                "session": {
                    "requestedMode": "fresh",
                    "resolvedMode": "fresh",
                    "resumeDecision": "not_requested",
                    "resumeRef": "",
                    "capabilityMetadata": {},
                },
                "promptText": "hello",
                "summary": "hello",
                "providerInvocation": {
                    "command": "gemini",
                    "modelOption": {
                        "flag": "--model",
                        "value": "gemini-3.1-pro-preview",
                    },
                },
            }
            calls: list[list[str]] = []

            def fake_run(
                cmd: list[str],
                *,
                input: bytes | None,
                capture_output: bool,
                timeout: int,
                cwd: str,
                env: dict[str, str],
            ) -> subprocess.CompletedProcess[bytes]:
                del input, capture_output, timeout, cwd, env
                calls.append(cmd)
                if len(calls) == 1:
                    return subprocess.CompletedProcess(
                        cmd,
                        1,
                        stdout=b"",
                        stderr=b"ModelNotFoundError: Requested entity was not found.",
                    )
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout=b'{"response":"hello","stats":{}}',
                    stderr=b"",
                )

            with patch(
                "collab.runtime.providers.base.subprocess.run",
                side_effect=fake_run,
            ):
                invocation = adapter.execute_live(adapter_request=adapter_request)

            self.assertEqual(invocation.result_payload["status"], "succeeded")
            self.assertEqual(
                calls[0][calls[0].index("--model") + 1],
                "gemini-3.1-pro-preview",
            )
            self.assertEqual(
                calls[1][calls[1].index("--model") + 1],
                "gemini-3-pro-preview",
            )
            self.assertEqual(
                invocation.result_payload["providerInvocation"]["modelOption"]["value"],
                "gemini-3-pro-preview",
            )
            self.assertEqual(
                invocation.result_payload["providerInvocation"]["fallbackFromModel"],
                "gemini-3.1-pro-preview",
            )
            self.assertTrue(
                any(
                    warning.get("code") == "MODEL_FALLBACK"
                    for warning in invocation.result_payload["parsedEnvelope"][
                        "warnings"
                    ]
                )
            )

    def _build_resolved_config(self, provider: str) -> dict[str, object]:
        facts_ref = (
            Path(__file__).resolve().parents[2]
            / "facts"
            / "verified-facts"
            / "imported-seed.json"
        )
        provider_options = {
            "codex": {"reasoningEffort": "medium"},
            "gemini": {"mode": "default"},
            "copilot": {},
        }[provider]
        model_ref = {
            "codex": "codex-primary",
            "gemini": "gemini-primary",
            "copilot": "copilot-primary",
        }[provider]
        return {
            "provider": {
                "provider": provider,
                "profile": f"{provider}-profile",
                "modelRef": model_ref,
                "model": model_ref,
                "options": provider_options,
                "supportedOptionKeys": ["model"],
                "timeoutDefaults": {"defaultMs": 600000},
                "retryDefaults": {"transient": 3},
            },
            "phaseOptions": {"budgetProfileRef": "budget-bootstrap"},
            "facts": {"verifiedFactRefs": [str(facts_ref)]},
        }

    def _build_request_payload(
        self, provider: str, *, workflow_intent: str
    ) -> dict[str, object]:
        allowed_modes = ["patch", "report_only"]
        if provider == "gemini":
            allowed_modes = ["report_only"]
        return {
            "workflow_intent": workflow_intent,
            "selectors": {"resume_from": "cursor-001"},
            "output": {
                "preferred_mode": allowed_modes[0],
                "allowed_modes": allowed_modes,
                "operations_required": provider == "codex",
            },
        }

    def _build_prompt_bundle(self) -> dict[str, object]:
        return {
            "targets": {"paths": ["src/example.txt"]},
            "summary": "stub adapter test",
            "operatorContext": {"summary": "unit test"},
        }


class TestMutationAuthority(unittest.TestCase):
    def test_gemini_provider_sandboxed_write_downgraded(self) -> None:
        self.assertEqual(
            resolve_mutation_authority(
                {"mutationAuthority": "provider_sandboxed_write"},
                provider="gemini",
            ),
            "runtime_apply_only",
        )

    def test_codex_provider_sandboxed_write_allowed(self) -> None:
        self.assertEqual(
            resolve_mutation_authority(
                {"mutationAuthority": "provider_sandboxed_write"},
                provider="codex",
            ),
            "provider_sandboxed_write",
        )

    def test_gemini_cannot_get_sandboxed_write(self) -> None:
        self.assertEqual(
            resolve_mutation_authority(
                {"mutationAuthority": "provider_sandboxed_write"},
                provider="gemini",
            ),
            "runtime_apply_only",
        )

    def test_codex_can_get_sandboxed_write(self) -> None:
        self.assertEqual(
            resolve_mutation_authority(
                {"mutationAuthority": "provider_sandboxed_write"},
                provider="codex",
            ),
            "provider_sandboxed_write",
        )

    def test_unknown_authority_falls_back(self) -> None:
        self.assertEqual(
            resolve_mutation_authority(
                {"mutationAuthority": "unexpected_value"},
                provider="codex",
            ),
            "runtime_apply_only",
        )

    def test_read_only_authority_preserved(self) -> None:
        self.assertEqual(
            resolve_mutation_authority(
                {"mutationAuthority": "read_only"},
                provider="gemini",
            ),
            "read_only",
        )

    def test_authority_allows_direct_write_true(self) -> None:
        self.assertTrue(authority_allows_direct_write("provider_sandboxed_write"))

    def test_authority_allows_direct_write_only_for_sandboxed(self) -> None:
        self.assertTrue(authority_allows_direct_write("provider_sandboxed_write"))
        self.assertFalse(authority_allows_direct_write("runtime_apply_only"))

    def test_authority_requires_apply_executor_true(self) -> None:
        self.assertTrue(authority_requires_apply_executor("runtime_apply_only"))

    def test_authority_requires_apply_executor_for_read_only(self) -> None:
        self.assertTrue(authority_requires_apply_executor("read_only"))


if __name__ == "__main__":
    unittest.main()
