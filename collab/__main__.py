#!/usr/bin/env python3
"""Collab runtime CLI.

Usage:
    python3 -m collab <intent> --source <file> [options]

Intents:
    plan      Generate a plan from the source document
    impl      Implement changes described in the source document
    review    Review the codebase against the source criteria
    harden    Apply security hardening based on the source criteria
    resume    Resume a blocked task (source must be a JSON resume payload)

Options:
    --source PATH      Path to the task source file (markdown or JSON)
    --root PATH        Repo root directory (auto-detected from script location)
    --strategy ID      Override the routing strategy selector
    --dry-run          Run in stub mode (no provider CLI calls)
    --with-harden      Compose review + harden in a single run (review intent only)

Source file formats:
    Markdown (.md)  — freeform goal description; all options use defaults
    JSON (.json)    — structured payload with inline selectors/targets/constraints

JSON source schema (all fields optional except summary):
    {
      "summary": "Brief description of the task",
      "selectors": { "strategy": "COLLAB_PLAN_FULL" },
      "targets":   { "path": "src/auth/" },
      "constraints": {},
      "phase_options": { "with_harden": false }
    }

Exit codes:
    0  Task dispatched and phase completed (or blocked awaiting approval)
    1  Validation or execution error
    2  Argument error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Repo root is always two levels up from this file: collab/__main__.py → collab/ → repo root.
# This is resolved relative to the script itself, not CWD, so it is correct regardless of
# where the caller invokes python3 -m collab from.
_AUTO_ROOT = Path(__file__).resolve().parent.parent

_INTENTS = {"plan", "impl", "review", "harden", "resume"}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m collab",
        description="Collab runtime — orchestrate LLM provider CLIs for plan/impl/review/harden tasks.",
    )
    parser.add_argument(
        "intent",
        choices=sorted(_INTENTS),
        help="Workflow intent: plan, impl, review, harden, or resume",
    )
    parser.add_argument(
        "--source",
        required=True,
        metavar="PATH",
        help="Path to the task source file (.md for markdown, .json for structured payload)",
    )
    parser.add_argument(
        "--root",
        default=None,
        metavar="PATH",
        help=(
            f"Repo root directory (default: auto-detected as {_AUTO_ROOT}). "
            "Override only if running from outside the project tree."
        ),
    )
    parser.add_argument(
        "--strategy",
        default=None,
        metavar="ID",
        help="Override routing strategy selector (e.g. COLLAB_PLAN_FULL). "
        "Prefer embedding selectors.strategy in a JSON source file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stub mode: build all artifacts without calling provider CLIs",
    )
    parser.add_argument(
        "--with-harden",
        action="store_true",
        help="Compose review + harden in a single run (only valid with review intent). "
        "Prefer embedding phase_options.with_harden in a JSON source file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"error: source file not found: {source_path}", file=sys.stderr)
        return 2

    # Root is always auto-detected from the script's own location. --root is an escape hatch.
    root_dir = (
        _AUTO_ROOT if args.root is None else Path(args.root).expanduser().resolve()
    )
    if not root_dir.is_dir():
        print(f"error: root directory not found: {root_dir}", file=sys.stderr)
        return 2

    source_kind = "json" if source_path.suffix.lower() == ".json" else "markdown"
    live_mode = not args.dry_run

    sys.path.insert(0, str(root_dir))

    from collab.runtime.claude_code_skill import ClaudeCodeSkill
    from collab.runtime.phase_runner import PhaseRunner

    # CLI flags are merged on top of whatever the JSON source already contains.
    # Prefer the JSON source for structured options; flags are a convenience override.
    selectors: dict = {}
    if args.strategy:
        selectors["strategy"] = args.strategy

    phase_options: dict = {}
    if args.with_harden:
        if args.intent != "review":
            print(
                "error: --with-harden is only valid with the 'review' intent",
                file=sys.stderr,
            )
            return 2
        phase_options["with_harden"] = True

    try:
        skill = ClaudeCodeSkill(root_dir=root_dir)
        dispatch = skill.dispatch(
            source_path=source_path,
            workflow_intent=args.intent,
            source_kind=source_kind,
            selectors=selectors or None,
            phase_options=phase_options or None,
        )
    except Exception as exc:
        print(f"error: dispatch failed: {exc}", file=sys.stderr)
        return 1

    if dispatch.stop_and_confirm:
        print(dispatch.shell_summary)
        print()
        print("STOP_AND_CONFIRM: operator approval required before execution proceeds.")
        print(f"task_id:   {dispatch.task_id}")
        print(f"state:     {dispatch.controller_state_path}")
        return 0

    try:
        runner = PhaseRunner(root_dir, live_mode=live_mode)
        result = runner.run(request_path=dispatch.request_path)
    except Exception as exc:
        print(f"error: phase execution failed: {exc}", file=sys.stderr)
        return 1

    artifacts_dir = root_dir / "collab" / "artifacts" / "tasks" / result.task_id

    print(f"task_id:   {result.task_id}")
    print(
        f"phases:    {', '.join(result.executed_phases) if result.executed_phases else '(none)'}"
    )
    print(f"status:    {result.controller_status}")
    print(f"artifacts: {artifacts_dir}")
    print(f"run_log:   {result.phase_run_path}")
    if result.pause_confirm_path:
        print(f"paused:    {result.pause_confirm_path}")

    if result.controller_status == "blocked":
        print()
        print("STOP_AND_CONFIRM: task paused awaiting operator approval.")
        return 0

    return 0 if result.controller_status in {"running", "succeeded", "partial"} else 1


if __name__ == "__main__":
    sys.exit(main())
