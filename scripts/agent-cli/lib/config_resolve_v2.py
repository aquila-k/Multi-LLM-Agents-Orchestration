#!/usr/bin/env python3
"""Resolve effective Config V2 values for a phase/method/step."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from config_validate_v2 import (  # type: ignore
    PHASES,
    TOOL_WEB_MODE_MAP,
    TOOLS,
    ValidationError,
    load_and_validate_v2_config,
    load_manifest_if_present,
    parse_manifest_v2_overrides,
)


def _resolve_selected_method(
    cfg: Dict[str, Any],
    phase: str,
    manifest_override: Dict[str, Any],
    runtime_method_id: Optional[str],
) -> str:
    phase_cfg = cfg["skills"][phase]

    default_method_ids = phase_cfg.get("default_method_ids") or []
    if not default_method_ids:
        raise ValidationError(f"skills.{phase}.default_method_ids must not be empty")

    selected = default_method_ids[0]

    manifest_method_id = manifest_override.get("method_id")
    if manifest_method_id:
        selected = manifest_method_id

    if runtime_method_id:
        selected = runtime_method_id

    methods = phase_cfg["methods"]
    if selected not in methods:
        raise ValidationError(
            f"resolved method_id '{selected}' is not defined in skills.{phase}.methods"
        )

    if not methods[selected].get("enabled", False):
        raise ValidationError(f"resolved method_id '{selected}' is disabled")

    return selected


def _resolve_step(
    cfg: Dict[str, Any],
    phase: str,
    method_node: Dict[str, Any],
    step_id: str,
    phase_override: Dict[str, Any],
) -> Dict[str, Any]:
    step_defaults = cfg["skills"][phase]["step_defaults"]
    base_step = dict(step_defaults[step_id])
    step_override = dict(
        (phase_override.get("step_overrides") or {}).get(step_id) or {}
    )

    tool = step_override.get("tool") or base_step["default_tool"]
    default_mode = step_override.get("default_mode") or base_step["default_mode"]
    web_research_mode = (
        step_override.get("web_research_mode") or base_step["web_research_mode"]
    )

    if web_research_mode != "off" and web_research_mode not in TOOL_WEB_MODE_MAP[tool]:
        raise ValidationError(
            f"step '{step_id}' web_research_mode '{web_research_mode}' is not compatible with tool '{tool}'"
        )

    model = cfg["servants"][tool]["default_model"]

    phase_tool_models = phase_override.get("tool_models") or {}
    if tool in phase_tool_models:
        model = phase_tool_models[tool]

    if "model" in step_override:
        model = step_override["model"]

    allowed_models = cfg["servants"][tool]["allowed_models"]
    if model not in allowed_models:
        raise ValidationError(
            f"step '{step_id}' resolved model '{model}' is not allowed for tool '{tool}'"
        )

    return {
        "tool": tool,
        "model": model,
        "default_mode": default_mode,
        "web_research_mode": web_research_mode,
    }


def resolve_v2(
    cfg: Dict[str, Any],
    phase: str,
    manifest_overrides: Dict[str, Any],
    method_id: Optional[str],
    step_id: Optional[str],
) -> Dict[str, Any]:
    phase_override = dict(
        (manifest_overrides.get("phase_overrides") or {}).get(phase) or {}
    )
    selected_method_id = _resolve_selected_method(cfg, phase, phase_override, method_id)

    method_node = cfg["skills"][phase]["methods"][selected_method_id]
    resolved_steps = list(method_node.get("steps") or [])
    if not resolved_steps:
        raise ValidationError(f"resolved method '{selected_method_id}' has no steps")

    if step_id:
        if step_id not in resolved_steps:
            raise ValidationError(
                f"step_id '{step_id}' is not part of resolved method '{selected_method_id}'"
            )
        resolved_steps = [step_id]

    step_map: Dict[str, Dict[str, Any]] = {}
    for sid in resolved_steps:
        step_map[sid] = _resolve_step(cfg, phase, method_node, sid, phase_override)

    return {
        "version": 2,
        "phase": phase,
        "selected_method_id": selected_method_id,
        "resolved_steps": resolved_steps,
        "step_agent_model_map": step_map,
        "applied_overrides": {
            "manifest": {
                "method_id": phase_override.get("method_id"),
                "tool_models": phase_override.get("tool_models") or {},
                "step_overrides": phase_override.get("step_overrides") or {},
            },
            "runtime": {
                "method_id": method_id,
                "step_id": step_id,
            },
        },
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Resolve effective Config V2 values")
    parser.add_argument(
        "--config-root", required=True, help="Path to configs-v2 directory"
    )
    parser.add_argument(
        "--phase",
        required=True,
        choices=PHASES,
        help="Phase to resolve",
    )
    parser.add_argument("--method-id", help="Runtime explicit method_id override")
    parser.add_argument(
        "--step-id", help="Restrict output to a single step from the resolved method"
    )
    parser.add_argument(
        "--manifest", help="Optional task manifest containing config_v2 overrides"
    )
    args = parser.parse_args()

    try:
        cfg = load_and_validate_v2_config(args.config_root)
        manifest = load_manifest_if_present(args.manifest)
        manifest_overrides = parse_manifest_v2_overrides(
            cfg,
            manifest,
            manifest_path=args.manifest or "manifest",
        )
        resolved = resolve_v2(
            cfg=cfg,
            phase=args.phase,
            manifest_overrides=manifest_overrides,
            method_id=args.method_id,
            step_id=args.step_id,
        )
    except ValidationError as e:
        print(f"CONFIG V2 RESOLVE ERROR: {e}", file=sys.stderr)
        return 1

    json.dump(resolved, sys.stdout, indent=2, sort_keys=True)
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
