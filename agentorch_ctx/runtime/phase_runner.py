from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.artifact_consistency import ArtifactConsistencyChecker
from agentorch_ctx.runtime.artifact_store import ArtifactStore
from agentorch_ctx.runtime.budget_gate import BudgetGate
from agentorch_ctx.runtime.config_loader import resolve_runtime_config
from agentorch_ctx.runtime.final_report import build_final_report
from agentorch_ctx.runtime.loop_state import build_loop_state_artifact
from agentorch_ctx.runtime.manifest_store import build_runtime_pause_confirm
from agentorch_ctx.runtime.parallel_executor import (
    execute_steps_parallel,
    is_consolidation_step,
    is_parallel_step,
    merge_parallel_results,
)
from agentorch_ctx.runtime.pathing import task_artifacts_dir, task_state_dir
from agentorch_ctx.runtime.plan_artifacts import (
    extract_plan_artifacts,
    validate_plan_artifacts,
)
from agentorch_ctx.runtime.prompt_assembly import assemble_prompt_bundle
from agentorch_ctx.runtime.providers import ProviderNotFoundError
from agentorch_ctx.runtime.renderers.markdown import render_markdown_document
from agentorch_ctx.runtime.review_gate import (
    ReviewGateResult,
    evaluate_review_gate,
    should_continue_loop,
)
from agentorch_ctx.runtime.runtime_coordinator import RuntimeCoordinator
from agentorch_ctx.runtime.step_contract import (
    check_input_contract,
    check_output_contract,
    inject_artifact_refs,
)
from agentorch_ctx.runtime.stop_categories import (
    ARTIFACT_CONSISTENCY_FAILURE,
    AUTO_ADVANCE_STOP_CODES,
    BUDGET_STOP,
    LOOP_CAP_REACHED,
    MISSING_TOOL_OR_AUTH,
    PLAN_ARTIFACT_INCOMPLETE,
    STEP_INPUT_CONTRACT_FAILED,
    STEP_OUTPUT_CONTRACT_FAILED,
)
from agentorch_ctx.runtime.task_runner import TaskRunner

_PRIOR_PHASE_SNIPPET_LIMIT = 2_000
_PRIOR_STEP_SNIPPET_LIMIT = 1_500
logger = logging.getLogger(__name__)


def _load_normalized_response(normalized_ref: str) -> dict[str, Any]:
    if not normalized_ref:
        return {}
    try:
        path = Path(normalized_ref)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _extract_questions(findings: list) -> list[str]:
    results: list[str] = []
    for item in findings or []:
        if isinstance(item, str) and "?" in item:
            results.append(item)
            if len(results) >= 3:
                break
    return results


def _extract_files(targets: dict) -> list[str]:
    if not isinstance(targets, dict):
        return []
    paths: list[str] = []
    raw_paths = targets.get("paths") or []
    if isinstance(raw_paths, list):
        paths.extend(str(p).strip() for p in raw_paths if str(p).strip())
    single_path = targets.get("path") or ""
    if isinstance(single_path, str) and single_path.strip():
        paths.append(single_path.strip())
    globs = targets.get("globs") or []
    if isinstance(globs, list):
        paths.extend(str(g).strip() for g in globs if str(g).strip())
    return list(dict.fromkeys(paths))


def _clip(text: str, max_chars: int) -> str:
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " [TRUNCATED]"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_lesson(normalized_response: dict[str, Any]) -> str:
    normalized_response = normalized_response or {}
    summary = normalized_response.get("summary") or ""
    if not isinstance(summary, str):
        summary = ""
    return summary[:200].strip()


def _extract_task_snapshot(
    request: dict[str, Any],
    phase: str,
    normalized_response: dict[str, Any],
) -> dict[str, Any]:
    normalized_response = normalized_response or {}
    return {
        "task_goal": request.get("summary", ""),
        "current_plan": _clip(
            normalized_response.get("summary", "") if phase == "plan" else "",
            2000,
        ),
        "progress": f"Phase '{phase}' completed at {_now_iso()}",
        "open_questions": _extract_questions(normalized_response.get("findings", [])),
        "blockers": (normalized_response.get("risks") or [])[:3],
        "relevant_files": _extract_files(request.get("targets", {})),
        "assumptions": [],
        "next_actions": (normalized_response.get("next_steps") or [])[:5],
    }


def _write_back_context(
    *,
    root_dir: Path,
    task_id: str,
    phase: str,
    request: dict[str, Any],
    normalized_response: dict[str, Any],
    expected_revision: int,
) -> None:
    from agentorch_ctx.runtime.context_bridge import (
        log_decision,
        log_episode,
        save_task_snapshot,
    )

    normalized_response = normalized_response or {}
    snapshot_payload = _extract_task_snapshot(request, phase, normalized_response)

    try:
        save_task_snapshot(
            root_dir=root_dir,
            task_id=task_id,
            payload=snapshot_payload,
            expected_revision=expected_revision,
            change_reason=f"phase_{phase}_completed",
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "context write-back: save_task_snapshot failed; skipping",
            extra={"task_id": task_id, "phase": phase},
        )

    lesson = _extract_lesson(normalized_response)
    episode_payload = {
        "observation": lesson,
        "phase": phase,
        "task_id": task_id,
    }
    try:
        log_episode(
            root_dir=root_dir,
            task_id=task_id,
            payload=episode_payload,
            change_reason=f"phase_{phase}_episode",
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "context write-back: log_episode failed; skipping",
            extra={"task_id": task_id, "phase": phase},
        )

    if phase == "plan":
        findings = normalized_response.get("findings") or []
        for i, finding in enumerate(findings[:3]):
            if not isinstance(finding, str) or not finding.strip():
                continue
            key = f"plan-decision-{i}"
            scope = f"task/{task_id}"
            try:
                log_decision(
                    root_dir=root_dir,
                    key=key,
                    scope=scope,
                    payload={"summary": finding.strip(), "phase": phase},
                    change_reason="plan_phase_finding",
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "context write-back: log_decision failed; skipping",
                    extra={"task_id": task_id, "phase": phase, "key": key},
                )


@dataclass(frozen=True)
class PhaseRunResult:
    task_id: str
    executed_phases: list[str]
    controller_status: str
    phase_run_path: Path
    pause_confirm_path: Path | None
    option_decision_path: Path | None


