#!/usr/bin/env python3
"""Fail-closed validator for Config V2."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set

import yaml

TOOLS = ("codex", "gemini", "copilot")
PHASES = ("plan", "impl", "review")
WEB_RESEARCH_MODES = ("off", "codex_explicit", "gemini_auto", "copilot_mcp")
DEFAULT_MODES = ("normal", "analysis_only")
GATE_PROFILES = ("standard", "strict", "minimal", "finding-first")
TIMEOUT_MODES = ("enforce", "wait_done")

TOOL_WEB_MODE_MAP = {
    "codex": {"off", "codex_explicit"},
    "gemini": {"off", "gemini_auto"},
    "copilot": {"off", "copilot_mcp"},
}

EXPECTED_FILES = {
    "skills": {"plan.yaml", "impl.yaml", "review.yaml"},
    "servants": {"codex.yaml", "gemini.yaml", "copilot.yaml"},
    "policies": {"routing.yaml", "review_parallel.yaml", "web_evidence.yaml"},
}

# Optional files that are allowed to exist but are not required.
OPTIONAL_FILES: Dict[str, Set[str]] = {}

ROUTING_STOP_ACTIONS = {"STOP_AND_CONFIRM"}
ROUTING_STOP_ON_STOP = {"write_reason_codes_to_routing_result"}
ROUTING_CONFIDENCE_VALUES = {"high", "medium", "low"}
ROUTING_IMPACT_SURFACES = {"low", "medium", "high"}
REPRODUCIBILITY_ON_MISMATCH = {"record_ROUTING_NON_DETERMINISTIC_and_stop"}

REVIEW_PARALLEL_MODE = "finding-first"
REVIEW_PARALLEL_JOIN_BARRIER = "required"
REVIEW_PARALLEL_APPLY_ORDER = "sequential"
REVIEW_PARALLEL_WORKER_OUTPUT_MODE = "analysis_only"

WEB_EVIDENCE_STRICTNESS = {"strict"}
WEB_EVIDENCE_GATE_ACTIONS = {"reject_and_stop"}
WEB_EVIDENCE_REQUIRED_FIELDS = {
    "evidence_id",
    "url",
    "accessed_at",
    "claim_summary",
}
WEB_EVIDENCE_REASON_CODES = {
    "WEB_EVIDENCE_MISSING",
    "WEB_EVIDENCE_UNVERIFIABLE",
    "WEB_EVIDENCE_STALE",
}


class ValidationError(Exception):
    pass


def _die(path: str, msg: str) -> None:
    raise ValidationError(f"{path}: {msg}")


def _expect_type(value: Any, expected_type: type, path: str) -> None:
    if not isinstance(value, expected_type):
        _die(path, f"must be {expected_type.__name__}")


def _ensure_keys(mapping: Mapping[str, Any], allowed: Iterable[str], path: str) -> None:
    allowed_set = set(allowed)
    unknown = sorted(set(mapping.keys()) - allowed_set)
    if unknown:
        _die(path, f"unknown keys: {', '.join(unknown)}")


def _expect_non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _die(path, "must be a non-empty string")
    return value


def _expect_string_list(
    value: Any, path: str, *, non_empty: bool = True
) -> Sequence[str]:
    _expect_type(value, list, path)
    out = []
    for idx, item in enumerate(value):
        out.append(_expect_non_empty_string(item, f"{path}[{idx}]"))
    if non_empty and not out:
        _die(path, "must not be empty")
    return out


def _load_yaml(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        _die(path, "file not found")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        _die(path, "file is empty")
    if not isinstance(data, dict):
        _die(path, "top-level must be a mapping")
    return data


def _validate_expected_files(root: str, subdir: str) -> None:
    dir_path = os.path.join(root, subdir)
    if not os.path.isdir(dir_path):
        _die(dir_path, "directory not found")

    found = {
        name
        for name in os.listdir(dir_path)
        if os.path.isfile(os.path.join(dir_path, name)) and name.endswith(".yaml")
    }
    expected = EXPECTED_FILES[subdir]

    missing = sorted(expected - found)
    if missing:
        _die(dir_path, f"missing required files: {', '.join(missing)}")

    optional = OPTIONAL_FILES.get(subdir, set())
    extra = sorted(found - expected - optional)
    if extra:
        _die(dir_path, f"unknown config files: {', '.join(extra)}")


def _validate_step_default(path: str, step_node: Dict[str, Any]) -> None:
    _ensure_keys(
        step_node,
        {"default_tool", "default_mode", "web_research_mode", "description"},
        path,
    )

    default_tool = _expect_non_empty_string(
        step_node.get("default_tool"), f"{path}.default_tool"
    )
    if default_tool not in TOOLS:
        _die(f"{path}.default_tool", f"must be one of: {', '.join(TOOLS)}")

    default_mode = _expect_non_empty_string(
        step_node.get("default_mode"), f"{path}.default_mode"
    )
    if default_mode not in DEFAULT_MODES:
        _die(f"{path}.default_mode", f"must be one of: {', '.join(DEFAULT_MODES)}")

    web_mode = _expect_non_empty_string(
        step_node.get("web_research_mode"), f"{path}.web_research_mode"
    )
    if web_mode not in WEB_RESEARCH_MODES:
        _die(
            f"{path}.web_research_mode",
            f"must be one of: {', '.join(WEB_RESEARCH_MODES)}",
        )
    if web_mode != "off" and web_mode not in TOOL_WEB_MODE_MAP[default_tool]:
        _die(
            f"{path}.web_research_mode",
            f"'{web_mode}' is not compatible with default_tool '{default_tool}'",
        )


def _validate_skill_file(node: Dict[str, Any], skill: str, path: str) -> Dict[str, Any]:
    _ensure_keys(
        node,
        {"version", "skill", "default_method_ids", "methods", "step_defaults"},
        path,
    )

    if node.get("version") != 2:
        _die(f"{path}.version", "must be 2")

    if node.get("skill") != skill:
        _die(f"{path}.skill", f"must be '{skill}'")

    default_method_ids = _expect_string_list(
        node.get("default_method_ids"), f"{path}.default_method_ids"
    )

    methods = node.get("methods")
    _expect_type(methods, dict, f"{path}.methods")
    if not methods:
        _die(f"{path}.methods", "must define at least one method")

    for method_id, method_node in methods.items():
        method_path = f"{path}.methods.{method_id}"
        _expect_type(method_node, dict, method_path)
        _ensure_keys(
            method_node,
            {"enabled", "steps", "allowed_tools", "gate_profile"},
            method_path,
        )

        enabled = method_node.get("enabled")
        if not isinstance(enabled, bool):
            _die(f"{method_path}.enabled", "must be boolean")

        steps = _expect_string_list(method_node.get("steps"), f"{method_path}.steps")
        allowed_tools = _expect_string_list(
            method_node.get("allowed_tools"), f"{method_path}.allowed_tools"
        )
        for idx, tool in enumerate(allowed_tools):
            if tool not in TOOLS:
                _die(
                    f"{method_path}.allowed_tools[{idx}]",
                    f"must be one of: {', '.join(TOOLS)}",
                )

        gate_profile = _expect_non_empty_string(
            method_node.get("gate_profile"), f"{method_path}.gate_profile"
        )
        if gate_profile not in GATE_PROFILES:
            _die(
                f"{method_path}.gate_profile",
                f"must be one of: {', '.join(GATE_PROFILES)}",
            )

        if enabled and not steps:
            _die(f"{method_path}.steps", "enabled method must have at least one step")

    for idx, method_id in enumerate(default_method_ids):
        if method_id not in methods:
            _die(
                f"{path}.default_method_ids[{idx}]",
                "must reference a method defined in methods",
            )

    step_defaults = node.get("step_defaults")
    _expect_type(step_defaults, dict, f"{path}.step_defaults")
    if not step_defaults:
        _die(f"{path}.step_defaults", "must define at least one step default")

    all_method_steps = set()
    for method_id, method_node in methods.items():
        method_steps = method_node.get("steps") or []
        all_method_steps.update(method_steps)
        for step in method_steps:
            if step not in step_defaults:
                _die(
                    f"{path}.methods.{method_id}.steps",
                    f"step '{step}' missing from step_defaults",
                )

    for step_id in step_defaults.keys():
        if step_id not in all_method_steps:
            _die(
                f"{path}.step_defaults.{step_id}",
                "step is not referenced by any method",
            )

    for step_id, step_node in step_defaults.items():
        step_path = f"{path}.step_defaults.{step_id}"
        _expect_type(step_node, dict, step_path)
        _validate_step_default(step_path, step_node)

    return node


def _validate_servant_file(
    node: Dict[str, Any], tool: str, path: str
) -> Dict[str, Any]:
    # Allow v1 runtime fields (purpose_models, purpose_efforts) as optional
    # extensions so that a single servant file can satisfy both the v1 runtime
    # (config_resolve.py reads purpose_models/purpose_efforts) and this v2
    # validator. See config_validate.py::_normalize_servant_file for the mirror.
    _ensure_keys(
        node,
        {
            "version",
            "tool",
            "default_model",
            "allowed_models",
            "wrapper_defaults",
            "web_capabilities",
            "purpose_models",  # v1 runtime extension — optional
            "purpose_efforts",  # v1 runtime extension — optional
            "effort_level_descriptions",  # documentation only — optional
        },
        path,
    )

    if node.get("version") != 2:
        _die(f"{path}.version", "must be 2")

    if node.get("tool") != tool:
        _die(f"{path}.tool", f"must be '{tool}'")

    default_model = _expect_non_empty_string(
        node.get("default_model"), f"{path}.default_model"
    )

    allowed_models = _expect_string_list(
        node.get("allowed_models"), f"{path}.allowed_models"
    )
    if default_model not in allowed_models:
        _die(f"{path}.default_model", "must be included in allowed_models")

    wrapper_defaults = node.get("wrapper_defaults")
    _expect_type(wrapper_defaults, dict, f"{path}.wrapper_defaults")
    # Allow v1 tool-specific keys (effort, approval_mode, sandbox) as optional
    # extensions so that a single servant file satisfies both validators.
    _ensure_keys(
        wrapper_defaults,
        {"timeout_ms", "timeout_mode", "effort", "approval_mode", "sandbox"},
        f"{path}.wrapper_defaults",
    )

    timeout_ms = wrapper_defaults.get("timeout_ms")
    if not isinstance(timeout_ms, int) or timeout_ms < 0:
        _die(f"{path}.wrapper_defaults.timeout_ms", "must be a non-negative integer")

    timeout_mode = _expect_non_empty_string(
        wrapper_defaults.get("timeout_mode"), f"{path}.wrapper_defaults.timeout_mode"
    )
    if timeout_mode not in TIMEOUT_MODES:
        _die(
            f"{path}.wrapper_defaults.timeout_mode",
            f"must be one of: {', '.join(TIMEOUT_MODES)}",
        )

    web_capabilities = node.get("web_capabilities")
    _expect_type(web_capabilities, dict, f"{path}.web_capabilities")
    _ensure_keys(web_capabilities, {"modes"}, f"{path}.web_capabilities")

    modes = _expect_string_list(
        web_capabilities.get("modes"), f"{path}.web_capabilities.modes"
    )
    allowed_modes = TOOL_WEB_MODE_MAP[tool]
    for idx, mode in enumerate(modes):
        if mode not in allowed_modes:
            _die(
                f"{path}.web_capabilities.modes[{idx}]",
                f"must be one of: {', '.join(sorted(allowed_modes))}",
            )
    if "off" not in modes:
        _die(f"{path}.web_capabilities.modes", "must include 'off'")

    return node


def _validate_routing_policy(node: Dict[str, Any], path: str) -> Dict[str, Any]:
    _ensure_keys(
        node,
        {
            "version",
            "stop_policy",
            "confidence_policy",
            "hard_stop_reason_map",
            "reproducibility_policy",
            "route_decider_policy",
        },
        path,
    )

    if node.get("version") != 2:
        _die(f"{path}.version", "must be 2")

    stop_policy = node.get("stop_policy")
    _expect_type(stop_policy, dict, f"{path}.stop_policy")
    _ensure_keys(stop_policy, {"conditions", "on_stop"}, f"{path}.stop_policy")

    conditions = stop_policy.get("conditions")
    _expect_type(conditions, list, f"{path}.stop_policy.conditions")
    if not conditions:
        _die(f"{path}.stop_policy.conditions", "must not be empty")

    for idx, cond in enumerate(conditions):
        cond_path = f"{path}.stop_policy.conditions[{idx}]"
        _expect_type(cond, dict, cond_path)
        _ensure_keys(
            cond,
            {
                "impact_surface",
                "confidence",
                "reason_codes_contain",
                "strict_evidence_violation",
                "action",
            },
            cond_path,
        )

        if "action" not in cond:
            _die(cond_path, "missing required key: action")
        action = _expect_non_empty_string(cond.get("action"), f"{cond_path}.action")
        if action not in ROUTING_STOP_ACTIONS:
            _die(
                f"{cond_path}.action",
                f"must be one of: {', '.join(sorted(ROUTING_STOP_ACTIONS))}",
            )

        if "impact_surface" in cond:
            impact = _expect_non_empty_string(
                cond.get("impact_surface"), f"{cond_path}.impact_surface"
            )
            if impact not in ROUTING_IMPACT_SURFACES:
                _die(
                    f"{cond_path}.impact_surface",
                    f"must be one of: {', '.join(sorted(ROUTING_IMPACT_SURFACES))}",
                )

        if "confidence" in cond:
            confidence = _expect_non_empty_string(
                cond.get("confidence"), f"{cond_path}.confidence"
            )
            if confidence not in ROUTING_CONFIDENCE_VALUES:
                _die(
                    f"{cond_path}.confidence",
                    f"must be one of: {', '.join(sorted(ROUTING_CONFIDENCE_VALUES))}",
                )

        if "reason_codes_contain" in cond:
            _expect_non_empty_string(
                cond.get("reason_codes_contain"), f"{cond_path}.reason_codes_contain"
            )

        if "strict_evidence_violation" in cond:
            if not isinstance(cond.get("strict_evidence_violation"), bool):
                _die(f"{cond_path}.strict_evidence_violation", "must be boolean")

    on_stop = _expect_non_empty_string(
        stop_policy.get("on_stop"), f"{path}.stop_policy.on_stop"
    )
    if on_stop not in ROUTING_STOP_ON_STOP:
        _die(
            f"{path}.stop_policy.on_stop",
            f"must be one of: {', '.join(sorted(ROUTING_STOP_ON_STOP))}",
        )

    confidence_policy = node.get("confidence_policy")
    _expect_type(confidence_policy, dict, f"{path}.confidence_policy")
    _ensure_keys(confidence_policy, {"values", "default"}, f"{path}.confidence_policy")

    values = _expect_string_list(
        confidence_policy.get("values"), f"{path}.confidence_policy.values"
    )
    values_set = set(values)
    if not values_set.issubset(ROUTING_CONFIDENCE_VALUES):
        _die(
            f"{path}.confidence_policy.values",
            f"must be subset of: {', '.join(sorted(ROUTING_CONFIDENCE_VALUES))}",
        )
    default_confidence = _expect_non_empty_string(
        confidence_policy.get("default"), f"{path}.confidence_policy.default"
    )
    if default_confidence not in values_set:
        _die(
            f"{path}.confidence_policy.default",
            "must be included in confidence_policy.values",
        )

    hard_stop_reason_map = node.get("hard_stop_reason_map")
    _expect_type(hard_stop_reason_map, dict, f"{path}.hard_stop_reason_map")
    if not hard_stop_reason_map:
        _die(f"{path}.hard_stop_reason_map", "must not be empty")
    for reason_code, reason_msg in hard_stop_reason_map.items():
        _expect_non_empty_string(reason_code, f"{path}.hard_stop_reason_map.<key>")
        _expect_non_empty_string(
            reason_msg, f"{path}.hard_stop_reason_map.{reason_code}"
        )

    reproducibility_policy = node.get("reproducibility_policy")
    _expect_type(reproducibility_policy, dict, f"{path}.reproducibility_policy")
    _ensure_keys(
        reproducibility_policy,
        {"deterministic_required", "on_mismatch"},
        f"{path}.reproducibility_policy",
    )
    if not isinstance(reproducibility_policy.get("deterministic_required"), bool):
        _die(f"{path}.reproducibility_policy.deterministic_required", "must be boolean")
    on_mismatch = _expect_non_empty_string(
        reproducibility_policy.get("on_mismatch"),
        f"{path}.reproducibility_policy.on_mismatch",
    )
    if on_mismatch not in REPRODUCIBILITY_ON_MISMATCH:
        _die(
            f"{path}.reproducibility_policy.on_mismatch",
            f"must be one of: {', '.join(sorted(REPRODUCIBILITY_ON_MISMATCH))}",
        )

    route_decider_policy = node.get("route_decider_policy")
    _expect_type(route_decider_policy, dict, f"{path}.route_decider_policy")
    _ensure_keys(
        route_decider_policy,
        {"phase_prompt_paths", "schema_version"},
        f"{path}.route_decider_policy",
    )

    phase_prompt_paths = route_decider_policy.get("phase_prompt_paths")
    _expect_type(
        phase_prompt_paths, dict, f"{path}.route_decider_policy.phase_prompt_paths"
    )
    _ensure_keys(
        phase_prompt_paths,
        set(PHASES),
        f"{path}.route_decider_policy.phase_prompt_paths",
    )
    for phase in PHASES:
        _expect_non_empty_string(
            phase_prompt_paths.get(phase),
            f"{path}.route_decider_policy.phase_prompt_paths.{phase}",
        )

    if route_decider_policy.get("schema_version") != 2:
        _die(f"{path}.route_decider_policy.schema_version", "must be 2")

    return node


def _validate_review_parallel_policy(node: Dict[str, Any], path: str) -> Dict[str, Any]:
    _ensure_keys(
        node,
        {
            "version",
            "mode",
            "join_barrier",
            "apply_order",
            "worker_output_mode",
            "merge_required",
            "artifacts",
        },
        path,
    )

    if node.get("version") != 2:
        _die(f"{path}.version", "must be 2")

    mode = _expect_non_empty_string(node.get("mode"), f"{path}.mode")
    if mode != REVIEW_PARALLEL_MODE:
        _die(f"{path}.mode", f"must be '{REVIEW_PARALLEL_MODE}'")

    join_barrier = _expect_non_empty_string(
        node.get("join_barrier"), f"{path}.join_barrier"
    )
    if join_barrier != REVIEW_PARALLEL_JOIN_BARRIER:
        _die(f"{path}.join_barrier", f"must be '{REVIEW_PARALLEL_JOIN_BARRIER}'")

    apply_order = _expect_non_empty_string(
        node.get("apply_order"), f"{path}.apply_order"
    )
    if apply_order != REVIEW_PARALLEL_APPLY_ORDER:
        _die(f"{path}.apply_order", f"must be '{REVIEW_PARALLEL_APPLY_ORDER}'")

    worker_output_mode = _expect_non_empty_string(
        node.get("worker_output_mode"), f"{path}.worker_output_mode"
    )
    if worker_output_mode != REVIEW_PARALLEL_WORKER_OUTPUT_MODE:
        _die(
            f"{path}.worker_output_mode",
            f"must be '{REVIEW_PARALLEL_WORKER_OUTPUT_MODE}'",
        )

    if not isinstance(node.get("merge_required"), bool):
        _die(f"{path}.merge_required", "must be boolean")

    artifacts = node.get("artifacts")
    _expect_type(artifacts, dict, f"{path}.artifacts")
    _ensure_keys(artifacts, {"findings_dir", "merged", "queue"}, f"{path}.artifacts")
    for key in ("findings_dir", "merged", "queue"):
        _expect_non_empty_string(artifacts.get(key), f"{path}.artifacts.{key}")

    return node


def _validate_web_evidence_policy(node: Dict[str, Any], path: str) -> Dict[str, Any]:
    _ensure_keys(
        node,
        {
            "version",
            "strictness",
            "required_fields",
            "reason_code_map",
            "gate_action_on_violation",
        },
        path,
    )

    if node.get("version") != 2:
        _die(f"{path}.version", "must be 2")

    strictness = _expect_non_empty_string(node.get("strictness"), f"{path}.strictness")
    if strictness not in WEB_EVIDENCE_STRICTNESS:
        _die(
            f"{path}.strictness",
            f"must be one of: {', '.join(sorted(WEB_EVIDENCE_STRICTNESS))}",
        )

    required_fields = set(
        _expect_string_list(node.get("required_fields"), f"{path}.required_fields")
    )
    if required_fields != WEB_EVIDENCE_REQUIRED_FIELDS:
        _die(
            f"{path}.required_fields",
            "must exactly match required evidence field set",
        )

    reason_code_map = node.get("reason_code_map")
    _expect_type(reason_code_map, dict, f"{path}.reason_code_map")
    _ensure_keys(reason_code_map, WEB_EVIDENCE_REASON_CODES, f"{path}.reason_code_map")
    for code, msg in reason_code_map.items():
        _expect_non_empty_string(code, f"{path}.reason_code_map.<key>")
        _expect_non_empty_string(msg, f"{path}.reason_code_map.{code}")

    gate_action = _expect_non_empty_string(
        node.get("gate_action_on_violation"),
        f"{path}.gate_action_on_violation",
    )
    if gate_action not in WEB_EVIDENCE_GATE_ACTIONS:
        _die(
            f"{path}.gate_action_on_violation",
            f"must be one of: {', '.join(sorted(WEB_EVIDENCE_GATE_ACTIONS))}",
        )

    return node


def load_and_validate_v2_config(config_root: str) -> Dict[str, Any]:
    root = os.path.abspath(config_root)

    for subdir in ("skills", "servants", "policies"):
        _validate_expected_files(root, subdir)

    skills: Dict[str, Any] = {}
    for phase in PHASES:
        path = os.path.join(root, "skills", f"{phase}.yaml")
        node = _load_yaml(path)
        skills[phase] = _validate_skill_file(node, phase, path)

    servants: Dict[str, Any] = {}
    for tool in TOOLS:
        path = os.path.join(root, "servants", f"{tool}.yaml")
        node = _load_yaml(path)
        servants[tool] = _validate_servant_file(node, tool, path)

    policies: Dict[str, Any] = {}
    routing_path = os.path.join(root, "policies", "routing.yaml")
    policies["routing"] = _validate_routing_policy(
        _load_yaml(routing_path), routing_path
    )

    review_parallel_path = os.path.join(root, "policies", "review_parallel.yaml")
    policies["review_parallel"] = _validate_review_parallel_policy(
        _load_yaml(review_parallel_path),
        review_parallel_path,
    )

    web_evidence_path = os.path.join(root, "policies", "web_evidence.yaml")
    policies["web_evidence"] = _validate_web_evidence_policy(
        _load_yaml(web_evidence_path),
        web_evidence_path,
    )

    return {
        "version": 2,
        "root": root,
        "skills": skills,
        "servants": servants,
        "policies": policies,
    }


def load_manifest_if_present(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    return _load_yaml(path)


def _normalize_phase_override(
    cfg: Dict[str, Any],
    phase: str,
    node: Dict[str, Any],
    path: str,
) -> Dict[str, Any]:
    _ensure_keys(node, {"method_id", "tool_models", "step_overrides"}, path)

    out: Dict[str, Any] = {}

    if "method_id" in node:
        method_id = _expect_non_empty_string(node.get("method_id"), f"{path}.method_id")
        methods = cfg["skills"][phase]["methods"]
        if method_id not in methods:
            _die(
                f"{path}.method_id",
                f"unknown method_id '{method_id}' for phase '{phase}'",
            )
        out["method_id"] = method_id

    tool_models = node.get("tool_models") or {}
    _expect_type(tool_models, dict, f"{path}.tool_models")
    _ensure_keys(tool_models, set(TOOLS), f"{path}.tool_models")
    normalized_tool_models: Dict[str, str] = {}
    for tool, model in tool_models.items():
        model_name = _expect_non_empty_string(model, f"{path}.tool_models.{tool}")
        allowed_models = cfg["servants"][tool]["allowed_models"]
        if model_name not in allowed_models:
            _die(
                f"{path}.tool_models.{tool}",
                f"model '{model_name}' is not in allowed_models",
            )
        normalized_tool_models[tool] = model_name
    out["tool_models"] = normalized_tool_models

    step_overrides = node.get("step_overrides") or {}
    _expect_type(step_overrides, dict, f"{path}.step_overrides")

    step_defaults = cfg["skills"][phase]["step_defaults"]
    normalized_step_overrides: Dict[str, Dict[str, Any]] = {}
    for step_id, step_node in step_overrides.items():
        step_path = f"{path}.step_overrides.{step_id}"
        if step_id not in step_defaults:
            _die(step_path, f"unknown step_id '{step_id}' for phase '{phase}'")
        _expect_type(step_node, dict, step_path)
        _ensure_keys(
            step_node, {"tool", "model", "default_mode", "web_research_mode"}, step_path
        )

        normalized_step: Dict[str, Any] = {}

        tool = step_node.get("tool")
        if tool is not None:
            tool_value = _expect_non_empty_string(tool, f"{step_path}.tool")
            if tool_value not in TOOLS:
                _die(f"{step_path}.tool", f"must be one of: {', '.join(TOOLS)}")
            normalized_step["tool"] = tool_value

        default_mode = step_node.get("default_mode")
        if default_mode is not None:
            default_mode_value = _expect_non_empty_string(
                default_mode, f"{step_path}.default_mode"
            )
            if default_mode_value not in DEFAULT_MODES:
                _die(
                    f"{step_path}.default_mode",
                    f"must be one of: {', '.join(DEFAULT_MODES)}",
                )
            normalized_step["default_mode"] = default_mode_value

        web_research_mode = step_node.get("web_research_mode")
        if web_research_mode is not None:
            web_mode_value = _expect_non_empty_string(
                web_research_mode, f"{step_path}.web_research_mode"
            )
            if web_mode_value not in WEB_RESEARCH_MODES:
                _die(
                    f"{step_path}.web_research_mode",
                    f"must be one of: {', '.join(WEB_RESEARCH_MODES)}",
                )
            normalized_step["web_research_mode"] = web_mode_value

        model = step_node.get("model")
        if model is not None:
            model_value = _expect_non_empty_string(model, f"{step_path}.model")
            tool_for_model = (
                normalized_step.get("tool") or step_defaults[step_id]["default_tool"]
            )
            allowed_models = cfg["servants"][tool_for_model]["allowed_models"]
            if model_value not in allowed_models:
                _die(
                    f"{step_path}.model",
                    f"model '{model_value}' is not allowed for tool '{tool_for_model}'",
                )
            normalized_step["model"] = model_value

        effective_tool = (
            normalized_step.get("tool") or step_defaults[step_id]["default_tool"]
        )
        effective_web_mode = (
            normalized_step.get("web_research_mode")
            or step_defaults[step_id]["web_research_mode"]
        )
        if (
            effective_web_mode != "off"
            and effective_web_mode not in TOOL_WEB_MODE_MAP[effective_tool]
        ):
            _die(
                f"{step_path}.web_research_mode",
                f"'{effective_web_mode}' is not compatible with tool '{effective_tool}'",
            )

        normalized_step_overrides[step_id] = normalized_step

    out["step_overrides"] = normalized_step_overrides
    return out


def parse_manifest_v2_overrides(
    cfg: Dict[str, Any],
    manifest: Optional[Dict[str, Any]],
    manifest_path: str = "manifest",
) -> Dict[str, Any]:
    out = {
        "phase_overrides": {
            phase: {"tool_models": {}, "step_overrides": {}} for phase in PHASES
        }
    }
    if manifest is None:
        return out

    if not isinstance(manifest, dict):
        _die(manifest_path, "top-level must be a mapping")

    config_v2 = manifest.get("config_v2")
    if config_v2 is None:
        return out

    _expect_type(config_v2, dict, f"{manifest_path}.config_v2")
    _ensure_keys(config_v2, {"phase_overrides"}, f"{manifest_path}.config_v2")

    phase_overrides = config_v2.get("phase_overrides") or {}
    _expect_type(phase_overrides, dict, f"{manifest_path}.config_v2.phase_overrides")
    _ensure_keys(
        phase_overrides, set(PHASES), f"{manifest_path}.config_v2.phase_overrides"
    )

    for phase, node in phase_overrides.items():
        phase_path = f"{manifest_path}.config_v2.phase_overrides.{phase}"
        _expect_type(node, dict, phase_path)
        out["phase_overrides"][phase] = _normalize_phase_override(
            cfg, phase, node, phase_path
        )

    return out


def validate_manifest_v2_overrides(
    cfg: Dict[str, Any],
    manifest: Optional[Dict[str, Any]],
    manifest_path: str = "manifest",
) -> None:
    parse_manifest_v2_overrides(cfg, manifest, manifest_path=manifest_path)


def build_choices_catalog(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "version": 2,
        "enums": {
            "tools": sorted(TOOLS),
            "phases": sorted(PHASES),
            "default_mode": sorted(DEFAULT_MODES),
            "web_research_mode": sorted(WEB_RESEARCH_MODES),
            "gate_profile": sorted(GATE_PROFILES),
            "timeout_mode": sorted(TIMEOUT_MODES),
            "routing_stop_action": sorted(ROUTING_STOP_ACTIONS),
        },
        "tool_web_capabilities": {
            tool: sorted(modes) for tool, modes in TOOL_WEB_MODE_MAP.items()
        },
        "servants": {
            tool: {
                "default_model": cfg["servants"][tool]["default_model"],
                "allowed_models": list(cfg["servants"][tool]["allowed_models"]),
            }
            for tool in TOOLS
        },
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate Config V2 YAML files")
    parser.add_argument(
        "--config-root", required=True, help="Path to configs-v2 directory"
    )
    parser.add_argument(
        "--manifest", help="Optional path to task manifest for override validation"
    )
    parser.add_argument(
        "--print-choices",
        action="store_true",
        help="Print allowed enum choices and model choices as JSON",
    )
    args = parser.parse_args()

    try:
        cfg = load_and_validate_v2_config(args.config_root)
        manifest = load_manifest_if_present(args.manifest)
        validate_manifest_v2_overrides(
            cfg, manifest, manifest_path=args.manifest or "manifest"
        )
    except ValidationError as e:
        print(f"CONFIG V2 VALIDATION ERROR: {e}", file=sys.stderr)
        return 1
    except yaml.YAMLError as e:
        print(f"CONFIG V2 VALIDATION ERROR: YAML parse failed: {e}", file=sys.stderr)
        return 1

    if args.print_choices:
        json.dump(build_choices_catalog(cfg), sys.stdout, indent=2, sort_keys=True)
        print("")
        return 0

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
