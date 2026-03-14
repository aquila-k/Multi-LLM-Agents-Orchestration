from __future__ import annotations

from typing import Any

from collab.runtime.prompt_builder import build_prompt


def assemble_prompt_bundle(
    *,
    request: dict[str, Any],
    resolved_config: dict[str, Any],
    routing_result: dict[str, Any],
    summary_input_refs: list[str],
    step_id: str = "",
) -> dict[str, Any]:
    provider_config = resolved_config.get("provider", {})
    effective_output_mode = (
        resolved_config.get("strategy", {}).get("preferredOutputMode", "") or ""
    )
    operator_context = request.get("operator_context", {})
    if not isinstance(operator_context, dict):
        operator_context = {}
    else:
        operator_context = dict(operator_context)
    return {
        "schemaVersion": "1.0.0",
        "taskId": request.get("task_id", ""),
        "phase": resolved_config["phase"],
        "workflowIntent": request.get("workflow_intent", ""),
        "source": request.get("source", {}),
        "summary": request.get("summary", ""),
        "targets": request.get("targets", {}),
        "constraints": request.get("constraints", {}),
        "output": request.get("output", {}),
        "operator_context": operator_context,
        "phaseOptions": request.get("phase_options", {}),
        "selectedStrategyId": resolved_config["strategy"]["selectedStrategyId"],
        "selectedProvider": resolved_config["provider"]["provider"],
        "selectedModel": resolved_config["provider"]["modelRef"],
        "promptText": build_prompt(
            request=request,
            resolved_config=resolved_config,
            step_id=step_id,
            provider=str(provider_config.get("provider", "")),
            model_ref=str(provider_config.get("modelRef", "")),
            effective_output_mode=str(effective_output_mode),
        ),
        "resolvedConfigRef": (
            summary_input_refs[1] if len(summary_input_refs) > 1 else ""
        ),
        "routingResultRef": (
            summary_input_refs[2] if len(summary_input_refs) > 2 else ""
        ),
        "summaryInputRefs": summary_input_refs,
        "dynamicInputs": {
            "taskSignals": resolved_config["signals"],
            "routingReasonCodes": routing_result.get("reasonCodes", []),
            "capabilityRequirements": resolved_config.get("capabilityRequirements", []),
        },
        "storedContextRef": bool(operator_context.get("stored_context")),
    }
