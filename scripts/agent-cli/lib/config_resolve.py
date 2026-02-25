#!/usr/bin/env python3
"""Resolve runtime config from split config files with strict validation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from config_validate import (  # type: ignore
    CODEX_EFFORT_VALUES,
    SERVANT_NAMES,
    TIMEOUT_MODE_VALUES,
    ValidationError,
    load_and_validate_split_config,
    load_manifest_if_present,
    validate_manifest_extensions,
)

DISPATCH_ALLOWED_FLAGS = {
    "impl": {"enable_brief", "enable_verify", "enable_review"},
    "review": {"enable_verify", "enable_review"},
}

PURPOSE_NAMES = {"impl", "review", "verify", "plan", "one_shot"}


def _stage_tool(stage_name: str) -> str:
    if "_" not in stage_name:
        raise ValidationError(f"stage '{stage_name}' must include tool prefix")
    tool = stage_name.split("_", 1)[0]
    if tool not in SERVANT_NAMES:
        raise ValidationError(f"stage '{stage_name}' starts with unknown tool '{tool}'")
    return tool


def _dispatch_stage_purpose(stage: str, pipeline: str, options: Dict[str, Any]) -> str:
    role = stage.split("_", 1)[1] if "_" in stage else stage
    impl_mode = options.get("impl_mode")

    if role in {"impl", "test_impl"}:
        return "impl"
    if role in {"verify", "static_verify"}:
        return "verify"
    if "review" in role:
        return "review"
    if role == "runbook":
        return "one_shot"
    if role in {"brief", "test_design"}:
        if pipeline == "impl" and impl_mode == "one_shot":
            return "one_shot"
        return "plan"
    return "plan" if pipeline == "impl" else "review"


def _plan_stage_purpose(stage: str) -> str:
    if "review" in stage:
        return "review"
    return "plan"


def _find_pipeline_for_profile_name(
    cfg: Dict[str, Any], profile_name: str
) -> Optional[str]:
    for pipeline in ("impl", "review"):
        if profile_name in cfg["pipelines"][pipeline]["profiles"]:
            return pipeline
    return None


def _base_profile_from_intent(cfg: Dict[str, Any], intent: str) -> Tuple[str, str]:
    pipeline = _find_pipeline_for_profile_name(cfg, intent)
    if pipeline is None:
        raise ValidationError(
            f"routing.intent '{intent}' is not defined in pipelines.impl/review"
        )
    return pipeline, intent


def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    out.update(override)
    return out


def _profile_data(cfg: Dict[str, Any], pipeline: str, profile: str) -> Dict[str, Any]:
    profiles = cfg["pipelines"][pipeline]["profiles"]
    if profile not in profiles:
        raise ValidationError(
            f"pipeline '{pipeline}' does not define profile '{profile}'"
        )
    node = profiles[profile]
    return {
        "stages": list(node.get("stages") or []),
        "flags": dict(node.get("flags") or {}),
        "options": dict(node.get("options") or {}),
        "stage_models": dict(node.get("stage_models") or {}),
        "stage_efforts": dict(node.get("stage_efforts") or {}),
    }


def _apply_dispatch_flag_filters(
    stages: List[str], flags: Dict[str, bool]
) -> List[str]:
    out = list(stages)
    if flags.get("enable_brief") is False:
        out = [s for s in out if not s.endswith("_brief")]
    if flags.get("enable_verify") is False:
        out = [s for s in out if "verify" not in s.split("_", 1)[1]]
    if flags.get("enable_review") is False:
        out = [s for s in out if "review" not in s.split("_", 1)[1]]
    return out


def _resolve_tool_models(
    cfg: Dict[str, Any], manifest: Optional[Dict[str, Any]]
) -> Dict[str, str]:
    models: Dict[str, str] = {}
    for tool in SERVANT_NAMES:
        models[tool] = cfg["servants"][tool]["default_model"]

    routing = (manifest or {}).get("routing") or {}
    model_override = routing.get("model") or {}
    if model_override:
        for tool, model in model_override.items():
            models[tool] = model

    return models


def _resolve_purpose_models(cfg: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    purpose_models: Dict[str, Dict[str, str]] = {}
    for tool in SERVANT_NAMES:
        raw = cfg["servants"][tool].get("purpose_models") or {}
        if not isinstance(raw, dict):
            raise ValidationError(f"servants.{tool}.purpose_models must be a mapping")
        allowed = cfg["servants"][tool]["allowed_models"]
        for purpose_name, model in raw.items():
            if purpose_name not in PURPOSE_NAMES:
                raise ValidationError(
                    f"servants.{tool}.purpose_models has unknown key '{purpose_name}'"
                )
            if model not in allowed:
                raise ValidationError(
                    f"servants.{tool}.purpose_models.{purpose_name}='{model}' is not allowed"
                )
        purpose_models[tool] = dict(raw)
    return purpose_models


def _resolve_codex_purpose_efforts(cfg: Dict[str, Any]) -> Dict[str, str]:
    raw = cfg["servants"]["codex"].get("purpose_efforts") or {}
    if not isinstance(raw, dict):
        raise ValidationError("servants.codex.purpose_efforts must be a mapping")
    for purpose_name, effort in raw.items():
        if purpose_name not in PURPOSE_NAMES:
            raise ValidationError(
                f"servants.codex.purpose_efforts has unknown key '{purpose_name}'"
            )
        if effort not in CODEX_EFFORT_VALUES:
            raise ValidationError(
                f"servants.codex.purpose_efforts.{purpose_name}='{effort}' is invalid"
            )
    return dict(raw)


def _resolve_tool_wrapper_defaults(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for tool in SERVANT_NAMES:
        raw = cfg["servants"][tool].get("wrapper_defaults") or {}
        if not isinstance(raw, dict):
            raise ValidationError(f"servants.{tool}.wrapper_defaults must be a mapping")
        out[tool] = dict(raw)
    return out


def resolve_dispatch(
    cfg: Dict[str, Any], manifest: Dict[str, Any], plan_name: str, intent_default: str
) -> Dict[str, Any]:
    routing = manifest.get("routing") or {}
    routing_model_overrides = dict(routing.get("model") or {})
    requested_intent = routing.get("intent") or intent_default
    if plan_name != "auto":
        requested_intent = plan_name

    pipeline, profile_from_intent = _base_profile_from_intent(cfg, requested_intent)

    pipeline_override = routing.get("pipeline") or {}
    profile_override = pipeline_override.get("profile")

    selected_profile = profile_override or profile_from_intent
    profile_runtime = _profile_data(cfg, pipeline, selected_profile)

    flags_override = dict(pipeline_override.get("flags") or {})
    options_override = dict(pipeline_override.get("options") or {})

    runtime_flags = _merge_dict(profile_runtime["flags"], flags_override)
    runtime_options = _merge_dict(profile_runtime["options"], options_override)

    unsupported_flags = sorted(
        set(runtime_flags.keys()) - DISPATCH_ALLOWED_FLAGS[pipeline]
    )
    if unsupported_flags:
        raise ValidationError(
            f"pipeline '{pipeline}' does not support flags: {', '.join(unsupported_flags)}"
        )

    if pipeline == "impl":
        unsupported = sorted(
            set(runtime_options.keys()) - {"impl_mode", "timeout_mode"}
        )
        if unsupported:
            raise ValidationError(
                f"pipeline '{pipeline}' does not support options: {', '.join(unsupported)}"
            )

        impl_mode = runtime_options.get("impl_mode")
        if impl_mode == "safe":
            selected_profile = "safe_impl"
        elif impl_mode == "one_shot":
            selected_profile = "one_shot_impl"

    if pipeline == "review":
        unsupported = sorted(
            set(runtime_options.keys())
            - {"review_mode", "timeout_mode", "security_mode"}
        )
        if unsupported:
            raise ValidationError(
                f"pipeline '{pipeline}' does not support options: {', '.join(unsupported)}"
            )
        review_mode = runtime_options.get("review_mode")
        if review_mode == "codex_only":
            selected_profile = "codex_only"
        elif review_mode == "cross":
            selected_profile = "review_cross"

    if selected_profile != (profile_override or profile_from_intent):
        profile_runtime = _profile_data(cfg, pipeline, selected_profile)
        runtime_flags = _merge_dict(profile_runtime["flags"], flags_override)
        runtime_options = _merge_dict(profile_runtime["options"], options_override)

    stage_plan = _apply_dispatch_flag_filters(profile_runtime["stages"], runtime_flags)
    if not stage_plan:
        raise ValidationError("resolved dispatch stage plan is empty")

    tool_models = _resolve_tool_models(cfg, manifest)
    purpose_models = _resolve_purpose_models(cfg)
    codex_purpose_efforts = _resolve_codex_purpose_efforts(cfg)
    wrapper_defaults = _resolve_tool_wrapper_defaults(cfg)
    timeout_mode_override = runtime_options.get("timeout_mode")
    if (
        timeout_mode_override is not None
        and timeout_mode_override not in TIMEOUT_MODE_VALUES
    ):
        raise ValidationError(
            f"pipeline '{pipeline}' timeout_mode='{timeout_mode_override}' is invalid"
        )

    profile_stage_models = profile_runtime["stage_models"]
    for stage_name, stage_model in profile_stage_models.items():
        tool = _stage_tool(stage_name)
        allowed = cfg["servants"][tool]["allowed_models"]
        if stage_model not in allowed:
            raise ValidationError(
                f"profile '{selected_profile}' stage_models.{stage_name}='{stage_model}' is not allowed for {tool}"
            )

    profile_stage_efforts = profile_runtime["stage_efforts"]
    for stage_name, stage_effort in profile_stage_efforts.items():
        tool = _stage_tool(stage_name)
        if tool != "codex":
            raise ValidationError(
                f"profile '{selected_profile}' stage_efforts.{stage_name} is only supported for codex stages"
            )
        if stage_effort not in CODEX_EFFORT_VALUES:
            raise ValidationError(
                f"profile '{selected_profile}' stage_efforts.{stage_name}='{stage_effort}' is invalid"
            )

    stage_models: Dict[str, str] = {}
    stage_efforts: Dict[str, str] = {}
    stage_timeout_ms: Dict[str, int] = {}
    stage_timeout_modes: Dict[str, str] = {}
    for stage_name in stage_plan:
        tool = _stage_tool(stage_name)
        stage_purpose = _dispatch_stage_purpose(stage_name, pipeline, runtime_options)
        # Task-level model override is the strongest signal for dispatch.
        stage_model = routing_model_overrides.get(tool)
        if stage_model is None:
            stage_model = profile_stage_models.get(stage_name)
            if stage_model is None:
                stage_model = purpose_models.get(tool, {}).get(stage_purpose)
            if stage_model is None:
                stage_model = tool_models[tool]
        stage_models[stage_name] = stage_model

        raw_timeout_ms = wrapper_defaults.get(tool, {}).get("timeout_ms")
        if isinstance(raw_timeout_ms, int) and raw_timeout_ms >= 0:
            stage_timeout_ms[stage_name] = raw_timeout_ms
        else:
            raise ValidationError(
                f"servants.{tool}.wrapper_defaults.timeout_ms must be a non-negative integer"
            )

        stage_timeout_mode = timeout_mode_override or wrapper_defaults.get(
            tool, {}
        ).get("timeout_mode")
        if stage_timeout_mode not in TIMEOUT_MODE_VALUES:
            raise ValidationError(
                f"resolved timeout_mode '{stage_timeout_mode}' is invalid for stage '{stage_name}'"
            )
        stage_timeout_modes[stage_name] = stage_timeout_mode

        if tool == "codex":
            stage_effort = profile_stage_efforts.get(stage_name)
            if stage_effort is None:
                stage_effort = codex_purpose_efforts.get(stage_purpose)
            if stage_effort is None:
                stage_effort = wrapper_defaults.get("codex", {}).get("effort")
            if stage_effort not in CODEX_EFFORT_VALUES:
                raise ValidationError(
                    f"resolved codex effort '{stage_effort}' is invalid for stage '{stage_name}'"
                )
            stage_efforts[stage_name] = stage_effort

    return {
        "pipeline_group": pipeline,
        "intent": requested_intent,
        "profile": selected_profile,
        "flags": runtime_flags,
        "options": runtime_options,
        "stage_plan": stage_plan,
        "tool_models": tool_models,
        "purpose_models": purpose_models,
        "stage_models": stage_models,
        "stage_efforts": stage_efforts,
        "stage_timeout_ms": stage_timeout_ms,
        "stage_timeout_modes": stage_timeout_modes,
    }


def resolve_plan_pipeline(
    cfg: Dict[str, Any],
    profile_override: Optional[str],
    model_overrides: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    plan_cfg = cfg["pipelines"]["plan"]
    profile_name = profile_override or plan_cfg["default_profile"]

    if profile_name not in plan_cfg["profiles"]:
        raise ValidationError(f"plan profile '{profile_name}' is not defined")

    profile = plan_cfg["profiles"][profile_name]
    flags = dict(profile.get("flags") or {})
    options = dict(profile.get("options") or {})
    profile_stage_models = dict(profile.get("stage_models") or {})
    profile_stage_efforts = dict(profile.get("stage_efforts") or {})

    tool_models: Dict[str, str] = {}
    for tool in SERVANT_NAMES:
        tool_models[tool] = cfg["servants"][tool]["default_model"]
    purpose_models = _resolve_purpose_models(cfg)
    codex_purpose_efforts = _resolve_codex_purpose_efforts(cfg)
    wrapper_defaults = _resolve_tool_wrapper_defaults(cfg)
    timeout_mode_override = options.get("timeout_mode")
    if (
        timeout_mode_override is not None
        and timeout_mode_override not in TIMEOUT_MODE_VALUES
    ):
        raise ValidationError(
            f"plan profile '{profile_name}' timeout_mode='{timeout_mode_override}' is invalid"
        )

    for tool, model in model_overrides.items():
        if model is None:
            continue
        allowed = cfg["servants"][tool]["allowed_models"]
        if model not in allowed:
            raise ValidationError(
                f"CLI override model '{model}' is not allowed for {tool}"
            )
        tool_models[tool] = model

    for stage_name, stage_model in profile_stage_models.items():
        try:
            tool = _stage_tool(stage_name)
        except ValidationError:
            raise ValidationError(
                f"plan profile stage_models has unknown key '{stage_name}'"
            )
        allowed = cfg["servants"][tool]["allowed_models"]
        if stage_model not in allowed:
            raise ValidationError(
                f"plan profile '{profile_name}' stage_models.{stage_name}='{stage_model}' is not allowed for {tool}"
            )

    for stage_name, stage_effort in profile_stage_efforts.items():
        try:
            tool = _stage_tool(stage_name)
        except ValidationError:
            raise ValidationError(
                f"plan profile stage_efforts.{stage_name} is only supported for codex stages"
            )
        if tool != "codex":
            raise ValidationError(
                f"plan profile stage_efforts.{stage_name} is only supported for codex stages"
            )
        if stage_effort not in CODEX_EFFORT_VALUES:
            raise ValidationError(
                f"plan profile '{profile_name}' stage_efforts.{stage_name}='{stage_effort}' is invalid"
            )

    stage_order = [
        "copilot_draft",
        "codex_enrich",
        "gemini_enrich",
        "codex_cross_review",
        "gemini_cross_review",
        "copilot_consolidate",
    ]

    stage_models: Dict[str, str] = {}
    stage_efforts: Dict[str, str] = {}
    stage_timeout_ms: Dict[str, int] = {}
    stage_timeout_modes: Dict[str, str] = {}
    for stage_name in stage_order:
        tool = _stage_tool(stage_name)

        # CLI model override is the strongest signal for plan pipeline runs.
        stage_model = model_overrides.get(tool)
        if stage_model is None:
            stage_purpose = _plan_stage_purpose(stage_name)
            stage_model = profile_stage_models.get(stage_name)
            if stage_model is None:
                stage_model = purpose_models.get(tool, {}).get(stage_purpose)
            if stage_model is None:
                stage_model = tool_models[tool]
        stage_models[stage_name] = stage_model

        raw_timeout_ms = wrapper_defaults.get(tool, {}).get("timeout_ms")
        if isinstance(raw_timeout_ms, int) and raw_timeout_ms >= 0:
            stage_timeout_ms[stage_name] = raw_timeout_ms
        else:
            raise ValidationError(
                f"servants.{tool}.wrapper_defaults.timeout_ms must be a non-negative integer"
            )

        stage_timeout_mode = timeout_mode_override or wrapper_defaults.get(
            tool, {}
        ).get("timeout_mode")
        if stage_timeout_mode not in TIMEOUT_MODE_VALUES:
            raise ValidationError(
                f"resolved timeout_mode '{stage_timeout_mode}' is invalid for plan stage '{stage_name}'"
            )
        stage_timeout_modes[stage_name] = stage_timeout_mode

        if tool == "codex":
            stage_purpose = _plan_stage_purpose(stage_name)
            stage_effort = profile_stage_efforts.get(stage_name)
            if stage_effort is None:
                stage_effort = codex_purpose_efforts.get(stage_purpose)
            if stage_effort is None:
                stage_effort = wrapper_defaults.get("codex", {}).get("effort")
            if stage_effort not in CODEX_EFFORT_VALUES:
                raise ValidationError(
                    f"resolved codex effort '{stage_effort}' is invalid for plan stage '{stage_name}'"
                )
            stage_efforts[stage_name] = stage_effort

    return {
        "profile": profile_name,
        "flags": flags,
        "options": options,
        "tool_models": tool_models,
        "purpose_models": purpose_models,
        "stage_models": stage_models,
        "stage_efforts": stage_efforts,
        "stage_timeout_ms": stage_timeout_ms,
        "stage_timeout_modes": stage_timeout_modes,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Resolve runtime config")
    sub = parser.add_subparsers(dest="mode", required=True)

    def add_source_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--config-root",
            required=True,
            help="Path to configs directory containing servant/ and pipeline/",
        )

    p_dispatch = sub.add_parser("dispatch", help="Resolve config for dispatch.sh")
    add_source_args(p_dispatch)
    p_dispatch.add_argument("--manifest", required=True)
    p_dispatch.add_argument("--plan-name", default="auto")
    p_dispatch.add_argument("--intent-default", default="safe_impl")

    p_plan = sub.add_parser("plan", help="Resolve config for run_plan_pipeline.sh")
    add_source_args(p_plan)
    p_plan.add_argument("--profile")
    p_plan.add_argument("--copilot-model")
    p_plan.add_argument("--gemini-model")
    p_plan.add_argument("--codex-model")

    args = parser.parse_args()

    try:
        cfg = load_and_validate_split_config(args.config_root)

        if args.mode == "dispatch":
            manifest = load_manifest_if_present(args.manifest)
            if manifest is None:
                raise ValidationError("manifest is required for dispatch resolution")
            validate_manifest_extensions(cfg, manifest, manifest_path=args.manifest)
            resolved = resolve_dispatch(
                cfg, manifest, args.plan_name, args.intent_default
            )
        else:
            model_overrides = {
                "copilot": args.copilot_model,
                "gemini": args.gemini_model,
                "codex": args.codex_model,
            }
            resolved = resolve_plan_pipeline(cfg, args.profile, model_overrides)

    except ValidationError as e:
        print(f"CONFIG RESOLVE ERROR: {e}", file=sys.stderr)
        return 1

    json.dump(resolved, sys.stdout, indent=2, sort_keys=True)
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
