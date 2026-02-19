#!/usr/bin/env python3
"""Strict validator for split config files and manifest extensions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import yaml

SERVANT_NAMES = ("codex", "gemini", "copilot")

PIPELINE_FLAGS = {
    "impl": {"enable_brief", "enable_verify", "enable_review"},
    "review": {"enable_verify", "enable_review"},
    "plan": {"enable_stage2_codex", "enable_stage2_gemini", "enable_stage3_cross_review"},
}

PIPELINE_OPTIONS = {
    "impl": {
        "impl_mode": {"safe", "one_shot"},
        "timeout_mode": {"enforce", "wait_done"},
    },
    "review": {
        "review_mode": {"codex_only", "cross"},
        "timeout_mode": {"enforce", "wait_done"},
    },
    "plan": {
        "consolidate_mode": {"standard"},
        "timeout_mode": {"enforce", "wait_done"},
    },
}

WRAPPER_DEFAULT_KEYS = {
    "codex": {"effort", "timeout_ms", "timeout_mode"},
    "gemini": {"approval_mode", "sandbox", "timeout_ms", "timeout_mode"},
    "copilot": {"timeout_ms", "timeout_mode"},
}

CODEX_EFFORT_VALUES = {"low", "medium", "high", "xhigh"}
GEMINI_APPROVAL_VALUES = {"default", "auto_edit", "yolo"}
TIMEOUT_MODE_VALUES = {"enforce", "wait_done"}

PLAN_STAGE_TOOL = {
    "stage1": "copilot",
    "stage2_codex": "codex",
    "stage2_gemini": "gemini",
    "stage3_codex_review": "codex",
    "stage3_gemini_review": "gemini",
    "stage4": "copilot",
}

SERVANT_FILES = {
    "codex": ("servant", "codex.yaml"),
    "gemini": ("servant", "gemini.yaml"),
    "copilot": ("servant", "copilot.yaml"),
}

PIPELINE_FILES = {
    "impl": ("pipeline", "impl-pipeline.yaml"),
    "review": ("pipeline", "review-pipeline.yaml"),
    "plan": ("pipeline", "plan-pipeline.yaml"),
}


class ValidationError(Exception):
    pass


def _die(path: str, msg: str) -> None:
    raise ValidationError(f"{path}: {msg}")


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


def _ensure_keys(mapping: Mapping[str, Any], allowed: Iterable[str], path: str) -> None:
    allowed_set = set(allowed)
    unknown = sorted(set(mapping.keys()) - allowed_set)
    if unknown:
        _die(path, f"unknown keys: {', '.join(unknown)}")


def _expect_type(value: Any, t: type, path: str) -> None:
    if not isinstance(value, t):
        _die(path, f"must be {t.__name__}")


def _expect_str_set(value: Any, path: str) -> Sequence[str]:
    _expect_type(value, list, path)
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            _die(f"{path}[{i}]", "must be a non-empty string")
        out.append(item)
    return out


def _stage_to_tool(stage: str, pipeline_name: str) -> Optional[str]:
    if pipeline_name == "plan":
        return PLAN_STAGE_TOOL.get(stage)
    if "_" not in stage:
        return None
    tool = stage.split("_", 1)[0]
    return tool if tool in SERVANT_NAMES else None


def validate_runtime_config_dict(cfg: Dict[str, Any], cfg_path: str = "config") -> Dict[str, Any]:
    _ensure_keys(cfg, {"version", "servants", "pipelines"}, cfg_path)

    version = cfg.get("version")
    if version != 1:
        _die(f"{cfg_path}.version", "must be 1")

    servants = cfg.get("servants")
    _expect_type(servants, dict, f"{cfg_path}.servants")
    _ensure_keys(servants, set(SERVANT_NAMES), f"{cfg_path}.servants")

    for servant in SERVANT_NAMES:
        node = servants.get(servant)
        _expect_type(node, dict, f"{cfg_path}.servants.{servant}")
        _ensure_keys(
            node,
            {"default_model", "allowed_models", "wrapper_defaults", "purpose_models", "purpose_efforts"},
            f"{cfg_path}.servants.{servant}",
        )

        default_model = node.get("default_model")
        if not isinstance(default_model, str) or not default_model.strip():
            _die(f"{cfg_path}.servants.{servant}.default_model", "must be a non-empty string")

        allowed_models = _expect_str_set(node.get("allowed_models"), f"{cfg_path}.servants.{servant}.allowed_models")
        if default_model not in allowed_models:
            _die(
                f"{cfg_path}.servants.{servant}.default_model",
                "must be included in allowed_models",
            )

        wrapper_defaults = node.get("wrapper_defaults")
        _expect_type(wrapper_defaults, dict, f"{cfg_path}.servants.{servant}.wrapper_defaults")
        _ensure_keys(wrapper_defaults, WRAPPER_DEFAULT_KEYS[servant], f"{cfg_path}.servants.{servant}.wrapper_defaults")
        missing_wrapper_keys = sorted(WRAPPER_DEFAULT_KEYS[servant] - set(wrapper_defaults.keys()))
        if missing_wrapper_keys:
            _die(
                f"{cfg_path}.servants.{servant}.wrapper_defaults",
                f"missing required keys: {', '.join(missing_wrapper_keys)}",
            )
        for key, raw in wrapper_defaults.items():
            key_path = f"{cfg_path}.servants.{servant}.wrapper_defaults.{key}"
            if key == "timeout_ms":
                if not isinstance(raw, int) or raw < 0:
                    _die(key_path, "must be a non-negative integer")
            elif key == "timeout_mode":
                if not isinstance(raw, str) or raw not in TIMEOUT_MODE_VALUES:
                    _die(key_path, f"must be one of: {', '.join(sorted(TIMEOUT_MODE_VALUES))}")
            elif servant == "codex" and key == "effort":
                if not isinstance(raw, str) or raw not in CODEX_EFFORT_VALUES:
                    _die(key_path, f"must be one of: {', '.join(sorted(CODEX_EFFORT_VALUES))}")
            elif servant == "gemini" and key == "approval_mode":
                if not isinstance(raw, str) or raw not in GEMINI_APPROVAL_VALUES:
                    _die(key_path, f"must be one of: {', '.join(sorted(GEMINI_APPROVAL_VALUES))}")
            elif servant == "gemini" and key == "sandbox":
                if not isinstance(raw, bool):
                    _die(key_path, "must be boolean")

        purpose_models = node.get("purpose_models") or {}
        _expect_type(purpose_models, dict, f"{cfg_path}.servants.{servant}.purpose_models")
        _ensure_keys(
            purpose_models,
            {"impl", "review", "verify", "plan", "one_shot"},
            f"{cfg_path}.servants.{servant}.purpose_models",
        )
        for purpose_name, model in purpose_models.items():
            if not isinstance(model, str) or not model.strip():
                _die(
                    f"{cfg_path}.servants.{servant}.purpose_models.{purpose_name}",
                    "must be a non-empty string",
                )
            if model not in allowed_models:
                _die(
                    f"{cfg_path}.servants.{servant}.purpose_models.{purpose_name}",
                    f"model '{model}' is not in allowed_models",
                )

        purpose_efforts = node.get("purpose_efforts") or {}
        _expect_type(purpose_efforts, dict, f"{cfg_path}.servants.{servant}.purpose_efforts")
        if servant != "codex" and purpose_efforts:
            _die(
                f"{cfg_path}.servants.{servant}.purpose_efforts",
                "is only supported for codex",
            )
        _ensure_keys(
            purpose_efforts,
            {"impl", "review", "verify", "plan", "one_shot"},
            f"{cfg_path}.servants.{servant}.purpose_efforts",
        )
        for purpose_name, effort in purpose_efforts.items():
            if not isinstance(effort, str) or effort not in CODEX_EFFORT_VALUES:
                _die(
                    f"{cfg_path}.servants.{servant}.purpose_efforts.{purpose_name}",
                    f"must be one of: {', '.join(sorted(CODEX_EFFORT_VALUES))}",
                )

    pipelines = cfg.get("pipelines")
    _expect_type(pipelines, dict, f"{cfg_path}.pipelines")
    _ensure_keys(pipelines, {"impl", "review", "plan"}, f"{cfg_path}.pipelines")

    for pipeline_name in ("impl", "review", "plan"):
        pipeline = pipelines.get(pipeline_name)
        _expect_type(pipeline, dict, f"{cfg_path}.pipelines.{pipeline_name}")
        _ensure_keys(pipeline, {"default_profile", "profiles"}, f"{cfg_path}.pipelines.{pipeline_name}")

        default_profile = pipeline.get("default_profile")
        if not isinstance(default_profile, str) or not default_profile.strip():
            _die(f"{cfg_path}.pipelines.{pipeline_name}.default_profile", "must be a non-empty string")

        profiles = pipeline.get("profiles")
        _expect_type(profiles, dict, f"{cfg_path}.pipelines.{pipeline_name}.profiles")
        if not profiles:
            _die(f"{cfg_path}.pipelines.{pipeline_name}.profiles", "must define at least one profile")
        if default_profile not in profiles:
            _die(
                f"{cfg_path}.pipelines.{pipeline_name}.default_profile",
                "must match a profile name",
            )

        for profile_name, profile in profiles.items():
            _expect_type(profile, dict, f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}")
            _ensure_keys(
                profile,
                {"stages", "flags", "options", "stage_models", "stage_efforts"},
                f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}",
            )

            if pipeline_name in {"impl", "review"}:
                stages = _expect_str_set(
                    profile.get("stages"),
                    f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stages",
                )
                if not stages:
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stages",
                        "must not be empty",
                    )
                for idx, stage in enumerate(stages):
                    tool = _stage_to_tool(stage, pipeline_name)
                    if tool is None:
                        _die(
                            f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stages[{idx}]",
                            "must start with a known tool prefix",
                        )
            elif "stages" in profile and profile.get("stages") not in (None, []):
                _die(
                    f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stages",
                    "is not supported for the plan pipeline",
                )

            flags = profile.get("flags") or {}
            _expect_type(flags, dict, f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.flags")
            _ensure_keys(
                flags,
                PIPELINE_FLAGS[pipeline_name],
                f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.flags",
            )
            for flag_name, flag_value in flags.items():
                if not isinstance(flag_value, bool):
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.flags.{flag_name}",
                        "must be boolean",
                    )

            options = profile.get("options") or {}
            _expect_type(options, dict, f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.options")
            _ensure_keys(
                options,
                PIPELINE_OPTIONS[pipeline_name].keys(),
                f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.options",
            )
            for opt_name, opt_val in options.items():
                if not isinstance(opt_val, str):
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.options.{opt_name}",
                        "must be string",
                    )
                allowed_vals = PIPELINE_OPTIONS[pipeline_name][opt_name]
                if opt_val not in allowed_vals:
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.options.{opt_name}",
                        f"must be one of: {', '.join(sorted(allowed_vals))}",
                    )

            stage_models = profile.get("stage_models") or {}
            _expect_type(stage_models, dict, f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stage_models")
            for stage_name, model in stage_models.items():
                if not isinstance(model, str) or not model.strip():
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stage_models.{stage_name}",
                        "must be a non-empty string",
                    )
                tool = _stage_to_tool(stage_name, pipeline_name)
                if tool is None:
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stage_models.{stage_name}",
                        "unknown stage name",
                    )
                allowed = servants[tool]["allowed_models"]
                if model not in allowed:
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stage_models.{stage_name}",
                        f"model '{model}' is not allowed for servant '{tool}'",
                    )

            stage_efforts = profile.get("stage_efforts") or {}
            _expect_type(stage_efforts, dict, f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stage_efforts")
            for stage_name, effort in stage_efforts.items():
                if not isinstance(effort, str) or effort not in CODEX_EFFORT_VALUES:
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stage_efforts.{stage_name}",
                        f"must be one of: {', '.join(sorted(CODEX_EFFORT_VALUES))}",
                    )
                tool = _stage_to_tool(stage_name, pipeline_name)
                if tool is None:
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stage_efforts.{stage_name}",
                        "unknown stage name",
                    )
                if tool != "codex":
                    _die(
                        f"{cfg_path}.pipelines.{pipeline_name}.profiles.{profile_name}.stage_efforts.{stage_name}",
                        "is only supported for codex stages",
                    )

    return cfg


def _normalize_servant_file(raw: Dict[str, Any], servant: str, path: str) -> Dict[str, Any]:
    full_keys = {
        "version",
        "tool",
        "default_model",
        "allowed_models",
        "wrapper_defaults",
        "purpose_models",
        "purpose_efforts",
    }
    compact_keys = {
        "default_model",
        "allowed_models",
        "wrapper_defaults",
        "purpose_models",
        "purpose_efforts",
    }

    if "version" in raw or "tool" in raw:
        _ensure_keys(raw, full_keys, path)
        if raw.get("version") != 1:
            _die(f"{path}.version", "must be 1")
        if raw.get("tool") != servant:
            _die(f"{path}.tool", f"must be '{servant}'")
        return {
            "default_model": raw["default_model"],
            "allowed_models": raw["allowed_models"],
            "wrapper_defaults": raw["wrapper_defaults"],
            "purpose_models": raw.get("purpose_models", {}),
            "purpose_efforts": raw.get("purpose_efforts", {}),
        }

    _ensure_keys(raw, compact_keys, path)
    return dict(raw)


def _normalize_pipeline_file(raw: Dict[str, Any], pipeline: str, path: str) -> Dict[str, Any]:
    full_keys = {"version", "pipeline", "default_profile", "profiles"}
    compact_keys = {"default_profile", "profiles"}

    if "version" in raw or "pipeline" in raw:
        _ensure_keys(raw, full_keys, path)
        if raw.get("version") != 1:
            _die(f"{path}.version", "must be 1")
        if raw.get("pipeline") != pipeline:
            _die(f"{path}.pipeline", f"must be '{pipeline}'")
        return {
            "default_profile": raw["default_profile"],
            "profiles": raw["profiles"],
        }

    _ensure_keys(raw, compact_keys, path)
    return dict(raw)


def load_and_validate_split_config(config_root: str) -> Dict[str, Any]:
    root = os.path.abspath(config_root)
    servants: Dict[str, Any] = {}
    pipelines: Dict[str, Any] = {}

    for servant, (subdir, filename) in SERVANT_FILES.items():
        path = os.path.join(root, subdir, filename)
        raw = _load_yaml(path)
        servants[servant] = _normalize_servant_file(raw, servant, path)

    for pipeline, (subdir, filename) in PIPELINE_FILES.items():
        path = os.path.join(root, subdir, filename)
        raw = _load_yaml(path)
        pipelines[pipeline] = _normalize_pipeline_file(raw, pipeline, path)

    cfg = {
        "version": 1,
        "servants": servants,
        "pipelines": pipelines,
    }
    return validate_runtime_config_dict(cfg, cfg_path=root)


def _pipeline_name_for_intent(cfg: Dict[str, Any], intent: str) -> Optional[str]:
    pipelines = cfg["pipelines"]
    for name in ("impl", "review"):
        if intent in pipelines[name]["profiles"]:
            return name
    return None


def validate_manifest_extensions(
    cfg: Dict[str, Any], manifest: Optional[Dict[str, Any]], manifest_path: str = "manifest"
) -> None:
    if not manifest:
        return
    if not isinstance(manifest, dict):
        _die(manifest_path, "top-level must be a mapping")

    routing = manifest.get("routing") or {}
    if routing and not isinstance(routing, dict):
        _die(f"{manifest_path}.routing", "must be a mapping")
    if routing:
        _ensure_keys(routing, {"intent", "model", "pipeline"}, f"{manifest_path}.routing")

    if "intent" in routing and not isinstance(routing["intent"], str):
        _die(f"{manifest_path}.routing.intent", "must be a string")

    model_map = routing.get("model") or {}
    if model_map:
        _expect_type(model_map, dict, f"{manifest_path}.routing.model")
        _ensure_keys(model_map, set(SERVANT_NAMES), f"{manifest_path}.routing.model")
        for servant, model in model_map.items():
            if not isinstance(model, str) or not model.strip():
                _die(f"{manifest_path}.routing.model.{servant}", "must be a non-empty string")
            allowed = cfg["servants"][servant]["allowed_models"]
            if model not in allowed:
                _die(
                    f"{manifest_path}.routing.model.{servant}",
                    f"model '{model}' is not in allowed_models",
                )

    pipeline = routing.get("pipeline") or {}
    if pipeline:
        _expect_type(pipeline, dict, f"{manifest_path}.routing.pipeline")
        _ensure_keys(pipeline, {"profile", "flags", "options"}, f"{manifest_path}.routing.pipeline")

        profile = pipeline.get("profile")
        if profile is not None:
            if not isinstance(profile, str) or not profile.strip():
                _die(f"{manifest_path}.routing.pipeline.profile", "must be a non-empty string")

        flags = pipeline.get("flags") or {}
        _expect_type(flags, dict, f"{manifest_path}.routing.pipeline.flags")
        all_flags = set().union(*PIPELINE_FLAGS.values())
        _ensure_keys(flags, all_flags, f"{manifest_path}.routing.pipeline.flags")
        for flag_name, flag_val in flags.items():
            if not isinstance(flag_val, bool):
                _die(f"{manifest_path}.routing.pipeline.flags.{flag_name}", "must be boolean")

        options = pipeline.get("options") or {}
        _expect_type(options, dict, f"{manifest_path}.routing.pipeline.options")

        allowed_options = {}
        for opt_map in PIPELINE_OPTIONS.values():
            allowed_options.update(opt_map)
        _ensure_keys(options, allowed_options.keys(), f"{manifest_path}.routing.pipeline.options")
        for opt_name, opt_val in options.items():
            if not isinstance(opt_val, str):
                _die(f"{manifest_path}.routing.pipeline.options.{opt_name}", "must be string")
            if opt_val not in allowed_options[opt_name]:
                _die(
                    f"{manifest_path}.routing.pipeline.options.{opt_name}",
                    f"must be one of: {', '.join(sorted(allowed_options[opt_name]))}",
                )

        intent = routing.get("intent")
        if isinstance(intent, str):
            group = _pipeline_name_for_intent(cfg, intent)
            if group is not None:
                profile_name = pipeline.get("profile")
                if profile_name and profile_name not in cfg["pipelines"][group]["profiles"]:
                    _die(
                        f"{manifest_path}.routing.pipeline.profile",
                        f"profile '{profile_name}' is not defined in pipelines.{group}.profiles",
                    )


def load_manifest_if_present(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    return _load_yaml(path)


def build_choices_catalog(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "enums": {
            "codex_effort": sorted(CODEX_EFFORT_VALUES),
            "gemini_approval_mode": sorted(GEMINI_APPROVAL_VALUES),
            "timeout_mode": sorted(TIMEOUT_MODE_VALUES),
            "pipeline_options": {
                pipeline: {opt: sorted(values) for opt, values in opt_map.items()}
                for pipeline, opt_map in PIPELINE_OPTIONS.items()
            },
            "pipeline_flags": {
                pipeline: sorted(flags) for pipeline, flags in PIPELINE_FLAGS.items()
            },
        },
        "servants": {
            tool: {
                "default_model": cfg["servants"][tool]["default_model"],
                "allowed_models": list(cfg["servants"][tool]["allowed_models"]),
                "wrapper_defaults": dict(cfg["servants"][tool].get("wrapper_defaults") or {}),
                "wrapper_allowed_keys": sorted(WRAPPER_DEFAULT_KEYS[tool]),
            }
            for tool in SERVANT_NAMES
        },
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate split config and optional manifest extensions")
    parser.add_argument("--config-root", required=True, help="Path to configs directory containing servant/ and pipeline/")
    parser.add_argument("--manifest", help="Optional path to manifest.yaml")
    parser.add_argument(
        "--print-choices",
        action="store_true",
        help="Print allowed enum choices/models as JSON (after successful validation)",
    )
    args = parser.parse_args()

    try:
        cfg = load_and_validate_split_config(args.config_root)
        manifest = load_manifest_if_present(args.manifest)
        validate_manifest_extensions(cfg, manifest, manifest_path=args.manifest or "manifest")
    except ValidationError as e:
        print(f"CONFIG VALIDATION ERROR: {e}", file=sys.stderr)
        return 1
    except yaml.YAMLError as e:
        print(f"CONFIG VALIDATION ERROR: YAML parse failed: {e}", file=sys.stderr)
        return 1

    if args.print_choices:
        json.dump(build_choices_catalog(cfg), sys.stdout, indent=2, sort_keys=True)
        print("")
        return 0

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
