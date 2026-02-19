#!/usr/bin/env python3
"""Generate human-facing config snapshots from split config files."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from typing import Any, Dict, List, Tuple

import yaml

from config_validate import (  # type: ignore
    ValidationError,
    build_choices_catalog,
    load_and_validate_split_config,
)


def _write_atomic(path: str, content: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".cfgsnapshot.", suffix=".tmp", dir=directory, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass


def _dump_yaml(cfg: Dict[str, Any]) -> str:
    header = (
        "# AUTO-GENERATED FILE. DO NOT EDIT.\n"
        "# Runtime source of truth is split config under:\n"
        "#   - configs/servant/*.yaml\n"
        "#   - configs/pipeline/*.yaml\n"
        "# This file is a read-only snapshot for humans.\n"
    )
    body = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=False)
    return header + body


def _provider_section(tool: str, node: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"### `{tool}`")
    lines.append(f"- Edit file: [configs/servant/{tool}.yaml](servant/{tool}.yaml)")
    lines.append(f"- `default_model`: `{node['default_model']}`")
    wrapper = node.get("wrapper_defaults") or {}
    lines.append(f"- `wrapper_defaults`: `{json.dumps(wrapper, ensure_ascii=False)}`")
    lines.append("- `allowed_models`:")
    for m in node.get("allowed_models") or []:
        lines.append(f"  - `{m}`")
    purpose_models = node.get("purpose_models") or {}
    if purpose_models:
        lines.append("- `purpose_models`:")
        for purpose in ("impl", "review", "verify", "plan", "one_shot"):
            if purpose in purpose_models:
                lines.append(f"  - `{purpose}` -> `{purpose_models[purpose]}`")
    purpose_efforts = node.get("purpose_efforts") or {}
    if purpose_efforts:
        lines.append("- `purpose_efforts`:")
        for purpose in ("impl", "review", "verify", "plan", "one_shot"):
            if purpose in purpose_efforts:
                lines.append(f"  - `{purpose}` -> `{purpose_efforts[purpose]}`")
    return "\n".join(lines)


def _profile_summary(
    profile: str, node: Dict[str, Any], pipeline_name: str
) -> List[str]:
    lines: List[str] = []
    lines.append(f"#### `{profile}`")
    stages = node.get("stages") or []
    if pipeline_name in {"impl", "review"}:
        lines.append(f"- `stages`: `{json.dumps(stages, ensure_ascii=False)}`")
    flags = node.get("flags") or {}
    options = node.get("options") or {}
    stage_models = node.get("stage_models") or {}
    stage_efforts = node.get("stage_efforts") or {}
    lines.append(f"- `flags`: `{json.dumps(flags, ensure_ascii=False)}`")
    lines.append(f"- `options`: `{json.dumps(options, ensure_ascii=False)}`")
    if stage_models:
        lines.append("- `stage_models`:")
        for stage, model in stage_models.items():
            lines.append(f"  - `{stage}` -> `{model}`")
    if stage_efforts:
        lines.append("- `stage_efforts`:")
        for stage, effort in stage_efforts.items():
            lines.append(f"  - `{stage}` -> `{effort}`")
    return lines


def _pipeline_section(name: str, node: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"### `{name}`")
    lines.append(
        f"- Edit file: [configs/pipeline/{name}-pipeline.yaml](pipeline/{name}-pipeline.yaml)"
    )
    lines.append(f"- `default_profile`: `{node['default_profile']}`")
    profiles = node.get("profiles") or {}
    for profile_name, profile_node in profiles.items():
        lines.extend(_profile_summary(profile_name, profile_node, name))
    return "\n".join(lines)


def _edit_map_rows() -> List[Tuple[str, str]]:
    return [
        ("Codex provider settings", "[configs/servant/codex.yaml](servant/codex.yaml)"),
        (
            "Gemini provider settings",
            "[configs/servant/gemini.yaml](servant/gemini.yaml)",
        ),
        (
            "Copilot provider settings",
            "[configs/servant/copilot.yaml](servant/copilot.yaml)",
        ),
        (
            "Impl pipeline profiles/options",
            "[configs/pipeline/impl-pipeline.yaml](pipeline/impl-pipeline.yaml)",
        ),
        (
            "Review pipeline profiles/options",
            "[configs/pipeline/review-pipeline.yaml](pipeline/review-pipeline.yaml)",
        ),
        (
            "Plan pipeline profiles/options",
            "[configs/pipeline/plan-pipeline.yaml](pipeline/plan-pipeline.yaml)",
        ),
        (
            "Task-level one-off overrides",
            "`<task>/manifest.yaml` (`routing.model.*`, `routing.pipeline.*`)",
        ),
        (
            "Allowed option enums and validation rules",
            "[scripts/agent-cli/lib/config_validate.py](../scripts/agent-cli/lib/config_validate.py)",
        ),
    ]


def _choices_section(choices: Dict[str, Any]) -> str:
    enums = choices["enums"]
    lines: List[str] = []
    lines.append("## Configurable Options (Current Allowed Values)")
    lines.append("")
    lines.append(
        f"- `codex_effort`: `{json.dumps(enums['codex_effort'], ensure_ascii=False)}`"
    )
    lines.append(
        f"- `gemini_approval_mode`: `{json.dumps(enums['gemini_approval_mode'], ensure_ascii=False)}`"
    )
    lines.append(
        f"- `timeout_mode`: `{json.dumps(enums['timeout_mode'], ensure_ascii=False)}`"
    )
    lines.append("")
    lines.append("### Pipeline Options")
    for pipeline, opt_map in enums["pipeline_options"].items():
        lines.append(f"- `{pipeline}`:")
        for opt, vals in opt_map.items():
            lines.append(f"  - `{opt}`: `{json.dumps(vals, ensure_ascii=False)}`")
    lines.append("")
    lines.append("### Pipeline Flags")
    for pipeline, flags in enums["pipeline_flags"].items():
        lines.append(f"- `{pipeline}`: `{json.dumps(flags, ensure_ascii=False)}`")
    return "\n".join(lines)


def _render_markdown(cfg: Dict[str, Any]) -> str:
    choices = build_choices_catalog(cfg)
    lines: List[str] = []
    lines.append("# Config State Snapshot")
    lines.append("")
    lines.append("> AUTO-GENERATED. DO NOT EDIT.")
    lines.append("")
    lines.append(
        "This document is a read-only view of current effective split configuration."
    )
    lines.append("Runtime source of truth:")
    lines.append("- `configs/servant/*.yaml`")
    lines.append("- `configs/pipeline/*.yaml`")
    lines.append("")
    lines.append("Snapshot files:")
    lines.append("- `configs/config-state.yaml`")
    lines.append("- `configs/config-state.md`")
    lines.append("")
    lines.append("## Where To Change Settings")
    lines.append("")
    lines.append("| What you want to change | Edit this file |")
    lines.append("| --- | --- |")
    for k, v in _edit_map_rows():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append(_choices_section(choices))
    lines.append("")
    lines.append("## Current Provider State")
    lines.append("")
    for tool in ("codex", "gemini", "copilot"):
        lines.append(_provider_section(tool, cfg["servants"][tool]))
        lines.append("")
    lines.append("## Current Pipeline State")
    lines.append("")
    for pipeline in ("impl", "review", "plan"):
        lines.append(_pipeline_section(pipeline, cfg["pipelines"][pipeline]))
        lines.append("")
    lines.append("## Validation Command")
    lines.append("")
    lines.append("```bash")
    lines.append(
        "python3 scripts/agent-cli/lib/config_validate.py --config-root configs"
    )
    lines.append(
        "python3 scripts/agent-cli/lib/config_validate.py --config-root configs --print-choices"
    )
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Generate read-only config snapshots")
    parser.add_argument(
        "--config-root", required=True, help="Path to configs directory"
    )
    parser.add_argument("--yaml-out", help="Output path for YAML snapshot")
    parser.add_argument("--md-out", help="Output path for Markdown snapshot")
    args = parser.parse_args()

    cfg = load_and_validate_split_config(args.config_root)

    root = os.path.abspath(args.config_root)
    yaml_out = args.yaml_out or os.path.join(root, "config-state.yaml")
    md_out = args.md_out or os.path.join(root, "config-state.md")

    _write_atomic(yaml_out, _dump_yaml(cfg))
    _write_atomic(md_out, _render_markdown(cfg))
    for legacy in ("orchestrator.yaml", "orchestrator.md"):
        legacy_path = os.path.join(root, legacy)
        if os.path.exists(legacy_path):
            os.unlink(legacy_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except ValidationError as e:
        raise SystemExit(f"CONFIG SNAPSHOT ERROR: {e}")
