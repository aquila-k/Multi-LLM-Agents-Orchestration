#!/usr/bin/env python3
"""Audit prompt profile coverage against configured pipeline profiles."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import yaml

PhasePromptSet = Dict[str, Dict[str, Set[Tuple[str, str]]]]

PHASES = ("plan", "impl", "review")
PLAN_PROMPT_MAP = {
    "copilot_draft": ("copilot", "draft"),
    "codex_enrich": ("shared", "enrich"),
    "gemini_enrich": ("shared", "enrich"),
    "codex_cross_review": ("shared", "cross_review"),
    "gemini_cross_review": ("shared", "cross_review"),
    "copilot_consolidate": ("copilot", "consolidate"),
}


class AuditError(Exception):
    """Raised for structural audit errors."""


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        raise AuditError(f"missing config file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - parser messages vary
        raise AuditError(f"failed to parse YAML at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AuditError(f"top-level YAML must be a mapping: {path}")
    return data


def _collect_expected_profiles(config_root: Path) -> PhasePromptSet:
    expected: PhasePromptSet = {phase: {} for phase in PHASES}

    for phase in PHASES:
        pipeline_file = config_root / "pipeline" / f"{phase}-pipeline.yaml"
        pipeline_cfg = _load_yaml(pipeline_file)
        profiles = pipeline_cfg.get("profiles")
        if not isinstance(profiles, dict):
            raise AuditError(f"{pipeline_file}: 'profiles' must be a mapping")

        for profile_name, profile_cfg in profiles.items():
            if not isinstance(profile_name, str):
                raise AuditError(f"{pipeline_file}: profile name must be string")
            if not isinstance(profile_cfg, dict):
                raise AuditError(
                    f"{pipeline_file}: profile '{profile_name}' must be a mapping"
                )

            required: Set[Tuple[str, str]] = set()
            if phase in {"impl", "review"}:
                stages = profile_cfg.get("stages")
                if not isinstance(stages, list) or not stages:
                    raise AuditError(
                        f"{pipeline_file}: profile '{profile_name}' must define non-empty stages"
                    )
                for stage in stages:
                    if not isinstance(stage, str) or "_" not in stage:
                        raise AuditError(
                            f"{pipeline_file}: invalid stage '{stage}' in profile '{profile_name}'"
                        )
                    tool, role = stage.split("_", 1)
                    required.add((tool, role))
            else:
                stage_models = profile_cfg.get("stage_models")
                if isinstance(stage_models, dict):
                    for stage_name in stage_models:
                        if stage_name not in PLAN_PROMPT_MAP:
                            raise AuditError(
                                f"{pipeline_file}: unsupported plan stage '{stage_name}' in profile '{profile_name}'"
                            )
                # Plan pipeline prompt contract is fixed to these 4 templates.
                required.update(
                    {
                        ("copilot", "draft"),
                        ("shared", "enrich"),
                        ("shared", "cross_review"),
                        ("copilot", "consolidate"),
                    }
                )

            expected[phase][profile_name] = required

    return expected


def _default_prompt_path(prompts_root: Path, tool: str, role: str) -> Path:
    if tool == "shared":
        return prompts_root / "plan" / f"{role}.md"
    return prompts_root / tool / f"{role}.md"


def _scan_profile_files(profile_dir: Path) -> Set[Tuple[str, str]]:
    found: Set[Tuple[str, str]] = set()
    if not profile_dir.is_dir():
        return found
    for md_file in profile_dir.rglob("*.md"):
        rel = md_file.relative_to(profile_dir).parts
        if len(rel) != 2:
            continue
        tool_dir, file_name = rel
        if not file_name.endswith(".md"):
            continue
        role = file_name[:-3]
        if role:
            found.add((tool_dir, role))
    return found


def run_audit(
    config_root: Path,
    prompts_root: Path,
    allow_default_fallback: bool,
) -> int:
    expected = _collect_expected_profiles(config_root)
    profiles_root = prompts_root / "profiles"

    missing: List[str] = []
    fallback_used: List[str] = []
    extra_templates: List[str] = []
    unknown_profiles: List[str] = []

    for phase in PHASES:
        configured_profiles = set(expected[phase].keys())
        phase_dir = profiles_root / phase

        if phase_dir.is_dir():
            for child in sorted(phase_dir.iterdir()):
                if not child.is_dir():
                    continue
                if child.name not in configured_profiles:
                    unknown_profiles.append(f"{phase}/{child.name}")

        for profile, required_prompts in sorted(expected[phase].items()):
            profile_dir = phase_dir / profile
            profile_templates = _scan_profile_files(profile_dir)

            for tool, role in sorted(required_prompts):
                profile_path = profile_dir / tool / f"{role}.md"
                if profile_path.is_file():
                    continue

                default_path = _default_prompt_path(prompts_root, tool, role)
                if allow_default_fallback and default_path.is_file():
                    fallback_used.append(
                        f"{phase}/{profile}: {tool}/{role}.md -> {default_path.relative_to(prompts_root)}"
                    )
                    continue

                missing.append(
                    f"{phase}/{profile}: missing {tool}/{role}.md "
                    f"(expected at {profile_path})"
                )

            for tool, role in sorted(profile_templates - required_prompts):
                extra_templates.append(f"{phase}/{profile}: unused {tool}/{role}.md")

    if missing:
        print("PROMPT PROFILE AUDIT: FAILED")
        for item in missing:
            print(f"  - {item}")
        return 1

    print("PROMPT PROFILE AUDIT: OK")
    if fallback_used:
        print("Fallbacks used:")
        for item in fallback_used:
            print(f"  - {item}")
    if unknown_profiles:
        print("Unknown profile directories:")
        for item in unknown_profiles:
            print(f"  - {item}")
    if extra_templates:
        print("Unused profile templates:")
        for item in extra_templates:
            print(f"  - {item}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-root",
        required=True,
        help="Path to config root containing pipeline/*.yaml",
    )
    parser.add_argument(
        "--prompts-root",
        default="prompts-src",
        help="Path to prompts-src root (default: prompts-src)",
    )
    parser.add_argument(
        "--allow-default-fallback",
        action="store_true",
        help="Allow prompts-src/<tool>/<role>.md when profile override is missing",
    )
    return parser.parse_args()


def _main() -> int:
    args = _parse_args()
    try:
        return run_audit(
            config_root=Path(args.config_root).resolve(),
            prompts_root=Path(args.prompts_root).resolve(),
            allow_default_fallback=bool(args.allow_default_fallback),
        )
    except AuditError as exc:
        print(f"PROMPT PROFILE AUDIT ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