class PhaseRunner:
    def __init__(self, root_dir: Path, *, live_mode: bool = False) -> None:
        self.root_dir = root_dir.resolve()
        self.store = ArtifactStore(self.root_dir)
        self.budget_gate = BudgetGate()
        self.consistency = ArtifactConsistencyChecker(self.root_dir)
        self.task_runner = TaskRunner(self.root_dir)
        self.coordinator = RuntimeCoordinator(self.root_dir, live_mode=live_mode)

    def run(self, *, request_path: Path) -> PhaseRunResult:
        request = self._load_json(request_path)
        task_id = request["task_id"]
        task_root = self.store.task_root(task_id)
        manifest_path = task_root / "manifests" / "manifest.json"
        phase_plan_path = task_root / "phase-runs" / "phase-run.json"

        initial_resolution = resolve_runtime_config(
            root_dir=self.root_dir, request=request
        )
        base_phase = initial_resolution.resolved_config["phase"]
        requested_strategy = request.get("selectors", {}).get("strategy", "")
        selected_strategy = initial_resolution.resolved_config["strategy"][
            "selectedStrategyId"
        ]
        if self._should_block_for_task_ambiguity(
            request=request,
            routing_result=initial_resolution.routing_result,
        ):
            ambiguity_step = self._resolve_step(
                request, initial_resolution.resolved_config
            )
            self.task_runner.pause_step(
                task_id=task_id,
                phase=base_phase,
                step=ambiguity_step,
                reason="task_ambiguity",
                resume_from=ambiguity_step,
            )
            pause_confirm_path = self._write_runtime_pause_confirm(
                task_id=task_id,
                phase=base_phase,
                step=ambiguity_step,
                strategy=selected_strategy,
                blocked_reason="task_ambiguity",
                artifact_refs={
                    "request": str(request_path),
                    "resolvedConfig": "",
                    "routingResult": "",
                    "promptBundle": "",
                    "manifest": str(manifest_path),
                    "response": "",
                    "validation": "",
                    "applyResult": "",
                },
            )
            consistency = self.consistency.check(
                task_id=task_id,
                phase=base_phase,
                step=ambiguity_step,
                filename=f"artifact-consistency-{base_phase}-{ambiguity_step}-blocked.json",
            )
            controller = self._load_json(
                task_state_dir(self.root_dir, task_id) / "controller-state.json"
            )
            phase_run_path = self._write_phase_run_artifact(
                task_id=task_id,
                phase_run_path=phase_plan_path,
                payload={
                    "taskId": task_id,
                    "compositionMode": "single",
                    "requestedPhase": base_phase,
                    "executedPhases": [],
                    "controllerStatus": controller["current_status"],
                    "blockedReason": controller.get("blocked_reason", ""),
                    "optionDecisionRef": "",
                    "consistencyRef": str(consistency.path),
                },
            )
            return PhaseRunResult(
                task_id=task_id,
                executed_phases=[],
                controller_status=controller["current_status"],
                phase_run_path=phase_run_path,
                pause_confirm_path=pause_confirm_path,
                option_decision_path=None,
            )

        if requested_strategy and requested_strategy != selected_strategy:
            option_decision_path, pause_confirm_path = (
                self._write_strategy_override_block(
                    task_id=task_id,
                    request=request,
                    resolved_config=initial_resolution.resolved_config,
                    routing_result=initial_resolution.routing_result,
                    request_path=request_path,
                    manifest_path=manifest_path,
                )
            )
            controller = self._load_json(
                task_state_dir(self.root_dir, task_id) / "controller-state.json"
            )
            consistency = self.consistency.check(
                task_id=task_id,
                phase=base_phase,
                step=self._resolve_step(request, initial_resolution.resolved_config),
                filename=f"artifact-consistency-{base_phase}-strategy-override.json",
            )
            phase_run_path = self._write_phase_run_artifact(
                task_id=task_id,
                phase_run_path=phase_plan_path,
                payload={
                    "taskId": task_id,
                    "compositionMode": "single",
                    "requestedPhase": base_phase,
                    "executedPhases": [],
                    "controllerStatus": controller["current_status"],
                    "blockedReason": controller.get("blocked_reason", ""),
                    "optionDecisionRef": str(option_decision_path),
                    "consistencyRef": str(consistency.path),
                },
            )
            return PhaseRunResult(
                task_id=task_id,
                executed_phases=[],
                controller_status=controller["current_status"],
                phase_run_path=phase_run_path,
                pause_confirm_path=pause_confirm_path,
                option_decision_path=option_decision_path,
            )

        phase_sequence = self._compose_phases(initial_resolution.resolved_config)
        auto_advance_enabled = self._auto_advance_enabled(
            request=request,
            resolved_config=initial_resolution.resolved_config,
        )
        phase_records: list[dict[str, Any]] = []
        pause_confirm_path: Path | None = None
        previous_record: dict[str, Any] | None = None
        counter_seed = self._load_execution_counter_seed(task_id)

        run_index = 0
        phase_blocked = False
        phase_request_seed = request
        phase_index = 0
        while phase_index < len(phase_sequence):
            phase = phase_sequence[phase_index]
            phase_index += 1
            if phase_blocked:
                break
            phase_request = self._phase_request(
                phase_request_seed,
                phase=phase,
                previous_phase_record=previous_record,
            )
            # Resolve config once to get strategy steps for this phase.
            base_resolution = resolve_runtime_config(
                root_dir=self.root_dir, request=phase_request
            )
            strategy_config = base_resolution.resolved_config.get("strategy", {})
            strategy_steps = strategy_config.get("steps", [])
            phase_strategy_id = strategy_config.get("selectedStrategyId")

            # If the request pins a specific step via selector, honour it;
            # otherwise iterate all steps defined in the strategy.
            pinned_step = phase_request.get("selectors", {}).get("step")
            if pinned_step:
                matched_step = next(
                    (
                        step_item
                        for step_item in strategy_steps
                        if step_item.get("id") == pinned_step
                    ),
                    None,
                )
                steps_to_run = (
                    [matched_step]
                    if isinstance(matched_step, dict)
                    else [{"id": pinned_step, "agentProfile": None}]
                )
            elif strategy_steps:
                steps_to_run = strategy_steps
            else:
                steps_to_run = [{"id": "execute", "agentProfile": None}]

            step_records: list[dict[str, Any]] = []
            last_consistency_ref = ""
            phase_had_blocked_step = False
            strategy_switch_ref = ""
            phase_plan_artifact_refs = {
                "planRef": "",
                "checklistRef": "",
                "deferredItemsRef": "",
            }
            prior_step_outputs = self._extract_prior_step_outputs(phase_request)
            if strategy_config.get(
                "requiresBudgetConfirm"
            ) and not self._has_budget_confirmation(
                task_id=task_id, strategy_id=phase_strategy_id
            ):
                preflight_step = "preflight"
                self.task_runner.pause_step(
                    task_id=task_id,
                    phase=phase,
                    step=preflight_step,
                    reason="strategy_budget_preflight",
                    resume_from=preflight_step,
                )
                pause_confirm_path = self._write_runtime_pause_confirm(
                    task_id=task_id,
                    phase=phase,
                    step=preflight_step,
                    strategy=phase_strategy_id,
                    blocked_reason="strategy_budget_preflight",
                    artifact_refs={
                        "request": str(request_path),
                        "resolvedConfig": "",
                        "routingResult": "",
                        "promptBundle": "",
                        "manifest": str(manifest_path),
                        "response": "",
                        "validation": "",
                        "applyResult": "",
                    },
                )
                consistency = self.consistency.check(
                    task_id=task_id,
                    phase=phase,
                    step=preflight_step,
                    filename=f"artifact-consistency-{phase}-{preflight_step}-blocked.json",
                )
                last_consistency_ref = str(consistency.path)
                step_records.append(
                    {
                        "step": preflight_step,
                        "agentProfile": "",
                        "provider": "",
                        "modelRef": "",
                        "strategy": phase_strategy_id,
                        "requestRef": str(request_path),
                        "resolvedConfigRef": "",
                        "routingResultRef": "",
                        "promptBundleRef": "",
                        "responseRef": "",
                        "normalizedRef": "",
                        "validationRef": "",
                        "applyResultRef": "",
                        "controllerStatus": "blocked",
                    }
                )
                phase_had_blocked_step = True
                phase_blocked = True

            loop_iterations: dict[str, int] = {}
            parallel_group_skip_until = -1
            for index, step_def in enumerate(steps_to_run):
                if phase_had_blocked_step:
                    break
                if index < parallel_group_skip_until:
                    continue
                if self._is_parallel_read_only_step(step_def):
                    parallel_group = self._collect_parallel_group(
                        steps_to_run=steps_to_run,
                        start_index=index,
                    )
                    if len(parallel_group) > 1:
                        parallel_group_skip_until = index + len(parallel_group)
                        parallel_result = self._execute_read_only_parallel_group(
                            task_id=task_id,
                            task_root=task_root,
                            request_path=request_path,
                            manifest_path=manifest_path,
                            phase=phase,
                            phase_request=phase_request,
                            steps_to_run=steps_to_run,
                            step_group=parallel_group,
                            phase_strategy_id=phase_strategy_id,
                            previous_record=previous_record,
                            strategy_switch_ref=strategy_switch_ref,
                            step_records=step_records,
                            prior_step_outputs=prior_step_outputs,
                            phase_plan_artifact_refs=phase_plan_artifact_refs,
                            counter_seed=counter_seed,
                            run_index=run_index,
                        )
                        run_index = int(parallel_result["run_index"])
                        phase_strategy_id = str(parallel_result["phase_strategy_id"])
                        strategy_switch_ref = str(
                            parallel_result.get("strategy_switch_ref", "")
                        )
                        new_consistency_ref = str(
                            parallel_result.get("last_consistency_ref", "")
                        )
                        if new_consistency_ref:
                            last_consistency_ref = new_consistency_ref
                        prior_step_outputs = parallel_result.get(
                            "prior_step_outputs", prior_step_outputs
                        )
                        phase_plan_artifact_refs = parallel_result.get(
                            "phase_plan_artifact_refs", phase_plan_artifact_refs
                        )
                        pause_path = parallel_result.get("pause_confirm_path")
                        if isinstance(pause_path, Path):
                            pause_confirm_path = pause_path
                        phase_had_blocked_step = bool(
                            parallel_result.get("phase_had_blocked_step", False)
                        )
                        phase_blocked = bool(
                            parallel_result.get("phase_blocked", False)
                        )
                        if phase_had_blocked_step:
                            break
                        continue
                step = step_def.get("id", "execute")
                agent_profile = step_def.get("agentProfile")
                step_loop_key = f"{phase}:{step}"
                while True:
                    run_index += 1
                    contract_ok = True
                    contract_reason = ""
                    try:
                        contract_ok, contract_reason = check_input_contract(
                            task_root=task_root,
                            step_def=step_def,
                            prior_step_records=step_records,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "step input contract check failed; continuing without blocking",
                            extra={
                                "task_id": task_id,
                                "phase": phase,
                                "step": step,
                            },
                        )
                        contract_ok = True
                        contract_reason = ""

                    if not contract_ok:
                        blocked_reason = f"step_input_contract_failed:{contract_reason}"
                        self.task_runner.pause_step(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            reason="step_input_contract_failed",
                            resume_from=step,
                        )
                        pause_confirm_path = self._write_runtime_pause_confirm(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            strategy=phase_strategy_id,
                            blocked_reason=blocked_reason,
                            artifact_refs={
                                "request": str(request_path),
                                "resolvedConfig": "",
                                "routingResult": "",
                                "promptBundle": "",
                                "manifest": str(manifest_path),
                                "response": "",
                                "validation": "",
                                "applyResult": "",
                            },
                        )
                        consistency = self.consistency.check(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            filename=f"artifact-consistency-{phase}-{step}-blocked.json",
                        )
                        last_consistency_ref = str(consistency.path)
                        step_records.append(
                            {
                                "step": step,
                                "agentProfile": agent_profile or "",
                                "provider": "",
                                "modelRef": "",
                                "strategy": phase_strategy_id,
                                "requestRef": str(request_path),
                                "resolvedConfigRef": "",
                                "routingResultRef": "",
                                "promptBundleRef": "",
                                "responseRef": "",
                                "normalizedRef": "",
                                "validationRef": "",
                                "applyResultRef": "",
                                "controllerStatus": "blocked",
                            }
                        )
                        phase_had_blocked_step = True
                        phase_blocked = True
                        break

                    step_request = phase_request
                    try:
                        step_request = inject_artifact_refs(
                            request=phase_request,
                            task_root=task_root,
                            step_def=step_def,
                            prior_step_records=step_records,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "failed to inject prior artifact refs; continuing with base request",
                            extra={
                                "task_id": task_id,
                                "phase": phase,
                                "step": step,
                            },
                        )
                    resolution = resolve_runtime_config(
                        root_dir=self.root_dir,
                        request=step_request,
                        agent_profile_override=agent_profile,
                        step_id=step,
                    )
                    current_step_strategy = resolution.resolved_config["strategy"][
                        "selectedStrategyId"
                    ]
                    resolved_strategy = resolution.resolved_config.get("strategy", {})
                    strategy_config = resolution.bundle.strategies.get(
                        current_step_strategy, {}
                    )
                    strategy_id = str(
                        resolved_strategy.get("strategyId", current_step_strategy)
                    )
                    try:
                        max_loops = int(
                            resolved_strategy.get(
                                "maxRepairLoops",
                                strategy_config.get("maxRepairLoops", 0),
                            )
                            or 0
                        )
                    except (TypeError, ValueError):
                        max_loops = 0
                    try:
                        estimated_cost_per_loop = float(
                            resolved_strategy.get(
                                "estimatedCallsPerLoop",
                                strategy_config.get("estimatedCallsPerLoop", 1),
                            )
                            or 1.0
                        )
                    except (TypeError, ValueError):
                        estimated_cost_per_loop = 1.0

                    if index == 0:
                        phase_strategy_id = current_step_strategy
                        if (
                            previous_record
                            and previous_record["strategy"] != phase_strategy_id
                        ):
                            strategy_switch_ref = str(
                                self._write_strategy_switch_artifact(
                                    task_id=task_id,
                                    from_phase=previous_record["phase"],
                                    from_strategy=previous_record["strategy"],
                                    to_phase=phase,
                                    to_strategy=phase_strategy_id,
                                    reason_code="phase_composition_follow_on",
                                )
                            )

                    attempt, run = self._resolve_execution_counters(
                        counter_seed=counter_seed,
                        phase=phase,
                        step=step,
                        run_index=run_index,
                    )
                    artifact_refs = self._materialize_phase_inputs(
                        task_id=task_id,
                        request=step_request,
                        resolved_config=resolution.resolved_config,
                        routing_result=resolution.routing_result,
                        phase=phase,
                        step=step,
                        step_def=step_def,
                        is_first_step=(index == 0),
                        prior_step_outputs=prior_step_outputs,
                    )

                    provider_config = resolution.resolved_config.get("provider", {})
                    self.task_runner.start_phase(
                        task_id=task_id,
                        phase=phase,
                        step=step,
                        strategy=phase_strategy_id,
                        attempt=attempt,
                        run=run,
                    )
                    try:
                        coordination = self.coordinator.execute_phase(
                            task_id=task_id,
                            request_path=Path(artifact_refs["request"]),
                            phase=phase,
                            step=step,
                            resolved_config_path=Path(artifact_refs["resolvedConfig"]),
                            routing_result_path=Path(artifact_refs["routingResult"]),
                            prompt_bundle_path=Path(artifact_refs["promptBundle"]),
                            manifest_path=manifest_path,
                            attempt=attempt,
                            run=run,
                            auto_apply=(phase in ("impl", "review", "harden")),
                        )
                    except ProviderNotFoundError:
                        self.task_runner.pause_step(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            reason="missing_tool_or_auth",
                            resume_from=step,
                        )
                        pause_confirm_path = self._write_runtime_pause_confirm(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            strategy=phase_strategy_id,
                            blocked_reason="missing_tool_or_auth",
                            artifact_refs={
                                "request": artifact_refs["request"],
                                "resolvedConfig": artifact_refs["resolvedConfig"],
                                "routingResult": artifact_refs["routingResult"],
                                "promptBundle": artifact_refs["promptBundle"],
                                "manifest": str(manifest_path),
                                "response": "",
                                "validation": "",
                                "applyResult": "",
                            },
                        )
                        consistency = self.consistency.check(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            filename=f"artifact-consistency-{phase}-{step}-blocked.json",
                        )
                        last_consistency_ref = str(consistency.path)
                        step_records.append(
                            {
                                "step": step,
                                "agentProfile": agent_profile or "",
                                "provider": provider_config.get("provider") or "",
                                "modelRef": provider_config.get("modelRef") or "",
                                "strategy": current_step_strategy,
                                "requestRef": artifact_refs["request"],
                                "resolvedConfigRef": artifact_refs["resolvedConfig"],
                                "routingResultRef": artifact_refs["routingResult"],
                                "promptBundleRef": artifact_refs["promptBundle"],
                                "responseRef": "",
                                "normalizedRef": "",
                                "validationRef": "",
                                "applyResultRef": "",
                                "controllerStatus": "blocked",
                            }
                        )
                        phase_had_blocked_step = True
                        phase_blocked = True
                        break
                    except Exception as exc:  # noqa: BLE001
                        if not self._exception_indicates_missing_tool_or_auth(exc):
                            raise
                        self.task_runner.pause_step(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            reason="missing_tool_or_auth",
                            resume_from=step,
                        )
                        pause_confirm_path = self._write_runtime_pause_confirm(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            strategy=phase_strategy_id,
                            blocked_reason="missing_tool_or_auth",
                            artifact_refs={
                                "request": artifact_refs["request"],
                                "resolvedConfig": artifact_refs["resolvedConfig"],
                                "routingResult": artifact_refs["routingResult"],
                                "promptBundle": artifact_refs["promptBundle"],
                                "manifest": str(manifest_path),
                                "response": "",
                                "validation": "",
                                "applyResult": "",
                            },
                        )
                        consistency = self.consistency.check(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            filename=f"artifact-consistency-{phase}-{step}-blocked.json",
                        )
                        last_consistency_ref = str(consistency.path)
                        step_records.append(
                            {
                                "step": step,
                                "agentProfile": agent_profile or "",
                                "provider": provider_config.get("provider") or "",
                                "modelRef": provider_config.get("modelRef") or "",
                                "strategy": current_step_strategy,
                                "requestRef": artifact_refs["request"],
                                "resolvedConfigRef": artifact_refs["resolvedConfig"],
                                "routingResultRef": artifact_refs["routingResult"],
                                "promptBundleRef": artifact_refs["promptBundle"],
                                "responseRef": "",
                                "normalizedRef": "",
                                "validationRef": "",
                                "applyResultRef": "",
                                "controllerStatus": "blocked",
                            }
                        )
                        phase_had_blocked_step = True
                        phase_blocked = True
                        break

                    step_records.append(
                        {
                            "step": step,
                            "agentProfile": agent_profile or "",
                            "provider": provider_config.get("provider") or "",
                            "modelRef": provider_config.get("modelRef") or "",
                            "strategy": current_step_strategy,
                            "requestRef": artifact_refs["request"],
                            "resolvedConfigRef": artifact_refs["resolvedConfig"],
                            "routingResultRef": artifact_refs["routingResult"],
                            "promptBundleRef": artifact_refs["promptBundle"],
                            "responseRef": str(coordination.response_path),
                            "normalizedRef": str(coordination.normalized_path),
                            "validationRef": str(coordination.validation_path),
                            "applyResultRef": (
                                str(coordination.apply_result_path)
                                if coordination.apply_result_path
                                else ""
                            ),
                            "controllerStatus": coordination.controller_status,
                        }
                    )
                    consistency = self.consistency.check(
                        task_id=task_id,
                        phase=phase,
                        step=step,
                    )
                    last_consistency_ref = str(consistency.path)
                    if self._consistency_failed(consistency):
                        self.task_runner.pause_step(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            reason="artifact_consistency_failure",
                            resume_from=step,
                        )
                        pause_confirm_path = self._write_runtime_pause_confirm(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            strategy=phase_strategy_id,
                            blocked_reason="artifact_consistency_failure",
                            artifact_refs={
                                "request": artifact_refs["request"],
                                "resolvedConfig": artifact_refs["resolvedConfig"],
                                "routingResult": artifact_refs["routingResult"],
                                "promptBundle": artifact_refs["promptBundle"],
                                "manifest": str(coordination.manifest_path),
                                "response": str(coordination.response_path),
                                "validation": str(coordination.validation_path),
                                "applyResult": (
                                    str(coordination.apply_result_path)
                                    if coordination.apply_result_path
                                    else ""
                                ),
                            },
                        )
                        phase_had_blocked_step = True
                        phase_blocked = True
                        break

                    pause_artifact_refs = {
                        "request": artifact_refs["request"],
                        "resolvedConfig": artifact_refs["resolvedConfig"],
                        "routingResult": artifact_refs["routingResult"],
                        "promptBundle": artifact_refs["promptBundle"],
                        "manifest": str(coordination.manifest_path),
                        "response": str(coordination.response_path),
                        "validation": str(coordination.validation_path),
                        "applyResult": (
                            str(coordination.apply_result_path)
                            if coordination.apply_result_path
                            else ""
                        ),
                    }

                    output_ok = True
                    if coordination.controller_status != "blocked":
                        output_ok, output_reason = self._check_step_output_contract(
                            task_root=task_root,
                            step_def=step_def,
                            step_record=step_records[-1],
                        )
                    if not output_ok:
                        blocked_reason = f"step_output_contract_failed:{output_reason}"
                        logger.warning(
                            "step output contract failed; blocking subsequent steps",
                            extra={
                                "task_id": task_id,
                                "phase": phase,
                                "step": step,
                                "reason": output_reason,
                            },
                        )
                        pause_confirm_path = self._write_runtime_pause_confirm(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            strategy=phase_strategy_id,
                            blocked_reason=blocked_reason,
                            artifact_refs=pause_artifact_refs,
                        )
                        phase_had_blocked_step = True
                        phase_blocked = True
                        break

                    step_summary, step_snippet = self._extract_response_context(
                        response_path=coordination.response_path,
                        raw_output_path=coordination.raw_output_path,
                    )
                    prior_step_outputs = self._append_prior_step_output(
                        prior_step_outputs,
                        step=step,
                        summary=step_summary,
                        content_snippet=step_snippet,
                    )
                    output_text = ""
                    try:
                        output_text = coordination.response_path.read_text(
                            encoding="utf-8"
                        )
                    except Exception:  # noqa: BLE001
                        output_text = ""
                    if os.environ.get("CONTEXTS_ENABLED", "1") != "0":
                        self._writeback_context(
                            f"{phase}:{step}",
                            output_text,
                            task_id,
                            self.root_dir,
                        )

                    if (
                        phase == "plan"
                        and coordination.controller_status != "blocked"
                        and index == len(steps_to_run) - 1
                    ):
                        plan_artifact_result = self._emit_plan_artifacts(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            normalized_path=coordination.normalized_path,
                        )
                        if plan_artifact_result.get("blocked"):
                            pause_confirm_path = self._write_runtime_pause_confirm(
                                task_id=task_id,
                                phase=phase,
                                step=step,
                                strategy=phase_strategy_id,
                                blocked_reason=PLAN_ARTIFACT_INCOMPLETE,
                                artifact_refs=pause_artifact_refs,
                            )
                            consistency = self.consistency.check(
                                task_id=task_id,
                                phase=phase,
                                step=step,
                                filename=f"artifact-consistency-{phase}-{step}-blocked.json",
                            )
                            last_consistency_ref = str(consistency.path)
                            phase_had_blocked_step = True
                            phase_blocked = True
                            break
                        phase_plan_artifact_refs = plan_artifact_result
                        self.task_runner.sync_manifest_snapshot(
                            task_id,
                            artifact_refs=phase_plan_artifact_refs,
                            plan_artifact_refs=phase_plan_artifact_refs,
                        )

                    if phase in ("review", "harden"):
                        gate_result = self._load_review_gate_result(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            attempt=attempt,
                            run=run,
                            normalized_path=coordination.normalized_path,
                        )
                        if gate_result is not None:
                            loop_iteration = loop_iterations.get(step_loop_key, 0)
                            if max_loops > 0:
                                should_continue, loop_reason = should_continue_loop(
                                    gate_result,
                                    {
                                        "current_iteration": loop_iteration,
                                        "max_loops": max_loops,
                                        "currentIteration": loop_iteration,
                                        "maxLoops": max_loops,
                                    },
                                )
                            else:
                                should_continue = False
                                loop_reason = (
                                    "blocking_cleared"
                                    if not gate_result.blocking_found
                                    else "no_looping_configured"
                                )

                            loop_status = "running" if should_continue else "completed"
                            if loop_reason == "loop_cap_reached":
                                loop_status = "paused_loop_cap"
                            self._write_loop_state_record(
                                task_id=task_id,
                                phase=phase,
                                step=step,
                                strategy_id=strategy_id,
                                current_iteration=loop_iteration,
                                max_loops=max_loops,
                                status=loop_status,
                                blockers_remaining=len(gate_result.findings),
                            )

                            if should_continue:
                                next_iteration = loop_iteration + 1
                                budget = resolution.resolved_config.get(
                                    "budget",
                                    resolution.resolved_config.get("budgetProfile", {}),
                                )
                                budget_decision = (
                                    self.budget_gate.evaluate_loop_iteration(
                                        budget,
                                        current_iteration=next_iteration,
                                        max_loops=max_loops,
                                        estimated_cost_per_loop=estimated_cost_per_loop,
                                    )
                                )
                                if budget_decision.stop_required:
                                    self._write_loop_state_record(
                                        task_id=task_id,
                                        phase=phase,
                                        step=step,
                                        strategy_id=strategy_id,
                                        current_iteration=next_iteration,
                                        max_loops=max_loops,
                                        status="paused_budget",
                                        blockers_remaining=len(gate_result.findings),
                                    )
                                    (
                                        pause_confirm_path,
                                        last_consistency_ref,
                                    ) = self._pause_review_loop_step(
                                        task_id=task_id,
                                        phase=phase,
                                        step=step,
                                        strategy=phase_strategy_id,
                                        reason=BUDGET_STOP,
                                        artifact_refs=pause_artifact_refs,
                                        attempt=attempt,
                                        run=run,
                                    )
                                    phase_had_blocked_step = True
                                    phase_blocked = True
                                    break
                                loop_iterations[step_loop_key] = next_iteration
                                continue

                            if gate_result.blocking_found:
                                pause_reason = ""
                                if loop_reason == "loop_cap_reached":
                                    pause_reason = LOOP_CAP_REACHED
                                elif loop_reason in {
                                    "no_fixable_operations",
                                    "no_looping_configured",
                                }:
                                    pause_reason = "review_blocking_findings"
                                if pause_reason:
                                    (
                                        pause_confirm_path,
                                        last_consistency_ref,
                                    ) = self._pause_review_loop_step(
                                        task_id=task_id,
                                        phase=phase,
                                        step=step,
                                        strategy=phase_strategy_id,
                                        reason=pause_reason,
                                        artifact_refs=pause_artifact_refs,
                                        attempt=attempt,
                                        run=run,
                                    )
                                    phase_had_blocked_step = True
                                    phase_blocked = True
                                    break

                    if coordination.controller_status == "blocked":
                        blocked_reason = self._coordination_blocked_reason(coordination)
                        pause_confirm_path = self._write_runtime_pause_confirm(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            strategy=phase_strategy_id,
                            blocked_reason=blocked_reason,
                            artifact_refs=pause_artifact_refs,
                        )
                        consistency = self.consistency.check(
                            task_id=task_id,
                            phase=phase,
                            step=step,
                            filename=f"artifact-consistency-{phase}-{step}-blocked.json",
                        )
                        last_consistency_ref = str(consistency.path)
                        if self._consistency_failed(consistency):
                            pause_confirm_path = self._write_runtime_pause_confirm(
                                task_id=task_id,
                                phase=phase,
                                step=step,
                                strategy=phase_strategy_id,
                                blocked_reason="artifact_consistency_failure",
                                artifact_refs=pause_artifact_refs,
                            )
                        phase_had_blocked_step = True
                        phase_blocked = True
                        break

                    break

            if not step_records:
                continue
            phase_blocked_reason = ""
            if phase_had_blocked_step:
                try:
                    phase_controller = self._load_json(
                        task_state_dir(self.root_dir, task_id) / "controller-state.json"
                    )
                    phase_blocked_reason = str(
                        phase_controller.get("blocked_reason", "")
                    )
                except Exception:  # noqa: BLE001
                    phase_blocked_reason = "phase_blocked"
            final_report = build_final_report(
                task_id=task_id,
                phase=phase,
                strategy_id=phase_strategy_id or "",
                step_records=step_records,
                plan_artifact_refs=(
                    phase_plan_artifact_refs if phase == "plan" else None
                ),
                blocked_reason=phase_blocked_reason,
                controller_status="blocked" if phase_had_blocked_step else "completed",
            )
            final_report_record = self.store.write_json_artifact(
                task_id=task_id,
                family="final-reports",
                artifact_type="final-report",
                payload=final_report,
                filename=f"final-report-{phase}.json",
                phase=phase,
                step="final-report",
            )
            first_step_record = step_records[0]
            last_step_record = step_records[-1]
            self.task_runner.sync_manifest_snapshot(
                task_id,
                final_report_ref=str(final_report_record.path),
            )
            if not phase_had_blocked_step:
                _write_back_context(
                    root_dir=self.root_dir,
                    task_id=task_id,
                    phase=phase,
                    request=phase_request,
                    normalized_response=_load_normalized_response(
                        last_step_record.get("normalizedRef", "")
                    ),
                    expected_revision=(
                        phase_request.get("operator_context", {}).get(
                            "stored_context_revision", 0
                        )
                    ),
                )

            phase_record = {
                "phase": phase,
                "strategy": phase_strategy_id,
                "requestRef": first_step_record["requestRef"],
                "resolvedConfigRef": first_step_record["resolvedConfigRef"],
                "routingResultRef": first_step_record["routingResultRef"],
                "promptBundleRef": first_step_record["promptBundleRef"],
                "responseRef": last_step_record["responseRef"],
                "validationRef": last_step_record["validationRef"],
                "applyResultRef": (
                    last_step_record["applyResultRef"] if phase == "impl" else ""
                ),
                "strategySwitchRef": strategy_switch_ref,
                "consistencyRef": last_consistency_ref,
                "controllerStatus": (
                    "blocked"
                    if phase_had_blocked_step
                    else last_step_record["controllerStatus"]
                ),
                "planRef": phase_plan_artifact_refs["planRef"],
                "checklistRef": phase_plan_artifact_refs["checklistRef"],
                "deferredItemsRef": phase_plan_artifact_refs["deferredItemsRef"],
                "finalReportRef": str(final_report_record.path),
                "stepRecords": step_records,
            }
            phase_records.append(phase_record)
            previous_record = phase_record
            phase_request_seed = phase_request
            if auto_advance_enabled and not phase_had_blocked_step:
                next_phase = self._next_phase(phase)
                if (
                    next_phase
                    and next_phase not in phase_sequence
                    and self._can_auto_advance(
                        root_dir=self.root_dir,
                        request=phase_request,
                        phase=next_phase,
                        previous_phase_record=phase_record,
                    )
                ):
                    phase_sequence.append(next_phase)

        controller = self._load_json(
            task_state_dir(self.root_dir, task_id) / "controller-state.json"
        )
        phase_run_path = self._write_phase_run_artifact(
            task_id=task_id,
            phase_run_path=phase_plan_path,
            payload={
                "taskId": task_id,
                "compositionMode": "composed" if len(phase_sequence) > 1 else "single",
                "requestedPhase": base_phase,
                "executedPhases": [record["phase"] for record in phase_records],
                "phaseRecords": phase_records,
                "controllerStatus": controller["current_status"],
                "blockedReason": controller.get("blocked_reason", ""),
                "withHarden": bool(
                    initial_resolution.resolved_config.get("phaseOptions", {}).get(
                        "withHarden", False
                    )
                ),
                "autoAdvance": auto_advance_enabled,
                "consistencyRefs": [
                    record["consistencyRef"] for record in phase_records
                ],
                "optionDecisionRef": "",
            },
        )
        return PhaseRunResult(
            task_id=task_id,
            executed_phases=[record["phase"] for record in phase_records],
            controller_status=controller["current_status"],
            phase_run_path=phase_run_path,
            pause_confirm_path=pause_confirm_path,
            option_decision_path=None,
        )

    def _is_parallel_read_only_step(self, step_def: dict[str, Any]) -> bool:
        return bool(step_def.get("readOnly", False)) and is_parallel_step(step_def)

    def _collect_parallel_group(
        self, *, steps_to_run: list[dict[str, Any]], start_index: int
    ) -> list[tuple[int, dict[str, Any]]]:
        group: list[tuple[int, dict[str, Any]]] = []
        index = start_index
        while index < len(steps_to_run):
            step_def = steps_to_run[index]
            if not self._is_parallel_read_only_step(step_def):
                break
            group.append((index, step_def))
            index += 1
        return group

    def _parallel_max_workers(self, group_size: int) -> int:
        if group_size <= 1:
            return 1
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return 1
        return min(3, group_size)

    def _extract_context_update(self, output_text: str) -> dict[str, Any] | None:
        """Extract ```json:context-update``` block from agent output."""
        pattern = r"```json:context-update\s*\n(.*?)\n```"
        match = re.search(pattern, output_text or "", re.DOTALL)
        if not match:
            return None
        try:
            loaded = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None

    def _writeback_context(
        self,
        step_id: str,
        output_text: str,
        task_id: str,
        root_dir: Path,
    ) -> None:
        """Write episode and optional context-update payload after step completion."""
        import os

        if os.environ.get("CONTEXTS_ENABLED", "1") == "0":
            return

        from agentorch_ctx.runtime.context_bridge import (
            get_current_revision,
            log_decision,
            log_episode,
            save_task_snapshot,
        )

        try:
            log_episode(
                root_dir=root_dir,
                task_id=task_id,
                payload={
                    "observation": f"{step_id} completed",
                    "action": "automated-step",
                },
            )
        except Exception:  # noqa: BLE001
            pass

        ctx_update = self._extract_context_update(output_text)
        if not ctx_update:
            return

        revision = get_current_revision(root_dir=root_dir, task_id=task_id)

        progress = ctx_update.get("task_progress")
        if isinstance(progress, str) and progress.strip():
            try:
                save_task_snapshot(
                    root_dir=root_dir,
                    task_id=task_id,
                    payload={"progress": progress},
                    expected_revision=revision,
                    change_reason=f"{step_id} context update",
                )
            except Exception:  # noqa: BLE001
                pass

        decisions = ctx_update.get("decisions", [])
        if not isinstance(decisions, list):
            return
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            key = decision.get("key", step_id)
            if not isinstance(key, str) or not key:
                key = step_id
            try:
                log_decision(
                    root_dir=root_dir,
                    key=key,
                    scope=f"task/{task_id}",
                    payload=decision,
                )
            except Exception:  # noqa: BLE001
                pass

    def _execute_read_only_parallel_group(
        self,
        *,
        task_id: str,
        task_root: Path,
        request_path: Path,
        manifest_path: Path,
        phase: str,
        phase_request: dict[str, Any],
        steps_to_run: list[dict[str, Any]],
        step_group: list[tuple[int, dict[str, Any]]],
        phase_strategy_id: str | None,
        previous_record: dict[str, Any] | None,
        strategy_switch_ref: str,
        step_records: list[dict[str, Any]],
        prior_step_outputs: list[dict[str, str]],
        phase_plan_artifact_refs: dict[str, str],
        counter_seed: dict[str, int],
        run_index: int,
    ) -> dict[str, Any]:
        local_run_index = run_index
        local_phase_strategy_id = phase_strategy_id or ""
        local_strategy_switch_ref = strategy_switch_ref
        local_last_consistency_ref = ""
        local_prior_step_outputs = list(prior_step_outputs)
        local_phase_plan_artifact_refs = dict(phase_plan_artifact_refs)
        local_pause_confirm_path: Path | None = None
        phase_had_blocked_step = False
        phase_blocked = False

        prepared_jobs: list[dict[str, Any]] = []
        for step_index, step_def in step_group:
            local_run_index += 1
            step = step_def.get("id", "execute")
            agent_profile = step_def.get("agentProfile")
            contract_ok = True
            contract_reason = ""
            try:
                contract_ok, contract_reason = check_input_contract(
                    task_root=task_root,
                    step_def=step_def,
                    prior_step_records=step_records,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "step input contract check failed; continuing without blocking",
                    extra={"task_id": task_id, "phase": phase, "step": step},
                )
                contract_ok = True
                contract_reason = ""

            if not contract_ok:
                blocked_reason = f"step_input_contract_failed:{contract_reason}"
                self.task_runner.pause_step(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    reason="step_input_contract_failed",
                    resume_from=step,
                )
                local_pause_confirm_path = self._write_runtime_pause_confirm(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    strategy=local_phase_strategy_id,
                    blocked_reason=blocked_reason,
                    artifact_refs={
                        "request": str(request_path),
                        "resolvedConfig": "",
                        "routingResult": "",
                        "promptBundle": "",
                        "manifest": str(manifest_path),
                        "response": "",
                        "validation": "",
                        "applyResult": "",
                    },
                )
                consistency = self.consistency.check(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    filename=f"artifact-consistency-{phase}-{step}-blocked.json",
                )
                local_last_consistency_ref = str(consistency.path)
                step_records.append(
                    {
                        "step": step,
                        "agentProfile": agent_profile or "",
                        "provider": "",
                        "modelRef": "",
                        "strategy": local_phase_strategy_id,
                        "requestRef": str(request_path),
                        "resolvedConfigRef": "",
                        "routingResultRef": "",
                        "promptBundleRef": "",
                        "responseRef": "",
                        "normalizedRef": "",
                        "validationRef": "",
                        "applyResultRef": "",
                        "controllerStatus": "blocked",
                        "parallelMode": "parallel_read_only",
                    }
                )
                phase_had_blocked_step = True
                phase_blocked = True
                return {
                    "run_index": local_run_index,
                    "phase_strategy_id": local_phase_strategy_id,
                    "strategy_switch_ref": local_strategy_switch_ref,
                    "last_consistency_ref": local_last_consistency_ref,
                    "prior_step_outputs": local_prior_step_outputs,
                    "phase_plan_artifact_refs": local_phase_plan_artifact_refs,
                    "pause_confirm_path": local_pause_confirm_path,
                    "phase_had_blocked_step": phase_had_blocked_step,
                    "phase_blocked": phase_blocked,
                }

            step_request = phase_request
            try:
                step_request = inject_artifact_refs(
                    request=phase_request,
                    task_root=task_root,
                    step_def=step_def,
                    prior_step_records=step_records,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "failed to inject prior artifact refs; continuing with base request",
                    extra={"task_id": task_id, "phase": phase, "step": step},
                )
            resolution = resolve_runtime_config(
                root_dir=self.root_dir,
                request=step_request,
                agent_profile_override=agent_profile,
                step_id=step,
            )
            current_step_strategy = resolution.resolved_config["strategy"][
                "selectedStrategyId"
            ]

            if step_index == 0:
                local_phase_strategy_id = current_step_strategy
                if (
                    previous_record
                    and previous_record["strategy"] != local_phase_strategy_id
                ):
                    local_strategy_switch_ref = str(
                        self._write_strategy_switch_artifact(
                            task_id=task_id,
                            from_phase=previous_record["phase"],
                            from_strategy=previous_record["strategy"],
                            to_phase=phase,
                            to_strategy=local_phase_strategy_id,
                            reason_code="phase_composition_follow_on",
                        )
                    )

            attempt, run = self._resolve_execution_counters(
                counter_seed=counter_seed,
                phase=phase,
                step=step,
                run_index=local_run_index,
            )
            artifact_refs = self._materialize_phase_inputs(
                task_id=task_id,
                request=step_request,
                resolved_config=resolution.resolved_config,
                routing_result=resolution.routing_result,
                phase=phase,
                step=step,
                step_def=step_def,
                is_first_step=(step_index == 0),
                prior_step_outputs=local_prior_step_outputs,
            )
            provider_config = resolution.resolved_config.get("provider", {})
            self.task_runner.start_phase(
                task_id=task_id,
                phase=phase,
                step=step,
                strategy=local_phase_strategy_id,
                attempt=attempt,
                run=run,
            )
            prepared_jobs.append(
                {
                    "step": step,
                    "step_index": step_index,
                    "agent_profile": agent_profile or "",
                    "strategy": current_step_strategy,
                    "artifact_refs": artifact_refs,
                    "provider_config": provider_config,
                    "attempt": attempt,
                    "run": run,
                }
            )

        parallel_defs: list[dict[str, Any]] = []
        for index, job in enumerate(prepared_jobs):
            parallel_defs.append(
                {
                    "id": f"{job['step']}@{index}",
                    "_job": job,
                }
            )

        def _execute_parallel_job(step_payload: dict[str, Any]) -> dict[str, Any]:
            job = step_payload.get("_job", {})
            artifact_refs = job.get("artifact_refs", {})
            step = str(job.get("step", "unknown"))
            try:
                coordination = self.coordinator.execute_phase(
                    task_id=task_id,
                    request_path=Path(artifact_refs["request"]),
                    phase=phase,
                    step=step,
                    resolved_config_path=Path(artifact_refs["resolvedConfig"]),
                    routing_result_path=Path(artifact_refs["routingResult"]),
                    prompt_bundle_path=Path(artifact_refs["promptBundle"]),
                    manifest_path=manifest_path,
                    attempt=int(job.get("attempt", 1)),
                    run=int(job.get("run", 1)),
                    auto_apply=False,
                    state_updates_enabled=False,
                )
                return {
                    "step": step,
                    "success": True,
                    "output": {
                        **job,
                        "response_ref": str(coordination.response_path),
                        "normalized_ref": str(coordination.normalized_path),
                        "validation_ref": str(coordination.validation_path),
                        "apply_result_ref": (
                            str(coordination.apply_result_path)
                            if coordination.apply_result_path
                            else ""
                        ),
                        "raw_output_ref": (
                            str(coordination.raw_output_path)
                            if coordination.raw_output_path
                            else ""
                        ),
                        "controller_status": coordination.controller_status,
                        "blocked_reason": coordination.blocked_reason,
                    },
                }
            except ProviderNotFoundError:
                return {
                    "step": step,
                    "success": False,
                    "output": {**job},
                    "error": "missing_tool_or_auth",
                }
            except Exception as exc:  # noqa: BLE001
                if self._exception_indicates_missing_tool_or_auth(exc):
                    return {
                        "step": step,
                        "success": False,
                        "output": {**job},
                        "error": "missing_tool_or_auth",
                    }
                return {
                    "step": step,
                    "success": False,
                    "output": {**job},
                    "error": str(exc)[:500],
                }

        raw_parallel_results = execute_steps_parallel(
            step_defs=parallel_defs,
            execute_fn=_execute_parallel_job,
            max_workers=self._parallel_max_workers(len(parallel_defs)),
        )
        parallel_results = sorted(
            raw_parallel_results,
            key=lambda item: int(item.output.get("step_index", 10_000)),
        )

        merge_artifact = merge_parallel_results(parallel_results)
        merge_step_ids = [sd.get("id", "unknown") for _, sd in step_group]
        merge_label = "_".join(merge_step_ids[:3]) if merge_step_ids else "parallel"
        self.store.write_json_artifact(
            task_id=task_id,
            family="merge-inputs",
            artifact_type="parallel_merge",
            payload=merge_artifact,
            filename=f"merge-{phase}-{merge_label}.json",
            phase=phase,
            step=merge_label,
        )

        for result in parallel_results:
            output = result.output if isinstance(result.output, dict) else {}
            step = str(output.get("step", result.step_id))
            agent_profile = str(output.get("agent_profile", ""))
            strategy = str(output.get("strategy", local_phase_strategy_id))
            artifact_refs = output.get("artifact_refs", {})
            provider_config = output.get("provider_config", {})
            response_ref = str(output.get("response_ref", ""))
            normalized_ref = str(output.get("normalized_ref", ""))
            validation_ref = str(output.get("validation_ref", ""))
            apply_result_ref = str(output.get("apply_result_ref", ""))
            controller_status = str(output.get("controller_status", "partial"))
            blocked_reason = str(output.get("blocked_reason", ""))

            if not result.success:
                blocked_reason = str(
                    output.get("error", result.error or "parallel_step_failed")
                )
                reason_code = (
                    "missing_tool_or_auth"
                    if blocked_reason == "missing_tool_or_auth"
                    else "parallel_step_failed"
                )
                self.task_runner.pause_step(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    reason=reason_code,
                    resume_from=step,
                )
                local_pause_confirm_path = self._write_runtime_pause_confirm(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    strategy=local_phase_strategy_id,
                    blocked_reason=blocked_reason,
                    artifact_refs={
                        "request": artifact_refs.get("request", ""),
                        "resolvedConfig": artifact_refs.get("resolvedConfig", ""),
                        "routingResult": artifact_refs.get("routingResult", ""),
                        "promptBundle": artifact_refs.get("promptBundle", ""),
                        "manifest": str(manifest_path),
                        "response": response_ref,
                        "validation": validation_ref,
                        "applyResult": apply_result_ref,
                    },
                )
                consistency = self.consistency.check(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    filename=f"artifact-consistency-{phase}-{step}-blocked.json",
                )
                local_last_consistency_ref = str(consistency.path)
                step_records.append(
                    {
                        "step": step,
                        "agentProfile": agent_profile,
                        "provider": provider_config.get("provider") or "",
                        "modelRef": provider_config.get("modelRef") or "",
                        "strategy": strategy,
                        "requestRef": artifact_refs.get("request", ""),
                        "resolvedConfigRef": artifact_refs.get("resolvedConfig", ""),
                        "routingResultRef": artifact_refs.get("routingResult", ""),
                        "promptBundleRef": artifact_refs.get("promptBundle", ""),
                        "responseRef": "",
                        "normalizedRef": "",
                        "validationRef": "",
                        "applyResultRef": "",
                        "controllerStatus": "blocked",
                        "parallelMode": "parallel_read_only",
                    }
                )
                phase_had_blocked_step = True
                phase_blocked = True
                break

            if controller_status != "blocked":
                self.task_runner.complete_step(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    artifact_ref=validation_ref or response_ref,
                    partial=True,
                )
            else:
                self.task_runner.pause_step(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    reason=blocked_reason or "parallel_step_blocked",
                    resume_from=step,
                )

            step_records.append(
                {
                    "step": step,
                    "agentProfile": agent_profile,
                    "provider": provider_config.get("provider") or "",
                    "modelRef": provider_config.get("modelRef") or "",
                    "strategy": strategy,
                    "requestRef": artifact_refs.get("request", ""),
                    "resolvedConfigRef": artifact_refs.get("resolvedConfig", ""),
                    "routingResultRef": artifact_refs.get("routingResult", ""),
                    "promptBundleRef": artifact_refs.get("promptBundle", ""),
                    "responseRef": response_ref,
                    "normalizedRef": normalized_ref,
                    "validationRef": validation_ref,
                    "applyResultRef": apply_result_ref,
                    "controllerStatus": controller_status,
                    "parallelMode": "parallel_read_only",
                }
            )
            consistency = self.consistency.check(
                task_id=task_id, phase=phase, step=step
            )
            local_last_consistency_ref = str(consistency.path)

            raw_output_ref = str(output.get("raw_output_ref", ""))
            if response_ref:
                step_summary, step_snippet = self._extract_response_context(
                    response_path=Path(response_ref),
                    raw_output_path=Path(raw_output_ref) if raw_output_ref else None,
                )
                local_prior_step_outputs = self._append_prior_step_output(
                    local_prior_step_outputs,
                    step=step,
                    summary=step_summary,
                    content_snippet=step_snippet,
                )
                output_text = ""
                try:
                    output_text = Path(response_ref).read_text(encoding="utf-8")
                except Exception:  # noqa: BLE001
                    output_text = ""
                if os.environ.get("CONTEXTS_ENABLED", "1") != "0":
                    self._writeback_context(
                        f"{phase}:{step}",
                        output_text,
                        task_id,
                        self.root_dir,
                    )

            if (
                phase == "plan"
                and controller_status != "blocked"
                and int(output.get("step_index", -1)) == len(steps_to_run) - 1
                and normalized_ref
            ):
                plan_artifact_result = self._emit_plan_artifacts(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    normalized_path=Path(normalized_ref),
                )
                if plan_artifact_result.get("blocked"):
                    local_pause_confirm_path = self._write_runtime_pause_confirm(
                        task_id=task_id,
                        phase=phase,
                        step=step,
                        strategy=local_phase_strategy_id,
                        blocked_reason=PLAN_ARTIFACT_INCOMPLETE,
                        artifact_refs={
                            "request": artifact_refs.get("request", ""),
                            "resolvedConfig": artifact_refs.get("resolvedConfig", ""),
                            "routingResult": artifact_refs.get("routingResult", ""),
                            "promptBundle": artifact_refs.get("promptBundle", ""),
                            "manifest": str(manifest_path),
                            "response": response_ref,
                            "validation": validation_ref,
                            "applyResult": apply_result_ref,
                        },
                    )
                    consistency = self.consistency.check(
                        task_id=task_id,
                        phase=phase,
                        step=step,
                        filename=f"artifact-consistency-{phase}-{step}-blocked.json",
                    )
                    local_last_consistency_ref = str(consistency.path)
                    phase_had_blocked_step = True
                    phase_blocked = True
                    break
                local_phase_plan_artifact_refs = plan_artifact_result
                self.task_runner.sync_manifest_snapshot(
                    task_id,
                    artifact_refs=local_phase_plan_artifact_refs,
                    plan_artifact_refs=local_phase_plan_artifact_refs,
                )

            if controller_status == "blocked":
                local_pause_confirm_path = self._write_runtime_pause_confirm(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    strategy=local_phase_strategy_id,
                    blocked_reason=blocked_reason or "parallel_step_blocked",
                    artifact_refs={
                        "request": artifact_refs.get("request", ""),
                        "resolvedConfig": artifact_refs.get("resolvedConfig", ""),
                        "routingResult": artifact_refs.get("routingResult", ""),
                        "promptBundle": artifact_refs.get("promptBundle", ""),
                        "manifest": str(manifest_path),
                        "response": response_ref,
                        "validation": validation_ref,
                        "applyResult": apply_result_ref,
                    },
                )
                phase_had_blocked_step = True
                phase_blocked = True
                break

        return {
            "run_index": local_run_index,
            "phase_strategy_id": local_phase_strategy_id,
            "strategy_switch_ref": local_strategy_switch_ref,
            "last_consistency_ref": local_last_consistency_ref,
            "prior_step_outputs": local_prior_step_outputs,
            "phase_plan_artifact_refs": local_phase_plan_artifact_refs,
            "pause_confirm_path": local_pause_confirm_path,
            "phase_had_blocked_step": phase_had_blocked_step,
            "phase_blocked": phase_blocked,
        }

    def _materialize_phase_inputs(
        self,
        *,
        task_id: str,
        request: dict[str, Any],
        resolved_config: dict[str, Any],
        routing_result: dict[str, Any],
        phase: str,
        step: str,
        step_def: dict[str, Any] | None = None,
        is_first_step: bool = False,
        prior_step_outputs: list[dict[str, str]] | None = None,
    ) -> dict[str, str]:
        effective_request = self._request_with_prior_step_outputs(
            request=request, prior_step_outputs=prior_step_outputs or []
        )
        effective_resolved_config = dict(resolved_config)
        existing_step_config = effective_resolved_config.get("step", {})
        if not isinstance(existing_step_config, dict):
            existing_step_config = {}
        effective_resolved_config["step"] = {
            **existing_step_config,
            "mutationAuthority": (
                step_def.get("mutationAuthority", "") if step_def else ""
            ),
        }
        request_filename = (
            f"request-{phase}.json" if is_first_step else f"request-{phase}-{step}.json"
        )
        request_record = self.store.write_json_artifact(
            task_id=task_id,
            family="requests",
            artifact_type="phase_request",
            payload=effective_request,
            filename=request_filename,
            phase=phase,
            step=step,
        )
        resolved_filename = (
            f"resolved-config-{phase}.json"
            if is_first_step
            else f"resolved-config-{phase}-{step}.json"
        )
        resolved_record = self.store.write_json_artifact(
            task_id=task_id,
            family="resolved-config",
            artifact_type="resolved_config",
            payload=effective_resolved_config,
            filename=resolved_filename,
            phase=phase,
            step=step,
        )
        routing_filename = (
            f"routing-result-{phase}.json"
            if is_first_step
            else f"routing-result-{phase}-{step}.json"
        )
        routing_record = self.store.write_json_artifact(
            task_id=task_id,
            family="routing",
            artifact_type="routing_result",
            payload=routing_result,
            filename=routing_filename,
            phase=phase,
            step=step,
        )
        prompt_bundle = assemble_prompt_bundle(
            request=effective_request,
            resolved_config=effective_resolved_config,
            routing_result=routing_result,
            summary_input_refs=[
                str(request_record.path),
                str(resolved_record.path),
                str(routing_record.path),
            ],
            step_id=step,
        )
        prompt_record = self.store.write_json_artifact(
            task_id=task_id,
            family="prompts",
            artifact_type="prompt_bundle",
            payload=prompt_bundle,
            filename=(
                f"prompt-bundle-{phase}.json"
                if is_first_step
                else f"prompt-bundle-{phase}-{step}.json"
            ),
            phase=phase,
            step=step,
        )
        return {
            "request": str(request_record.path),
            "resolvedConfig": str(resolved_record.path),
            "routingResult": str(routing_record.path),
            "promptBundle": str(prompt_record.path),
        }

    def _emit_plan_artifacts(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        normalized_path: Path,
    ) -> dict[str, Any]:
        try:
            normalized_payload = json.loads(normalized_path.read_text(encoding="utf-8"))
        except Exception:
            normalized_payload = {}

        plan, checklist, deferred = extract_plan_artifacts(
            task_id=task_id,
            step_id=step,
            normalized=normalized_payload,
        )
        valid, failures = validate_plan_artifacts(plan, checklist, deferred)
        if not valid:
            controller_path = (
                task_state_dir(self.root_dir, task_id) / "controller-state.json"
            )
            controller_state = self._load_json(controller_path)
            if controller_state.get("current_status") != "running":
                cursor_path = (
                    task_state_dir(self.root_dir, task_id) / "resume-cursor.json"
                )
                resume_cursor = (
                    self._load_json(cursor_path) if cursor_path.exists() else {}
                )
                self.task_runner.start_phase(
                    task_id=task_id,
                    phase=phase,
                    step=step,
                    strategy=str(controller_state.get("active_strategy", "")),
                    attempt=int(resume_cursor.get("attempt", 1)),
                    run=int(resume_cursor.get("run", 1)),
                )
            self.task_runner.pause_step(
                task_id=task_id,
                phase=phase,
                step=step,
                reason=PLAN_ARTIFACT_INCOMPLETE,
                resume_from=step,
            )
            return {
                "plan": None,
                "checklist": None,
                "deferred": None,
                "blocked": True,
                "failures": failures,
            }

        plan_record = self.store.write_json_artifact(
            task_id=task_id,
            family="plans",
            artifact_type="plan-artifact",
            payload=plan,
            filename=f"plan-{phase}-{step}.json",
            phase=phase,
            step=step,
        )
        checklist_record = self.store.write_json_artifact(
            task_id=task_id,
            family="checklists",
            artifact_type="checklist",
            payload=checklist,
            filename=f"checklist-{phase}-{step}.json",
            phase=phase,
            step=step,
        )
        deferred_ref = ""
        if deferred is not None:
            deferred_record = self.store.write_json_artifact(
                task_id=task_id,
                family="deferred-items",
                artifact_type="deferred-items",
                payload=deferred,
                filename=f"deferred-{phase}-{step}.json",
                phase=phase,
                step=step,
            )
            deferred_ref = str(deferred_record.path)

        return {
            "planRef": str(plan_record.path),
            "checklistRef": str(checklist_record.path),
            "deferredItemsRef": deferred_ref,
        }

    def _write_strategy_override_block(
        self,
        *,
        task_id: str,
        request: dict[str, Any],
        resolved_config: dict[str, Any],
        routing_result: dict[str, Any],
        request_path: Path,
        manifest_path: Path,
    ) -> tuple[Path, Path]:
        phase = resolved_config["phase"]
        step = self._resolve_step(request, resolved_config)
        reason_code = "strategy_override_unavailable"
        payload = {
            "schemaVersion": "1.0.0",
            "taskId": task_id,
            "decisionType": "strategy_override",
            "requestedStrategy": request.get("selectors", {}).get("strategy", ""),
            "selectedStrategy": resolved_config["strategy"]["selectedStrategyId"],
            "phase": phase,
            "step": step,
            "outcome": "blocked",
            "reasonCode": reason_code,
            "routingReasonCodes": routing_result.get("reasonCodes", []),
        }
        decision_record = self.store.write_json_artifact(
            task_id=task_id,
            family="option-decisions",
            artifact_type="option_decision",
            payload=payload,
            filename=f"strategy-override-{phase}.json",
            phase=phase,
            step=step,
        )
        self.task_runner.decisions.append(
            task_id=task_id,
            decision_type="strategy_override",
            phase=phase,
            step=step,
            outcome="blocked",
            payload=payload,
        )
        self.task_runner.pause_step(
            task_id=task_id,
            phase=phase,
            step=step,
            reason="strategy_override_conflict",
            resume_from=step,
        )
        pause_confirm_path = self._write_runtime_pause_confirm(
            task_id=task_id,
            phase=phase,
            step=step,
            strategy=resolved_config["strategy"]["selectedStrategyId"],
            blocked_reason="strategy_override_conflict",
            artifact_refs={
                "request": str(request_path),
                "resolvedConfig": "",
                "routingResult": "",
                "promptBundle": "",
                "manifest": str(manifest_path),
                "response": "",
                "validation": "",
                "applyResult": "",
            },
        )
        return decision_record.path, pause_confirm_path

    def _write_runtime_pause_confirm(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        strategy: str,
        blocked_reason: str,
        artifact_refs: dict[str, str],
    ) -> Path:
        payload = build_runtime_pause_confirm(
            task_id=task_id,
            phase=phase,
            step=step,
            strategy=strategy,
            blocked_reason=blocked_reason,
            reason_code=blocked_reason,
            artifact_refs=artifact_refs,
            severity="high" if "approval" in blocked_reason else "medium",
        )
        pause_record = self.store.write_json_artifact(
            task_id=task_id,
            family="pause-confirm",
            artifact_type="pause_confirm",
            payload=payload,
            filename=f"pause-confirm-{phase}-{step}.json",
            phase=phase,
            step=step,
        )
        self.store.write_text_artifact(
            task_id=task_id,
            family="summaries",
            filename=f"pause-confirm-{phase}-{step}.md",
            content=render_markdown_document(
                title="Pause Confirm",
                payload=payload,
            ),
        )
        self._attach_pause_confirm_to_manifest(
            task_id=task_id, pause_confirm_path=pause_record.path
        )
        return pause_record.path

    def _write_phase_run_artifact(
        self,
        *,
        task_id: str,
        phase_run_path: Path,
        payload: dict[str, Any],
    ) -> Path:
        record = self.store.write_json_artifact(
            task_id=task_id,
            family="phase-runs",
            artifact_type="phase_run",
            payload=payload,
            filename=phase_run_path.name,
            phase=payload.get("requestedPhase", "unknown"),
            step="phase-run",
        )
        return record.path

    def _write_strategy_switch_artifact(
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
        self.task_runner.decisions.append(
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

    def _compose_phases(self, resolved_config: dict[str, Any]) -> list[str]:
        phase = resolved_config["phase"]
        phases = [phase]
        if phase == "review" and resolved_config.get("phaseOptions", {}).get(
            "withHarden"
        ):
            composition = resolved_config.get("phaseConfig", {}).get("composition", {})
            with_harden = composition.get("withHarden", {})
            if with_harden.get("enabled") and with_harden.get("followOnPhase"):
                phases.append(with_harden["followOnPhase"])
        return phases

    def _next_phase(self, current_phase: str) -> str | None:
        sequence = ["plan", "impl", "review", "harden"]
        try:
            index = sequence.index(current_phase)
        except ValueError:
            return None
        next_index = index + 1
        if next_index >= len(sequence):
            return None
        return sequence[next_index]

    def _auto_advance_enabled(
        self, *, request: dict[str, Any], resolved_config: dict[str, Any]
    ) -> bool:
        if request.get("auto_advance") is True:
            return True
        return bool(
            resolved_config.get("phaseOptions", {}).get("autoAdvance", False)
            or request.get("phase_options", {}).get("auto_advance", False)
        )

    def _can_auto_advance(
        self,
        *,
        root_dir: Path,
        request: dict[str, Any],
        phase: str,
        previous_phase_record: dict[str, Any],
    ) -> bool:
        next_request = self._phase_request(
            request,
            phase=phase,
            previous_phase_record=previous_phase_record,
        )
        next_resolution = resolve_runtime_config(
            root_dir=root_dir, request=next_request
        )
        return not self._has_auto_advance_stop_signal(next_resolution.routing_result)

    def _has_auto_advance_stop_signal(self, routing_result: dict[str, Any]) -> bool:
        if routing_result.get("requiresHumanConfirm"):
            return True
        reason_codes = {str(code) for code in routing_result.get("reasonCodes", [])}
        return bool(reason_codes.intersection(AUTO_ADVANCE_STOP_CODES))

    def _phase_request(
        self,
        request: dict[str, Any],
        *,
        phase: str,
        previous_phase_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        phase_request = json.loads(json.dumps(request))
        phase_request.setdefault("selectors", {})
        phase_request["selectors"]["phase"] = phase
        original_phase = request.get("selectors", {}).get(
            "phase", request.get("workflow_intent")
        )
        if phase != original_phase:
            phase_request["selectors"].pop("step", None)
            phase_request["selectors"].pop("strategy", None)
        if phase != "review":
            phase_request.setdefault("phase_options", {})
            phase_request["phase_options"]["with_harden"] = False
        if phase == "harden":
            phase_request["workflow_intent"] = "harden"
        prior_phase_output = self._build_prior_phase_output(previous_phase_record)
        if prior_phase_output:
            operator_context = phase_request.setdefault("operator_context", {})
            if not isinstance(operator_context, dict):
                operator_context = {}
                phase_request["operator_context"] = operator_context
            existing_outputs = self._extract_prior_phase_outputs(phase_request)
            existing_outputs.append(prior_phase_output)
            operator_context["prior_phase_outputs"] = existing_outputs
        return phase_request

    def _build_prior_phase_output(
        self, previous_phase_record: dict[str, Any] | None
    ) -> dict[str, str] | None:
        if not isinstance(previous_phase_record, dict):
            return None

        phase_name = self._safe_text(previous_phase_record.get("phase")) or "unknown"
        step_records = previous_phase_record.get("stepRecords")

        if not isinstance(step_records, list) or not step_records:
            response_ref = self._safe_text(previous_phase_record.get("responseRef"))
            if not response_ref:
                return None
            summary, snippet = self._extract_response_context(
                response_path=Path(response_ref),
                raw_output_path=None,
            )
            snippet = self._truncate_text(
                snippet or summary, _PRIOR_PHASE_SNIPPET_LIMIT
            )
            if not summary and not snippet:
                return None
            return {"phase": phase_name, "summary": summary, "content_snippet": snippet}

        full_summary: list[str] = []
        full_snippet: list[str] = []
        for record in step_records:
            if not isinstance(record, dict):
                continue
            response_ref_str = self._safe_text(record.get("responseRef"))
            if not response_ref_str:
                continue

            raw_output_path = None
            response_path = Path(response_ref_str)
            if response_path.is_file():
                try:
                    envelope = self._load_json(response_path)
                    payload = envelope.get("payload", envelope)
                    if isinstance(payload, dict):
                        raw_ref = payload.get("raw_output_ref")
                        if isinstance(raw_ref, str) and Path(raw_ref).is_file():
                            raw_output_path = Path(raw_ref)
                except (OSError, ValueError):
                    pass

            summary, snippet = self._extract_response_context(
                response_path=response_path,
                raw_output_path=raw_output_path,
            )
            step_id = self._safe_text(record.get("step"))
            if summary:
                full_summary.append(f"Step `{step_id}`: {summary}")
            if snippet:
                full_snippet.append(f"### From Step `{step_id}`\n\n{snippet}")

        final_summary = " ".join(full_summary)
        final_snippet = "\n\n---\n\n".join(full_snippet)
        if not final_summary and not final_snippet:
            return None

        return {
            "phase": phase_name,
            "summary": self._truncate_text(final_summary, 800),
            "content_snippet": self._truncate_text(
                final_snippet, _PRIOR_PHASE_SNIPPET_LIMIT
            ),
        }

    def _extract_response_context(
        self,
        *,
        response_path: Path,
        raw_output_path: Path | None,
    ) -> tuple[str, str]:
        response_payload: dict[str, Any] = {}
        parsed_envelope: dict[str, Any] = {}
        if response_path.exists():
            try:
                envelope = self._load_json(response_path)
                parsed_candidate = envelope.get("parsedEnvelope")
                if isinstance(parsed_candidate, dict):
                    parsed_envelope = parsed_candidate
                payload = envelope.get("payload", envelope)
                if isinstance(payload, dict):
                    response_payload = payload
                    nested_parsed_candidate = payload.get("parsedEnvelope")
                    if isinstance(nested_parsed_candidate, dict):
                        parsed_envelope = nested_parsed_candidate
            except (OSError, ValueError, TypeError):
                response_payload = {}
                parsed_envelope = {}
        summary = self._safe_text(response_payload.get("summary")) or self._safe_text(
            parsed_envelope.get("summary")
        )
        snippet = ""

        if raw_output_path and raw_output_path.exists():
            snippet = self._read_text(raw_output_path)
        else:
            raw_output_ref = self._safe_text(
                response_payload.get("raw_output_ref")
            ) or self._safe_text(parsed_envelope.get("raw_output_ref"))
            if raw_output_ref:
                snippet = self._read_text(Path(raw_output_ref))

        if not snippet:
            payload = response_payload.get("payload")
            if payload is None:
                payload = parsed_envelope.get("payload")
            if isinstance(payload, str):
                snippet = payload.strip()
            elif isinstance(payload, dict):
                snippet = self._safe_text(payload.get("summary"))
                if not snippet:
                    try:
                        snippet = json.dumps(payload, ensure_ascii=True)
                    except (TypeError, ValueError):
                        snippet = ""
            elif isinstance(payload, list):
                try:
                    snippet = json.dumps(payload, ensure_ascii=True)
                except (TypeError, ValueError):
                    snippet = ""

        snippet = snippet.strip()
        if not summary and snippet:
            summary = self._truncate_text(snippet.replace("\n", " "), 240)
        return summary, snippet

    def _request_with_prior_step_outputs(
        self,
        *,
        request: dict[str, Any],
        prior_step_outputs: list[dict[str, str]],
    ) -> dict[str, Any]:
        if not prior_step_outputs:
            return request
        phase_request = json.loads(json.dumps(request))
        operator_context = phase_request.setdefault("operator_context", {})
        if not isinstance(operator_context, dict):
            operator_context = {}
            phase_request["operator_context"] = operator_context
        operator_context["prior_step_outputs"] = [
            {
                "step": item.get("step", ""),
                "summary": item.get("summary", ""),
                "content_snippet": self._truncate_text(
                    item.get("content_snippet", ""),
                    _PRIOR_STEP_SNIPPET_LIMIT,
                ),
            }
            for item in prior_step_outputs
            if item.get("step") or item.get("summary") or item.get("content_snippet")
        ]
        return phase_request

    def _extract_prior_phase_outputs(
        self, request: dict[str, Any]
    ) -> list[dict[str, str]]:
        operator_context = request.get("operator_context")
        if not isinstance(operator_context, dict):
            return []
        outputs = operator_context.get("prior_phase_outputs")
        if not isinstance(outputs, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in outputs:
            if not isinstance(item, dict):
                continue
            phase = self._safe_text(item.get("phase"))
            summary = self._safe_text(item.get("summary"))
            snippet = self._truncate_text(
                self._safe_text(item.get("content_snippet")),
                _PRIOR_PHASE_SNIPPET_LIMIT,
            )
            if not phase and not summary and not snippet:
                continue
            normalized.append(
                {
                    "phase": phase or "unknown",
                    "summary": summary,
                    "content_snippet": snippet or summary,
                }
            )
        return normalized

    def _extract_prior_step_outputs(
        self, request: dict[str, Any]
    ) -> list[dict[str, str]]:
        operator_context = request.get("operator_context")
        if not isinstance(operator_context, dict):
            return []
        outputs = operator_context.get("prior_step_outputs")
        if not isinstance(outputs, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in outputs:
            if not isinstance(item, dict):
                continue
            step = self._safe_text(item.get("step"))
            summary = self._safe_text(item.get("summary"))
            snippet = self._truncate_text(
                self._safe_text(item.get("content_snippet")),
                _PRIOR_STEP_SNIPPET_LIMIT,
            )
            if not step and not summary and not snippet:
                continue
            normalized.append(
                {
                    "step": step,
                    "summary": summary,
                    "content_snippet": snippet or summary,
                }
            )
        return normalized

    def _append_prior_step_output(
        self,
        current_outputs: list[dict[str, str]],
        *,
        step: str,
        summary: str,
        content_snippet: str,
    ) -> list[dict[str, str]]:
        updated_outputs = [dict(item) for item in current_outputs]
        snippet = self._truncate_text(
            content_snippet or summary, _PRIOR_STEP_SNIPPET_LIMIT
        )
        if not summary and not snippet:
            return updated_outputs
        updated_outputs.append(
            {
                "step": step,
                "summary": summary,
                "content_snippet": snippet,
            }
        )
        return updated_outputs

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _safe_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        return ""

    def _truncate_text(self, text: str, max_chars: int) -> str:
        content = text.strip()
        if len(content) <= max_chars:
            return content
        clipped = content[:max_chars].rstrip()
        last_break = max(
            clipped.rfind(" "),
            clipped.rfind("\n"),
            clipped.rfind("\t"),
            clipped.rfind("\r"),
        )
        if last_break > 0:
            clipped = clipped[:last_break].rstrip()
        return f"{clipped} [TRUNCATED]"

    def _resolve_step(
        self, request: dict[str, Any], resolved_config: dict[str, Any]
    ) -> str:
        selector_phase = request.get("selectors", {}).get("phase")
        selector_step = request.get("selectors", {}).get("step")
        if selector_step and (
            not selector_phase or selector_phase == resolved_config["phase"]
        ):
            return selector_step
        steps = resolved_config.get("strategy", {}).get("steps", [])
        if steps:
            return steps[0].get("id", "execute")
        return "execute"

    def _should_block_for_task_ambiguity(
        self, *, request: dict[str, Any], routing_result: dict[str, Any]
    ) -> bool:
        if self._has_task_clarification(request):
            return False
        ambiguity_level = str(request.get("ambiguity_level", "")).strip().lower()
        reason_codes = {
            str(code).strip().lower() for code in routing_result.get("reasonCodes", [])
        }
        ambiguity_in_reason = any("ambigu" in code for code in reason_codes)
        return ambiguity_level == "high" or (
            ambiguity_in_reason and ambiguity_level in {"", "high"}
        )

    def _has_task_clarification(self, request: dict[str, Any]) -> bool:
        explicit = str(request.get("clarification", "")).strip()
        if explicit:
            return True
        operator_context = request.get("operator_context")
        if isinstance(operator_context, dict):
            clarification = str(operator_context.get("clarification", "")).strip()
            if clarification:
                return True
        return bool(request.get("clarification_provided"))

    def _has_budget_confirmation(
        self, *, task_id: str, strategy_id: str | None
    ) -> bool:
        # Conservative fail-closed default until explicit budget approvals are modeled.
        _ = (task_id, strategy_id)
        return False

    def _load_review_gate_result(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        attempt: int,
        run: int,
        normalized_path: Path,
    ) -> ReviewGateResult | None:
        gate_result: ReviewGateResult | None = None
        try:
            gate_result = evaluate_review_gate(self._load_json(normalized_path))
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to evaluate review gate from normalized artifact",
                extra={
                    "task_id": task_id,
                    "phase": phase,
                    "step": step,
                    "path": str(normalized_path),
                },
            )

        gate_artifact_path = (
            self.store.task_root(task_id)
            / "findings"
            / f"findings-gate-{phase}-{step}-{attempt}-{run}.json"
        )
        if not gate_artifact_path.exists():
            return gate_result

        try:
            gate_data = self._load_json(gate_artifact_path)
            gate_payload = gate_data.get("payload", gate_data)
            blocking_found = bool(gate_payload.get("blocking_found", False))
            findings = gate_payload.get("findings", [])
            if not isinstance(findings, list):
                findings = []
            summary = gate_payload.get("findings_summary", {})
            if not isinstance(summary, dict):
                summary = {}
            fixable_operations = gate_payload.get("fixable_operations", [])
            if not isinstance(fixable_operations, list):
                try:
                    fixable_count = int(gate_payload.get("fixable_operations_count", 0))
                except (TypeError, ValueError):
                    fixable_count = 0
                fixable_operations = [
                    {"operation_id": f"fix-{index + 1}"}
                    for index in range(max(0, fixable_count))
                ]
            fallback = ReviewGateResult(
                can_complete=bool(gate_payload.get("can_complete", not blocking_found)),
                blocking_found=blocking_found,
                fixable_operations=fixable_operations,
                findings=findings,
                summary=summary,
                blocked_reason="review_blocking_findings" if blocking_found else "",
            )
            if gate_result is None:
                return fallback
            if blocking_found and (
                not gate_result.blocking_found
                or len(fallback.fixable_operations)
                > len(gate_result.fixable_operations)
                or (not gate_result.findings and bool(fallback.findings))
            ):
                return fallback
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to parse findings gate artifact; ignoring fallback",
                extra={
                    "task_id": task_id,
                    "phase": phase,
                    "step": step,
                    "path": str(gate_artifact_path),
                },
            )

        return gate_result

    def _write_loop_state_record(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        strategy_id: str,
        current_iteration: int,
        max_loops: int,
        status: str,
        blockers_remaining: int = 0,
        blockers_resolved: int = 0,
        fix_operations_applied: int = 0,
    ) -> Path:
        record = self.store.write_json_artifact(
            task_id=task_id,
            family="loop-state",
            artifact_type="loop_state",
            payload=build_loop_state_artifact(
                task_id=task_id,
                phase=phase,
                strategy_id=strategy_id,
                current_iteration=current_iteration,
                max_loops=max_loops,
                status=status,
                blockers_resolved=blockers_resolved,
                blockers_remaining=blockers_remaining,
                fix_operations_applied=fix_operations_applied,
            ),
            filename=f"loop-state-{phase}-{step}-iter{current_iteration}.json",
            phase=phase,
            step=step,
        )
        return record.path

    def _pause_review_loop_step(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        strategy: str,
        reason: str,
        artifact_refs: dict[str, str],
        attempt: int,
        run: int,
    ) -> tuple[Path, str]:
        controller_state = self._load_json(
            task_state_dir(self.root_dir, task_id) / "controller-state.json"
        )
        current_status = str(controller_state.get("current_status", ""))
        current_reason = str(controller_state.get("blocked_reason", ""))
        if current_status != "running" and current_reason != reason:
            self.task_runner.start_phase(
                task_id=task_id,
                phase=phase,
                step=step,
                strategy=strategy,
                attempt=attempt,
                run=run,
            )
            current_status = "running"
        if current_status == "running":
            self.task_runner.pause_step(
                task_id=task_id,
                phase=phase,
                step=step,
                reason=reason,
                resume_from=step,
            )
        pause_confirm_path = self._write_runtime_pause_confirm(
            task_id=task_id,
            phase=phase,
            step=step,
            strategy=strategy,
            blocked_reason=reason,
            artifact_refs=artifact_refs,
        )
        consistency = self.consistency.check(
            task_id=task_id,
            phase=phase,
            step=step,
            filename=f"artifact-consistency-{phase}-{step}-blocked.json",
        )
        last_consistency_ref = str(consistency.path)
        if self._consistency_failed(consistency):
            pause_confirm_path = self._write_runtime_pause_confirm(
                task_id=task_id,
                phase=phase,
                step=step,
                strategy=strategy,
                blocked_reason="artifact_consistency_failure",
                artifact_refs=artifact_refs,
            )
        return pause_confirm_path, last_consistency_ref

    def _consistency_failed(self, consistency: Any) -> bool:
        payload = {}
        if hasattr(consistency, "payload") and isinstance(consistency.payload, dict):
            payload = consistency.payload
        status = str(payload.get("status", "")).strip().lower()
        if not status and hasattr(consistency, "path"):
            try:
                envelope = json.loads(consistency.path.read_text(encoding="utf-8"))
                parsed_payload = envelope.get("payload", envelope)
                if isinstance(parsed_payload, dict):
                    status = str(parsed_payload.get("status", "")).strip().lower()
            except Exception:  # noqa: BLE001
                return True
        return status == "failed"

    def _coordination_blocked_reason(self, coordination: Any) -> str:
        blocked_reason = str(getattr(coordination, "blocked_reason", "")).strip()
        if not blocked_reason:
            blocked_reason = str(
                (getattr(coordination, "apply_result", {}) or {}).get("result", "")
            ).strip()
        if self._is_missing_tool_or_auth_reason(blocked_reason):
            return "missing_tool_or_auth"
        return blocked_reason or "blocked"

    def _is_missing_tool_or_auth_reason(self, reason: str) -> bool:
        normalized = reason.strip().lower()
        return any(
            token in normalized
            for token in (
                "missing_binary",
                "binary_not_found",
                "auth_failed",
                "tool_not_found",
                "missing_tool_or_auth",
            )
        )

    def _exception_indicates_missing_tool_or_auth(self, exc: Exception) -> bool:
        message = str(exc).strip().lower()
        return any(
            token in message
            for token in (
                "unsupported provider adapter",
                "command not found",
                "binary not found",
                "tool not found",
                "auth failed",
                "authentication",
            )
        )

    def _check_step_output_contract(
        self,
        *,
        task_root: Path,
        step_def: dict[str, Any],
        step_record: dict[str, Any],
    ) -> tuple[bool, str]:
        try:
            return check_output_contract(
                task_root=task_root,
                step_def=step_def,
                step_record=step_record,
            )
        except Exception:  # noqa: BLE001
            logger.exception("step output contract check failed; treating as ok")
            return True, ""

    def _load_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_execution_counter_seed(self, task_id: str) -> dict[str, Any]:
        cursor_path = task_state_dir(self.root_dir, task_id) / "resume-cursor.json"
        if not cursor_path.exists():
            return {}
        return self._load_json(cursor_path)

    def _resolve_execution_counters(
        self,
        *,
        counter_seed: dict[str, Any],
        phase: str,
        step: str,
        run_index: int,
    ) -> tuple[int, int]:
        base_run = int(counter_seed.get("run", 1))
        base_attempt = int(counter_seed.get("attempt", 1))
        attempt = (
            base_attempt + 1
            if counter_seed.get("phase") == phase and counter_seed.get("step") == step
            else 1
        )
        return attempt, base_run + run_index

    def _attach_pause_confirm_to_manifest(
        self, *, task_id: str, pause_confirm_path: Path
    ) -> None:
        manifest_path = (
            task_artifacts_dir(self.root_dir, task_id) / "manifests" / "manifest.json"
        )
        if not manifest_path.exists():
            return
        envelope = self._load_json(manifest_path)
        blocker_refs = list(envelope.get("payload", envelope).get("blockerRefs", []))
        blocker_refs.append(str(pause_confirm_path))
        self.task_runner.sync_manifest_snapshot(
            task_id,
            blocker_refs=list(dict.fromkeys(blocker_refs)),
            artifact_refs={"pauseConfirm": str(pause_confirm_path)},
        )
