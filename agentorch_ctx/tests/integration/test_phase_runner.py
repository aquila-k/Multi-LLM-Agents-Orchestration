from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentorch_ctx.runtime.claude_code_skill import ClaudeCodeSkill
from agentorch_ctx.runtime.config_loader import resolve_runtime_config
from agentorch_ctx.runtime.pathing import task_artifacts_dir, task_state_dir
from agentorch_ctx.runtime.phase_runner import PhaseRunner
from agentorch_ctx.runtime.runtime_coordinator import CoordinationResult


class PhaseRunnerIntegrationTest(unittest.TestCase):
    def _mock_coordination_result(
        self,
        *,
        root: Path,
        task_id: str,
        phase: str,
        step: str,
        content: str,
    ) -> CoordinationResult:
        task_root = task_artifacts_dir(root, task_id)
        state_root = task_state_dir(root, task_id)
        adapter_request_path = (
            task_root / "adapter" / f"adapter-request-{phase}-{step}-stub.json"
        )
        adapter_result_path = (
            task_root / "adapter" / f"adapter-result-{phase}-{step}-stub.json"
        )
        raw_output_path = task_root / "adapter" / f"raw-output-{phase}-{step}-stub.txt"
        response_path = task_root / "responses" / f"response-{phase}-{step}-stub.json"
        normalized_path = (
            task_root / "normalized" / f"normalized-{phase}-{step}-stub.json"
        )
        validation_path = (
            task_root / "validation" / f"validation-{phase}-{step}-stub.json"
        )
        execution_record_path = (
            task_root
            / "execution-records"
            / f"execution-record-{phase}-{step}-stub.json"
        )
        shell_digest_path = (
            task_root / "shell-digests" / f"shell-digest-{phase}-{step}-stub.json"
        )
        manifest_path = task_root / "manifests" / "manifest.json"
        session_state_path = state_root / "session-state.json"
        apply_result_path = (
            task_root / "apply-results" / f"apply-result-{phase}-{step}.json"
        )

        for path in (
            adapter_request_path,
            adapter_result_path,
            raw_output_path,
            response_path,
            normalized_path,
            validation_path,
            execution_record_path,
            shell_digest_path,
            session_state_path,
            apply_result_path,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)

        adapter_request_path.write_text(
            json.dumps({"payload": {"phase": phase, "step": step}}),
            encoding="utf-8",
        )
        adapter_result_path.write_text(
            json.dumps({"payload": {"status": "succeeded"}}),
            encoding="utf-8",
        )
        raw_output_path.write_text(content, encoding="utf-8")
        response_path.write_text(
            json.dumps(
                {
                    "payload": {
                        "summary": "mocked plan output",
                        "payload": {"report": content},
                    }
                }
            ),
            encoding="utf-8",
        )
        normalized_path.write_text(
            json.dumps({"payload": {"content": content}}),
            encoding="utf-8",
        )
        validation_path.write_text(
            json.dumps({"payload": {"overall_outcome": "passed"}}),
            encoding="utf-8",
        )
        execution_record_path.write_text(
            json.dumps({"payload": {"status": "succeeded"}}),
            encoding="utf-8",
        )
        shell_digest_path.write_text(
            json.dumps({"payload": {"summary": "mock shell digest"}}),
            encoding="utf-8",
        )
        session_state_path.write_text(
            json.dumps({"provider": "codex", "sessionRef": "mock-session"}),
            encoding="utf-8",
        )
        apply_result_path.write_text(
            json.dumps({"payload": {"result": "not_applied"}}),
            encoding="utf-8",
        )

        controller_path = state_root / "controller-state.json"
        controller = json.loads(controller_path.read_text(encoding="utf-8"))
        strategy = controller.get("active_strategy", "")
        controller.update(
            {
                "active_phase": phase,
                "active_step": step,
                "active_strategy": strategy,
                "current_status": "partial",
                "blocked_reason": "",
                "latest_shell_digest_refs": [str(shell_digest_path)],
            }
        )
        controller_path.write_text(
            json.dumps(controller, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        approval_state_path = state_root / "approval-state.json"
        if approval_state_path.exists():
            approval_state = json.loads(approval_state_path.read_text(encoding="utf-8"))
        else:
            approval_state = {"status": "not_required", "marker": ""}
            approval_state_path.write_text(
                json.dumps(approval_state, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

        resume_cursor_payload = {
            "schema_version": "1.0.0",
            "phase": phase,
            "strategy": strategy,
            "step": step,
            "attempt": 1,
            "run": 1,
            "resume_from": "",
            "approval_continuation": approval_state.get("marker", ""),
            "artifact_ref": str(validation_path),
            "updated_at": controller.get("updated_at", ""),
        }
        (state_root / "resume-cursor.json").write_text(
            json.dumps(resume_cursor_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        known_information_path = state_root / "known-information.json"
        known_information = json.loads(
            known_information_path.read_text(encoding="utf-8")
        )
        known_information["latest_phase_summary"] = {
            "phase": phase,
            "summary": "mocked phase summary",
            "artifact_ref": str(response_path),
        }
        known_information["latest_validation_apply_summary"] = {
            "summary": "validation=passed apply=not_applied",
            "validation_ref": str(validation_path),
            "apply_result_ref": "",
        }
        known_information_path.write_text(
            json.dumps(known_information, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        manifest_envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_payload = manifest_envelope.get("payload", manifest_envelope)
        manifest_payload.update(
            {
                "activePhase": phase,
                "activeStep": step,
                "activeStrategyId": strategy,
                "controllerStatus": "partial",
                "artifactRefs": {
                    "request": str(adapter_request_path),
                    "adapterRequest": str(adapter_request_path),
                    "adapterResult": str(adapter_result_path),
                    "rawOutput": str(raw_output_path),
                    "response": str(response_path),
                    "normalized": str(normalized_path),
                    "validation": str(validation_path),
                    "executionRecord": str(execution_record_path),
                    "shellDigest": str(shell_digest_path),
                    "applyResult": "",
                    "sessionState": str(session_state_path),
                },
                "lastSuccessfulArtifactRefs": [str(validation_path)],
                "latestShellDigestRefs": [str(shell_digest_path)],
                "blockerRefs": [],
                "sessionRefs": {"provider": "codex", "sessionRef": "mock-session"},
                "approvalState": {
                    "status": approval_state.get("status", ""),
                    "marker": approval_state.get("marker", ""),
                },
                "resumeCursor": {
                    "phase": phase,
                    "strategy": strategy,
                    "step": step,
                    "attempt": 1,
                    "run": 1,
                    "resumeFrom": "",
                    "approvalContinuation": approval_state.get("marker", ""),
                    "artifactRef": str(validation_path),
                },
                "latestPhaseSummary": {
                    "phase": phase,
                    "summary": "mocked phase summary",
                    "artifactRef": str(response_path),
                },
                "latestValidationApplySummary": {
                    "summary": "validation=passed apply=not_applied",
                    "validationRef": str(validation_path),
                    "applyResultRef": "",
                },
            }
        )
        manifest_path.write_text(
            json.dumps({"payload": manifest_payload}, indent=2, ensure_ascii=True)
            + "\n",
            encoding="utf-8",
        )

        return CoordinationResult(
            adapter_request_path=adapter_request_path,
            adapter_result_path=adapter_result_path,
            raw_output_path=raw_output_path,
            response_path=response_path,
            normalized_path=normalized_path,
            validation_path=validation_path,
            execution_record_path=execution_record_path,
            shell_digest_path=shell_digest_path,
            manifest_path=manifest_path,
            session_state_path=session_state_path,
            apply_result_path=None,
            apply_result=None,
            controller_status="partial",
        )

    def _run_mocked_plan_phase(
        self,
        *,
        root: Path,
        content: str,
    ) -> tuple[str, Path]:
        source = root / "plan.md"
        source.write_text("# Plan runtime\n", encoding="utf-8")
        dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
            source_path=source,
            workflow_intent="plan",
            source_kind="markdown",
            selectors={"step": "FINAL_plan"},
            operator_context={"summary": "mocked plan artifacts"},
        )

        runner = PhaseRunner(root)

        def fake_execute_phase(**kwargs: object) -> CoordinationResult:
            return self._mock_coordination_result(
                root=root,
                task_id=str(kwargs["task_id"]),
                phase=str(kwargs["phase"]),
                step=str(kwargs["step"]),
                content=content,
            )

        runner.coordinator.execute_phase = fake_execute_phase  # type: ignore[method-assign]
        result = runner.run(request_path=dispatch.request_path)
        self.assertEqual(result.executed_phases, ["plan"])
        return dispatch.task_id, result.phase_run_path

    def _write_findings_gate_artifact(
        self,
        *,
        root: Path,
        task_id: str,
        phase: str,
        step: str,
        attempt: int,
        run: int,
        can_complete: bool,
        blocking_found: bool,
    ) -> None:
        gate_path = (
            task_artifacts_dir(root, task_id)
            / "findings"
            / f"findings-gate-{phase}-{step}-{attempt}-{run}.json"
        )
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path.write_text(
            json.dumps(
                {
                    "payload": {
                        "can_complete": can_complete,
                        "blocking_found": blocking_found,
                        "findings_summary": {
                            "total": 1 if blocking_found else 0,
                            "by_severity": {
                                "Critical": 1 if blocking_found else 0,
                                "High": 0,
                                "Mid": 0,
                                "Low": 0,
                                "Nitpick": 0,
                            },
                            "blocking_count": 1 if blocking_found else 0,
                        },
                        "findings": [],
                        "fixable_operations_count": 0,
                    }
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def _write_plan_artifact(self, *, root: Path, task_id: str) -> Path:
        plan_path = (
            task_artifacts_dir(root, task_id) / "plans" / "plan-plan-FINAL_plan.json"
        )
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(
                {
                    "summary": "seed plan artifact for impl precondition",
                    "implementationSteps": [],
                    "checklist": [],
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return plan_path

    def test_materialize_phase_inputs_persists_step_mutation_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "harden.md"
            source.write_text("# Harden runtime\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="harden",
                source_kind="markdown",
                operator_context={"summary": "step mutation authority"},
            )
            request = json.loads(dispatch.request_path.read_text(encoding="utf-8"))
            resolution = resolve_runtime_config(
                root_dir=root,
                request=request,
                step_id="H1_fix_recommendations",
            )

            runner = PhaseRunner(root)
            artifact_refs = runner._materialize_phase_inputs(
                task_id=dispatch.task_id,
                request=request,
                resolved_config=resolution.resolved_config,
                routing_result=resolution.routing_result,
                phase="harden",
                step="H1_fix_recommendations",
                step_def={
                    "id": "H1_fix_recommendations",
                    "mutationAuthority": "provider_sandboxed_write",
                },
            )

            resolved_config_artifact = json.loads(
                Path(artifact_refs["resolvedConfig"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                resolved_config_artifact["payload"]["step"]["mutationAuthority"],
                "provider_sandboxed_write",
            )

    def test_review_with_harden_runs_as_composed_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "review.md"
            source.write_text("# Review runtime\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="review",
                source_kind="markdown",
                phase_options={"with_harden": True},
                operator_context={"summary": "phase runner composed flow"},
            )

            result = PhaseRunner(root).run(request_path=dispatch.request_path)

            self.assertEqual(result.executed_phases, ["review", "harden"])
            self.assertEqual(result.controller_status, "partial")
            self.assertIsNone(result.pause_confirm_path)
            self.assertTrue(result.phase_run_path.exists())

            phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
            self.assertEqual(phase_run["payload"]["compositionMode"], "composed")
            self.assertTrue(phase_run["payload"]["withHarden"])
            self.assertEqual(len(phase_run["payload"]["phaseRecords"]), 2)
            self.assertEqual(
                phase_run["payload"]["phaseRecords"][1]["requestRef"].endswith(
                    "request-harden.json"
                ),
                True,
            )
            self.assertTrue(phase_run["payload"]["phaseRecords"][0]["consistencyRef"])
            self.assertTrue(phase_run["payload"]["phaseRecords"][1]["consistencyRef"])
            self.assertTrue(
                phase_run["payload"]["phaseRecords"][1]["strategySwitchRef"]
            )

            harden_config = (
                task_artifacts_dir(root, dispatch.task_id)
                / "resolved-config"
                / "resolved-config-harden.json"
            )
            self.assertTrue(harden_config.exists())
            harden_request = (
                task_artifacts_dir(root, dispatch.task_id)
                / "requests"
                / "request-harden.json"
            )
            self.assertTrue(harden_request.exists())

    def test_invalid_strategy_override_blocks_with_reason_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "plan.md"
            source.write_text("# Plan runtime\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                selectors={"strategy": "COLLAB_IMPL_PATCH_FIRST"},
                operator_context={"summary": "invalid strategy override"},
            )

            result = PhaseRunner(root).run(request_path=dispatch.request_path)

            self.assertEqual(result.executed_phases, [])
            self.assertEqual(result.controller_status, "blocked")
            self.assertIsNotNone(result.pause_confirm_path)
            self.assertIsNotNone(result.option_decision_path)
            self.assertTrue(result.pause_confirm_path.exists())
            self.assertTrue(result.option_decision_path.exists())

            decision = json.loads(
                result.option_decision_path.read_text(encoding="utf-8")
            )
            self.assertEqual(decision["payload"]["outcome"], "blocked")
            self.assertEqual(
                decision["payload"]["reasonCode"], "strategy_override_unavailable"
            )

            controller = json.loads(
                dispatch.controller_state_path.read_text(encoding="utf-8")
            )
            self.assertEqual(controller["blocked_reason"], "strategy_override_conflict")
            phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
            self.assertTrue(phase_run["payload"]["consistencyRef"])

    def test_strategy_requiring_budget_confirmation_blocks_at_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "plan.md"
            source.write_text("# Plan runtime\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                selectors={"strategy": "COLLAB_PLAN_THOROUGH"},
                operator_context={"summary": "budget preflight block"},
            )

            result = PhaseRunner(root).run(request_path=dispatch.request_path)

            self.assertEqual(result.executed_phases, ["plan"])
            self.assertEqual(result.controller_status, "blocked")
            self.assertIsNotNone(result.pause_confirm_path)
            self.assertTrue(result.pause_confirm_path.exists())

            pause_confirm = json.loads(
                result.pause_confirm_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                pause_confirm["payload"]["stopReason"], "strategy_budget_preflight"
            )
            self.assertEqual(
                pause_confirm["payload"]["resumeOptions"][0]["step"], "preflight"
            )

            phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
            self.assertEqual(
                phase_run["payload"]["blockedReason"], "strategy_budget_preflight"
            )
            self.assertEqual(
                phase_run["payload"]["phaseRecords"][0]["stepRecords"][0]["step"],
                "preflight",
            )

    def test_blocked_impl_execution_materializes_pause_confirm_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "impl.md"
            source.write_text("# Implement runtime\n", encoding="utf-8")
            target = root / "src" / "hello.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="impl",
                source_kind="markdown",
                targets={"paths": ["src/hello.txt"]},
                constraints={"disallowed_paths": ["src/hello.txt"]},
                operator_context={"summary": "blocked impl"},
            )
            self._write_plan_artifact(root=root, task_id=dispatch.task_id)

            result = PhaseRunner(root).run(request_path=dispatch.request_path)

            self.assertEqual(result.executed_phases, ["impl"])
            self.assertEqual(result.controller_status, "blocked")
            self.assertIsNotNone(result.pause_confirm_path)
            self.assertTrue(result.pause_confirm_path.exists())

            pause_confirm = json.loads(
                result.pause_confirm_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                pause_confirm["payload"]["stopReason"], "blocked_for_scope"
            )

            phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
            self.assertEqual(phase_run["payload"]["blockedReason"], "blocked_for_scope")
            self.assertTrue(phase_run["payload"]["consistencyRefs"][0])

    def test_impl_step_contract_blocks_when_plan_artifact_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "impl.md"
            source.write_text("# Implement runtime\n", encoding="utf-8")
            target = root / "src" / "hello.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="impl",
                source_kind="markdown",
                selectors={"strategy": "COLLAB_IMPL_PATCH_FIRST"},
                targets={"paths": ["src/hello.txt"]},
                operator_context={"summary": "contract missing plan"},
            )

            runner = PhaseRunner(root)
            execute_calls: list[str] = []

            def fake_execute_phase(**kwargs: object) -> CoordinationResult:
                execute_calls.append(str(kwargs["step"]))
                return self._mock_coordination_result(
                    root=root,
                    task_id=str(kwargs["task_id"]),
                    phase=str(kwargs["phase"]),
                    step=str(kwargs["step"]),
                    content="should not execute",
                )

            runner.coordinator.execute_phase = fake_execute_phase  # type: ignore[method-assign]
            result = runner.run(request_path=dispatch.request_path)

            self.assertEqual(result.executed_phases, ["impl"])
            self.assertEqual(result.controller_status, "blocked")
            self.assertIsNotNone(result.pause_confirm_path)
            self.assertTrue(result.pause_confirm_path.exists())
            self.assertEqual(execute_calls, [])

            pause_confirm = json.loads(
                result.pause_confirm_path.read_text(encoding="utf-8")
            )
            self.assertTrue(
                pause_confirm["payload"]["stopReason"].startswith(
                    "step_input_contract_failed:missing_required_artifacts"
                )
            )
            self.assertIn("plans/", pause_confirm["payload"]["stopReason"])

            phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
            self.assertEqual(
                phase_run["payload"]["phaseRecords"][0]["stepRecords"][0]["step"],
                "I0_analyze",
            )

    def test_impl_step_contract_passes_when_plan_artifact_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "impl.md"
            source.write_text("# Implement runtime\n", encoding="utf-8")
            target = root / "src" / "hello.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="impl",
                source_kind="markdown",
                selectors={"strategy": "COLLAB_IMPL_PATCH_FIRST"},
                targets={"paths": ["src/hello.txt"]},
                operator_context={"summary": "contract has plan"},
            )
            self._write_plan_artifact(root=root, task_id=dispatch.task_id)

            runner = PhaseRunner(root)
            execute_calls: list[str] = []

            def fake_execute_phase(**kwargs: object) -> CoordinationResult:
                execute_calls.append(str(kwargs["step"]))
                return self._mock_coordination_result(
                    root=root,
                    task_id=str(kwargs["task_id"]),
                    phase=str(kwargs["phase"]),
                    step=str(kwargs["step"]),
                    content="executed with contract satisfied",
                )

            runner.coordinator.execute_phase = fake_execute_phase  # type: ignore[method-assign]
            result = runner.run(request_path=dispatch.request_path)

            self.assertEqual(result.executed_phases, ["impl"])
            self.assertNotEqual(result.controller_status, "blocked")
            self.assertIsNone(result.pause_confirm_path)
            self.assertTrue(execute_calls)

    def test_review_blocking_findings_stops_with_pause_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "review.md"
            source.write_text("# Review runtime\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="review",
                source_kind="markdown",
                operator_context={"summary": "review blocking findings gate"},
            )
            runner = PhaseRunner(root)
            auto_apply_values: list[bool] = []

            def fake_execute_phase(**kwargs: object) -> CoordinationResult:
                auto_apply_values.append(bool(kwargs.get("auto_apply")))
                self._write_findings_gate_artifact(
                    root=root,
                    task_id=str(kwargs["task_id"]),
                    phase=str(kwargs["phase"]),
                    step=str(kwargs["step"]),
                    attempt=int(kwargs["attempt"]),
                    run=int(kwargs["run"]),
                    can_complete=False,
                    blocking_found=True,
                )
                return self._mock_coordination_result(
                    root=root,
                    task_id=str(kwargs["task_id"]),
                    phase=str(kwargs["phase"]),
                    step=str(kwargs["step"]),
                    content="review output with blocking findings",
                )

            runner.coordinator.execute_phase = fake_execute_phase  # type: ignore[method-assign]
            result = runner.run(request_path=dispatch.request_path)

            self.assertEqual(result.executed_phases, ["review"])
            self.assertEqual(result.controller_status, "blocked")
            self.assertIsNotNone(result.pause_confirm_path)
            self.assertTrue(result.pause_confirm_path.exists())
            self.assertTrue(auto_apply_values)
            self.assertTrue(all(auto_apply_values))

            pause_confirm = json.loads(
                result.pause_confirm_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                pause_confirm["payload"]["stopReason"], "review_blocking_findings"
            )

            phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
            self.assertEqual(
                phase_run["payload"]["blockedReason"], "review_blocking_findings"
            )
            self.assertEqual(
                len(phase_run["payload"]["phaseRecords"][0]["stepRecords"]), 1
            )

    def test_review_without_blocking_findings_completes_normally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "review.md"
            source.write_text("# Review runtime\n", encoding="utf-8")

            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="review",
                source_kind="markdown",
                operator_context={"summary": "review non-blocking findings gate"},
            )
            runner = PhaseRunner(root)
            auto_apply_values: list[bool] = []

            def fake_execute_phase(**kwargs: object) -> CoordinationResult:
                auto_apply_values.append(bool(kwargs.get("auto_apply")))
                self._write_findings_gate_artifact(
                    root=root,
                    task_id=str(kwargs["task_id"]),
                    phase=str(kwargs["phase"]),
                    step=str(kwargs["step"]),
                    attempt=int(kwargs["attempt"]),
                    run=int(kwargs["run"]),
                    can_complete=True,
                    blocking_found=False,
                )
                return self._mock_coordination_result(
                    root=root,
                    task_id=str(kwargs["task_id"]),
                    phase=str(kwargs["phase"]),
                    step=str(kwargs["step"]),
                    content="review output with no blocking findings",
                )

            runner.coordinator.execute_phase = fake_execute_phase  # type: ignore[method-assign]
            result = runner.run(request_path=dispatch.request_path)

            self.assertEqual(result.executed_phases, ["review"])
            self.assertNotEqual(result.controller_status, "blocked")
            self.assertIsNone(result.pause_confirm_path)
            self.assertTrue(auto_apply_values)
            self.assertTrue(all(auto_apply_values))

            phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
            self.assertEqual(phase_run["payload"]["blockedReason"], "")

    def test_plan_auto_advance_executes_follow_on_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "plan.md"
            source.write_text("# Plan runtime\n", encoding="utf-8")
            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                selectors={"step": "FINAL_plan"},
                phase_options={"auto_advance": True},
                operator_context={"summary": "auto advance enabled"},
            )
            runner = PhaseRunner(root)
            executed_phases: list[str] = []

            def fake_execute_phase(**kwargs: object) -> CoordinationResult:
                executed_phases.append(str(kwargs["phase"]))
                phase = str(kwargs["phase"])
                return self._mock_coordination_result(
                    root=root,
                    task_id=str(kwargs["task_id"]),
                    phase=phase,
                    step=str(kwargs["step"]),
                    content=(
                        """
```json
{
  "summary": "Auto advance plan",
  "implementationSteps": [{"id": "S01", "description": "Plan next phase"}],
  "targetPaths": ["agentorch_ctx/runtime/phase_runner.py"],
  "checklist": ["Verify auto advance"]
}
```
"""
                        if phase == "plan"
                        else "auto advance content"
                    ),
                )

            runner.coordinator.execute_phase = fake_execute_phase  # type: ignore[method-assign]
            result = runner.run(request_path=dispatch.request_path)

            self.assertGreaterEqual(len(executed_phases), 2)
            self.assertEqual(executed_phases[0], "plan")
            self.assertEqual(executed_phases[1], "impl")
            self.assertIn("impl", result.executed_phases)
            phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
            self.assertTrue(phase_run["payload"]["autoAdvance"])

    def test_plan_default_auto_advance_stops_after_requested_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "plan.md"
            source.write_text("# Plan runtime\n", encoding="utf-8")
            dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                selectors={"step": "FINAL_plan"},
                operator_context={"summary": "auto advance disabled"},
            )
            runner = PhaseRunner(root)
            executed_phases: list[str] = []

            def fake_execute_phase(**kwargs: object) -> CoordinationResult:
                executed_phases.append(str(kwargs["phase"]))
                phase = str(kwargs["phase"])
                return self._mock_coordination_result(
                    root=root,
                    task_id=str(kwargs["task_id"]),
                    phase=phase,
                    step=str(kwargs["step"]),
                    content=(
                        """
```json
{
  "summary": "Single phase plan",
  "implementationSteps": [{"id": "S01", "description": "Finish plan"}],
  "targetPaths": ["agentorch_ctx/runtime/phase_runner.py"],
  "checklist": ["Stay on requested phase"]
}
```
"""
                        if phase == "plan"
                        else "no auto advance content"
                    ),
                )

            runner.coordinator.execute_phase = fake_execute_phase  # type: ignore[method-assign]
            result = runner.run(request_path=dispatch.request_path)

            self.assertEqual(executed_phases, ["plan"])
            self.assertEqual(result.executed_phases, ["plan"])
            phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
            self.assertFalse(phase_run["payload"]["autoAdvance"])

    def test_plan_run_creates_plan_and_checklist_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = """
Here is the final plan.
```json
{
  "summary": "Implement canonical plan artifact flow",
  "implementationSteps": [
    {
      "id": "S01",
      "description": "Add runtime extractor",
      "targetFiles": ["agentorch_ctx/runtime/plan_artifacts.py"]
    }
  ],
  "targetPaths": ["agentorch_ctx/runtime/plan_artifacts.py"],
  "checklist": [
    {
      "id": "C001",
      "description": "Emit plan artifacts after final step",
      "category": "impl",
      "status": "pending",
      "targetFiles": ["agentorch_ctx/runtime/phase_runner.py"]
    }
  ]
}
```
"""
            task_id, phase_run_path = self._run_mocked_plan_phase(
                root=root, content=content
            )
            task_root = task_artifacts_dir(root, task_id)
            plan_path = task_root / "plans" / "plan-plan-FINAL_plan.json"
            checklist_path = task_root / "checklists" / "checklist-plan-FINAL_plan.json"
            self.assertTrue(plan_path.exists())
            self.assertTrue(checklist_path.exists())

            manifest = json.loads(
                (task_root / "manifests" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["payload"]["planArtifactRefs"]["planRef"])
            self.assertTrue(manifest["payload"]["planArtifactRefs"]["checklistRef"])

            phase_run = json.loads(phase_run_path.read_text(encoding="utf-8"))
            phase_record = phase_run["payload"]["phaseRecords"][0]
            self.assertTrue(phase_record["planRef"])
            self.assertTrue(phase_record["checklistRef"])

    def test_plan_run_blocks_when_plan_artifacts_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = """
```json
{
  "summary": "Incomplete plan output",
  "implementationSteps": [{"id": "S01", "description": "Do one thing"}],
  "targetPaths": ["agentorch_ctx/runtime/phase_runner.py"],
  "checklist": []
}
```
"""
            task_id, phase_run_path = self._run_mocked_plan_phase(
                root=root, content=content
            )
            task_root = task_artifacts_dir(root, task_id)

            self.assertFalse(
                (task_root / "plans" / "plan-plan-FINAL_plan.json").exists()
            )
            self.assertFalse(
                (task_root / "checklists" / "checklist-plan-FINAL_plan.json").exists()
            )

            controller = json.loads(
                (task_state_dir(root, task_id) / "controller-state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(controller["current_status"], "blocked")
            self.assertEqual(controller["blocked_reason"], "plan_artifact_incomplete")

            pause_confirm = (
                task_root / "pause-confirm" / "pause-confirm-plan-FINAL_plan.json"
            )
            self.assertTrue(pause_confirm.exists())

            phase_run = json.loads(phase_run_path.read_text(encoding="utf-8"))
            self.assertEqual(
                phase_run["payload"]["blockedReason"], "plan_artifact_incomplete"
            )

    def test_plan_run_emits_final_report_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = """
```json
{
  "summary": "Plan output for final report",
  "implementationSteps": [{"id": "S01", "description": "Do one thing"}],
  "targetPaths": ["agentorch_ctx/runtime/phase_runner.py"],
  "checklist": ["emit final report"]
}
```
"""
            task_id, _ = self._run_mocked_plan_phase(root=root, content=content)
            final_report_path = (
                task_artifacts_dir(root, task_id)
                / "final-reports"
                / "final-report-plan.json"
            )
            self.assertTrue(final_report_path.exists())
            final_report = json.loads(final_report_path.read_text(encoding="utf-8"))
            payload = final_report.get("payload", final_report)
            self.assertIn("whatWasDone", payload)
            self.assertIn("FINAL_plan", payload["whatWasDone"])

    def test_deferred_items_emitted_only_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content_with_deferred = """
```json
{
  "summary": "Plan with deferred work",
  "implementationSteps": [{"id": "S01", "description": "Implement now"}],
  "targetPaths": ["agentorch_ctx/runtime/phase_runner.py"],
  "checklist": ["Ship plan artifacts"],
  "deferredItems": [
    {
      "id": "D001",
      "description": "Handle downstream schema migration",
      "reason": "out of scope for this task",
      "expectedResolutionPhase": "harden"
    }
  ]
}
```
"""
            task_id, _ = self._run_mocked_plan_phase(
                root=root, content=content_with_deferred
            )
            task_root = task_artifacts_dir(root, task_id)
            deferred_path = (
                task_root / "deferred-items" / "deferred-plan-FINAL_plan.json"
            )
            self.assertTrue(deferred_path.exists())

            manifest = json.loads(
                (task_root / "manifests" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["payload"]["planArtifactRefs"]["deferredItemsRef"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content_without_deferred = """
```json
{
  "summary": "Plan without deferred work",
  "implementationSteps": [{"id": "S01", "description": "Implement now"}],
  "targetPaths": ["agentorch_ctx/runtime/phase_runner.py"],
  "checklist": ["Ship plan artifacts"]
}
```
"""
            task_id, _ = self._run_mocked_plan_phase(
                root=root, content=content_without_deferred
            )
            task_root = task_artifacts_dir(root, task_id)
            deferred_dir = task_root / "deferred-items"
            self.assertFalse(deferred_dir.exists())

            manifest = json.loads(
                (task_root / "manifests" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["payload"]["planArtifactRefs"]["deferredItemsRef"], ""
            )


if __name__ == "__main__":
    unittest.main()
