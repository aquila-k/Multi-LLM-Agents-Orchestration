from __future__ import annotations

import json
from pathlib import Path

from agentorch_ctx.interfaces.skill_entry import DispatchResult
from agentorch_ctx.runtime.preflight import PreflightResult


def render_dispatch_summary(
    *,
    dispatch_result: DispatchResult,
    preflight_result: PreflightResult,
) -> str:
    controller_state = json.loads(
        dispatch_result.controller_state_path.read_text(encoding="utf-8")
    )
    task_root = dispatch_result.request_path.parents[1]
    resolved_config_path = task_root / "resolved-config" / "resolved-config-intake.json"
    routing_result_path = task_root / "routing" / "routing-result-intake.json"
    summary_path = task_root / "summaries" / "intake-summary.md"
    preflight_suffix = _render_preflight_suffix(preflight_result)

    lines = [
        f"status: {'blocked' if dispatch_result.stop_and_confirm else 'ready'}",
        (
            "task: "
            f"{dispatch_result.task_id} phase={controller_state['active_phase']} "
            f"strategy={controller_state['active_strategy']}"
        ),
    ]
    blocked_reason = controller_state.get("blocked_reason", "")
    if blocked_reason:
        lines.append(f"stop_reason: {blocked_reason}")
    lines.extend(
        [
            f"artifacts: request={dispatch_result.request_path}",
            f"artifacts: state={dispatch_result.controller_state_path}",
            f"artifacts: resolved_config={resolved_config_path}",
            f"artifacts: routing={routing_result_path}",
            f"artifacts: summary={summary_path}",
        ]
    )
    if preflight_suffix:
        lines.append(preflight_suffix)
    return "\n".join(lines)


def _render_preflight_suffix(preflight_result: PreflightResult) -> str:
    if not preflight_result.missing_providers:
        return "preflight: provider_commands=all_detected"
    missing = ",".join(preflight_result.missing_providers)
    return f"preflight: missing_provider_commands={missing} stub_safe=true"
