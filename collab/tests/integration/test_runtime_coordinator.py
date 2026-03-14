from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collab.runtime.artifact_store import ArtifactStore
from collab.runtime.claude_code_skill import ClaudeCodeSkill
from collab.runtime.config_loader import resolve_runtime_config
from collab.runtime.prompt_assembly import assemble_prompt_bundle
from collab.runtime.runtime_coordinator import RuntimeCoordinator


class RuntimeCoordinatorIntegrationTest(unittest.TestCase):
    def test_processes_adapter_execution_end_to_end_and_applies_safe_change(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text(
                "# Implement runtime\n\nApply one safe change.\n", encoding="utf-8"
            )
            target = root / "src" / "hello.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="impl",
                source_kind="markdown",
                targets={"paths": ["src/hello.txt"], "summary": "single file"},
                operator_context={"summary": "coordinator success"},
            )

            coordinator = RuntimeCoordinator(root)
            result = coordinator.execute_phase(
                task_id=dispatch.task_id,
                request_path=dispatch.request_path,
                phase="impl",
                step="apply",
            )

            self.assertEqual(result.controller_status, "running")
            self.assertIsNotNone(result.apply_result)
            self.assertEqual(result.apply_result["result"], "applied")
            self.assertTrue(result.adapter_request_path.exists())
            self.assertTrue(result.adapter_result_path.exists())
            self.assertTrue(
                result.raw_output_path is not None and result.raw_output_path.exists()
            )
            self.assertTrue(result.response_path.exists())
            self.assertTrue(result.normalized_path.exists())
            self.assertTrue(result.validation_path.exists())
            self.assertTrue(result.execution_record_path.exists())
            self.assertTrue(result.shell_digest_path.exists())
            self.assertTrue(result.session_state_path.exists())
            self.assertTrue(result.manifest_path.exists())

            applied_content = target.read_text(encoding="utf-8")
            self.assertIn("before\n", applied_content)
            self.assertIn("stub:codex:impl:apply:codex-primary", applied_content)

            adapter_request = json.loads(
                result.adapter_request_path.read_text(encoding="utf-8")
            )
            self.assertEqual(adapter_request["payload"]["provider"], "codex")
            self.assertEqual(
                adapter_request["payload"]["providerOptions"]["reasoningEffort"],
                "medium",
            )
            self.assertEqual(
                adapter_request["payload"]["session"]["resolvedMode"], "fresh"
            )

            adapter_result = json.loads(
                result.adapter_result_path.read_text(encoding="utf-8")
            )
            session_ref = adapter_result["payload"]["session"]["sessionRef"]
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["payload"]["artifactRefs"]["adapterRequest"],
                result.adapter_request_path.as_posix(),
            )
            self.assertEqual(
                manifest["payload"]["sessionRefs"]["sessionRef"], session_ref
            )

            session_state = json.loads(
                result.session_state_path.read_text(encoding="utf-8")
            )
            self.assertEqual(session_state["sessionRef"], session_ref)
            self.assertEqual(session_state["provider"], "codex")

            known_information = json.loads(
                (
                    root
                    / "collab"
                    / "state"
                    / "tasks"
                    / dispatch.task_id
                    / "known-information.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                known_information["latest_validation_apply_summary"][
                    "apply_result_ref"
                ],
                result.apply_result_path.as_posix(),
            )

    def test_persists_stub_adapter_execution_without_applying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text(
                "# Review runtime\n\nHandle provider failure.\n", encoding="utf-8"
            )

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="review",
                source_kind="markdown",
                operator_context={"summary": "coordinator failure"},
            )

            coordinator = RuntimeCoordinator(root)
            result = coordinator.execute_phase(
                task_id=dispatch.task_id,
                request_path=dispatch.request_path,
                phase="review",
                step="analysis",
                auto_apply=False,
            )

            self.assertEqual(result.controller_status, "partial")
            self.assertIsNone(result.apply_result)
            self.assertTrue(result.adapter_request_path.exists())
            self.assertTrue(result.adapter_result_path.exists())
            self.assertTrue(result.response_path.exists())
            self.assertTrue(result.validation_path.exists())
            self.assertTrue(result.execution_record_path.exists())

            response_artifact = json.loads(
                result.response_path.read_text(encoding="utf-8")
            )
            self.assertEqual(response_artifact["payload"]["status"], "partial")
            validation_artifact = json.loads(
                result.validation_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                validation_artifact["payload"]["overall_outcome"],
                "failed_but_meaningful",
            )

    def test_step_specific_user_overrides_flow_into_adapter_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text(
                "# Implement runtime\n\nInspect the patch-first analysis step.\n",
                encoding="utf-8",
            )
            target = root / "src" / "hello.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="impl",
                source_kind="markdown",
                targets={"paths": ["src/hello.txt"], "summary": "single file"},
                operator_context={"summary": "step override propagation"},
            )
            request = json.loads(dispatch.request_path.read_text(encoding="utf-8"))
            resolution = resolve_runtime_config(
                root_dir=root,
                request=request,
                step_id="I0_analyze",
            )
            store = ArtifactStore(root)
            resolved_record = store.write_json_artifact(
                task_id=dispatch.task_id,
                family="resolved-config",
                artifact_type="resolved_config",
                payload=resolution.resolved_config,
                filename="resolved-config-impl-I0_analyze.json",
                phase="impl",
                step="I0_analyze",
            )
            routing_record = store.write_json_artifact(
                task_id=dispatch.task_id,
                family="routing",
                artifact_type="routing_result",
                payload=resolution.routing_result,
                filename="routing-result-impl-I0_analyze.json",
                phase="impl",
                step="I0_analyze",
            )
            prompt_bundle = assemble_prompt_bundle(
                request=request,
                resolved_config=resolution.resolved_config,
                routing_result=resolution.routing_result,
                summary_input_refs=[
                    str(dispatch.request_path),
                    str(resolved_record.path),
                    str(routing_record.path),
                ],
                step_id="I0_analyze",
            )
            prompt_record = store.write_json_artifact(
                task_id=dispatch.task_id,
                family="prompts",
                artifact_type="prompt_bundle",
                payload=prompt_bundle,
                filename="prompt-bundle-impl-I0_analyze.json",
                phase="impl",
                step="I0_analyze",
            )

            coordinator = RuntimeCoordinator(root)
            result = coordinator.execute_phase(
                task_id=dispatch.task_id,
                request_path=dispatch.request_path,
                phase="impl",
                step="I0_analyze",
                resolved_config_path=resolved_record.path,
                routing_result_path=routing_record.path,
                prompt_bundle_path=prompt_record.path,
                auto_apply=False,
            )

            adapter_request = json.loads(
                result.adapter_request_path.read_text(encoding="utf-8")
            )
            self.assertEqual(adapter_request["payload"]["provider"], "codex")
            self.assertEqual(
                adapter_request["payload"]["modelRef"], "gpt-5.1-codex-mini"
            )
            self.assertEqual(
                adapter_request["payload"]["providerOptions"]["reasoningEffort"],
                "low",
            )
            self.assertEqual(
                adapter_request["payload"]["providerOptions"]["model"],
                "gpt-5.1-codex-mini",
            )

    def test_provider_sandboxed_write_skips_apply_and_records_diff_capture(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text(
                "# Implement runtime\n\nAllow provider-sandboxed write.\n",
                encoding="utf-8",
            )
            target = root / "src" / "hello.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="impl",
                source_kind="markdown",
                targets={"paths": ["src/hello.txt"], "summary": "single file"},
                operator_context={"summary": "provider sandboxed write"},
            )
            request = json.loads(dispatch.request_path.read_text(encoding="utf-8"))
            resolution = resolve_runtime_config(
                root_dir=root,
                request=request,
                step_id="I0_analyze",
            )
            resolved_config = dict(resolution.resolved_config)
            resolved_config["step"] = {
                "mutationAuthority": "provider_sandboxed_write",
            }
            store = ArtifactStore(root)
            resolved_record = store.write_json_artifact(
                task_id=dispatch.task_id,
                family="resolved-config",
                artifact_type="resolved_config",
                payload=resolved_config,
                filename="resolved-config-impl-I0_analyze-direct.json",
                phase="impl",
                step="I0_analyze",
            )
            routing_record = store.write_json_artifact(
                task_id=dispatch.task_id,
                family="routing",
                artifact_type="routing_result",
                payload=resolution.routing_result,
                filename="routing-result-impl-I0_analyze-direct.json",
                phase="impl",
                step="I0_analyze",
            )
            prompt_bundle = assemble_prompt_bundle(
                request=request,
                resolved_config=resolved_config,
                routing_result=resolution.routing_result,
                summary_input_refs=[
                    str(dispatch.request_path),
                    str(resolved_record.path),
                    str(routing_record.path),
                ],
                step_id="I0_analyze",
            )
            prompt_record = store.write_json_artifact(
                task_id=dispatch.task_id,
                family="prompts",
                artifact_type="prompt_bundle",
                payload=prompt_bundle,
                filename="prompt-bundle-impl-I0_analyze-direct.json",
                phase="impl",
                step="I0_analyze",
            )

            coordinator = RuntimeCoordinator(root)
            result = coordinator.execute_phase(
                task_id=dispatch.task_id,
                request_path=dispatch.request_path,
                phase="impl",
                step="I0_analyze",
                resolved_config_path=resolved_record.path,
                routing_result_path=routing_record.path,
                prompt_bundle_path=prompt_record.path,
                auto_apply=True,
            )

            self.assertIsNone(result.apply_result)
            self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

            execution_record = json.loads(
                result.execution_record_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                execution_record["payload"]["effectiveMutationAuthority"],
                "provider_sandboxed_write",
            )

            diff_capture_paths = sorted(
                (
                    root
                    / "collab"
                    / "artifacts"
                    / "tasks"
                    / dispatch.task_id
                    / "diff-captures"
                ).glob("diff-capture-impl-I0_analyze-*.json")
            )
            self.assertEqual(len(diff_capture_paths), 1)
            diff_capture = json.loads(diff_capture_paths[0].read_text(encoding="utf-8"))
            self.assertEqual(diff_capture["payload"]["method"], "unavailable")


if __name__ == "__main__":
    unittest.main()
