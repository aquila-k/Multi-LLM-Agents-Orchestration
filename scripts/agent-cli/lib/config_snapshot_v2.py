#!/usr/bin/env python3
"""Generate a markdown snapshot for Config V2."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from config_validate_v2 import (  # type: ignore
    PHASES,
    TOOLS,
    ValidationError,
    load_and_validate_v2_config,
)


def _render_skill_phase(phase: str, node: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"### `{phase}`")
    lines.append(f"- source: `configs-v2/skills/{phase}.yaml`")
    lines.append(
        f"- default_method_ids: `{json.dumps(node.get('default_method_ids') or [], ensure_ascii=False)}`"
    )
    lines.append("- methods:")
    for method_id, method_node in (node.get("methods") or {}).items():
        enabled = method_node.get("enabled")
        steps = method_node.get("steps") or []
        allowed_tools = method_node.get("allowed_tools") or []
        gate_profile = method_node.get("gate_profile")
        lines.append(
            f"  - `{method_id}` enabled=`{enabled}` gate_profile=`{gate_profile}` "
            f"steps=`{json.dumps(steps, ensure_ascii=False)}` allowed_tools=`{json.dumps(allowed_tools, ensure_ascii=False)}`"
        )
    lines.append("- step_defaults:")
    for step_id, step_node in (node.get("step_defaults") or {}).items():
        desc = step_node.get("description", "")
        desc_part = f" — {desc}" if desc else ""
        lines.append(
            f"  - `{step_id}`{desc_part} tool=`{step_node.get('default_tool')}` "
            f"mode=`{step_node.get('default_mode')}` "
            f"web_research_mode=`{step_node.get('web_research_mode')}`"
        )
    return "\n".join(lines)


def _render_servant(tool: str, node: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"### `{tool}`")
    lines.append(f"- source: `configs-v2/servants/{tool}.yaml`")
    lines.append(f"- default_model: `{node.get('default_model')}`")
    lines.append(
        f"- allowed_models: `{json.dumps(node.get('allowed_models') or [], ensure_ascii=False)}`"
    )
    wrapper_defaults = node.get("wrapper_defaults") or {}
    lines.append(
        f"- wrapper_defaults: `{json.dumps(wrapper_defaults, ensure_ascii=False)}`"
    )
    modes = (node.get("web_capabilities") or {}).get("modes") or []
    lines.append(f"- web_modes: `{json.dumps(modes, ensure_ascii=False)}`")
    return "\n".join(lines)


def _render_policies(policies: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("## Policies")
    lines.append("")

    routing = policies["routing"]
    lines.append("### `routing`")
    lines.append("- source: `configs-v2/policies/routing.yaml`")
    lines.append(
        "- stop_policy.conditions: "
        f"`{json.dumps((routing.get('stop_policy') or {}).get('conditions') or [], ensure_ascii=False)}`"
    )
    lines.append(
        f"- stop_policy.on_stop: `{(routing.get('stop_policy') or {}).get('on_stop')}`"
    )
    lines.append(
        "- confidence_policy: "
        f"`{json.dumps(routing.get('confidence_policy') or {}, ensure_ascii=False)}`"
    )
    lines.append(
        "- hard_stop_reason_map keys: "
        f"`{json.dumps(sorted((routing.get('hard_stop_reason_map') or {}).keys()), ensure_ascii=False)}`"
    )
    lines.append(
        "- reproducibility_policy: "
        f"`{json.dumps(routing.get('reproducibility_policy') or {}, ensure_ascii=False)}`"
    )
    lines.append(
        "- route_decider_policy: "
        f"`{json.dumps(routing.get('route_decider_policy') or {}, ensure_ascii=False)}`"
    )
    lines.append("")

    review_parallel = policies["review_parallel"]
    lines.append("### `review_parallel`")
    lines.append("- source: `configs-v2/policies/review_parallel.yaml`")
    lines.append(f"- config: `{json.dumps(review_parallel, ensure_ascii=False)}`")
    lines.append("")

    web_evidence = policies["web_evidence"]
    lines.append("### `web_evidence`")
    lines.append("- source: `configs-v2/policies/web_evidence.yaml`")
    lines.append(f"- config: `{json.dumps(web_evidence, ensure_ascii=False)}`")

    return "\n".join(lines)


def render_snapshot(cfg: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Config V2 Snapshot")
    lines.append("")
    lines.append("> Auto-generated summary of the current configs-v2 state.")
    lines.append("")
    lines.append(f"- config_root: `{cfg.get('root')}`")
    lines.append(f"- version: `{cfg.get('version')}`")
    lines.append("")

    lines.append("## Skills")
    lines.append("")
    for phase in PHASES:
        lines.append(_render_skill_phase(phase, cfg["skills"][phase]))
        lines.append("")

    lines.append("## Servants")
    lines.append("")
    for tool in TOOLS:
        lines.append(_render_servant(tool, cfg["servants"][tool]))
        lines.append("")

    lines.append(_render_policies(cfg["policies"]))
    lines.append("")
    return "\n".join(lines)


def _write_output(path: str, content: str) -> None:
    abs_path = os.path.abspath(path)
    directory = os.path.dirname(abs_path)
    os.makedirs(directory, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Generate Config V2 markdown snapshot")
    parser.add_argument(
        "--config-root", required=True, help="Path to configs-v2 directory"
    )
    parser.add_argument("--output", help="Optional output markdown file path")
    args = parser.parse_args()

    try:
        cfg = load_and_validate_v2_config(args.config_root)
        snapshot = render_snapshot(cfg)
    except ValidationError as e:
        print(f"CONFIG V2 SNAPSHOT ERROR: {e}", file=sys.stderr)
        return 1

    if args.output:
        _write_output(args.output, snapshot)

    sys.stdout.write(snapshot)
    if not snapshot.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
