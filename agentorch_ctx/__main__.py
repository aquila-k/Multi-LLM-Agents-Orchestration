#!/usr/bin/env python3
"""agentorch CLI.

Usage:
    python3 -m agentorch_ctx <subcommand> [options]

Subcommands:
    version    Show agentorch version
    doctor     Check provider CLIs and Python dependencies
    bootstrap  Set up global environment
    init       Initialize a repository (collab + context DB)
    collab     Orchestration workflows (init, plan, impl, review, harden, resume)
    task       Task registry namespace
    ctx        Context management namespace
"""

from __future__ import annotations

import argparse
import importlib.metadata
import shutil
import sys
from pathlib import Path

_COLLAB_RUN_INTENTS = ("plan", "impl", "review", "harden", "resume")
_COLLAB_RUN_INTENT_HELP = {
    "plan": "Generate a plan from a source document",
    "impl": "Implement changes from a source document",
    "review": "Review the codebase against source criteria",
    "harden": "Apply hardening based on source criteria",
    "resume": "Resume a blocked task",
}


def _status_prefix(ok: bool, use_color: bool) -> str:
    if use_color:
        return "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
    return "[OK]" if ok else "[FAIL]"


def _find_cli(name: str) -> tuple[str | None, str | None]:
    path = shutil.which(name)
    if path:
        return path, "PATH"

    nvm_candidates = sorted(Path.home().glob(f".nvm/versions/node/*/bin/{name}"))
    if nvm_candidates:
        return str(nvm_candidates[-1].expanduser().resolve()), "NVM"

    return None, None


def _add_run_options(
    parser: argparse.ArgumentParser, *, include_with_harden: bool = False
) -> None:
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
            "Repo root directory (default: auto-detected from CWD by walking "
            "up to find AGENTS.md or .git). "
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
    if include_with_harden:
        parser.add_argument(
            "--with-harden",
            action="store_true",
            help="Compose review + harden in a single run. "
            "Prefer embedding phase_options.with_harden in a JSON source file.",
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentorch",
        description="agentorch runtime CLI",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    parser_version = subparsers.add_parser("version", help="Show agentorch version")
    parser_version.set_defaults(func=cmd_version)

    parser_doctor = subparsers.add_parser(
        "doctor", help="Check provider CLIs and Python dependencies"
    )
    parser_doctor.set_defaults(func=cmd_doctor)

    parser_bootstrap = subparsers.add_parser(
        "bootstrap", help="Set up global environment"
    )
    parser_bootstrap.add_argument(
        "--verbose",
        action="store_true",
        help="Show more detail about each check",
    )
    parser_bootstrap.set_defaults(func=cmd_bootstrap)

    parser_init = subparsers.add_parser(
        "init",
        help="Initialize a repository for agentorch (collab + context DB)",
    )
    parser_init.add_argument(
        "--dir",
        default=None,
        metavar="PATH",
        help="Repository root to initialize (default: current directory)",
    )
    parser_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configs and wrapper if present",
    )
    parser_init.set_defaults(func=cmd_init)

    parser_migrate = subparsers.add_parser(
        "migrate",
        help="Migrate from legacy collab/ layout to .agentorch/",
    )
    parser_migrate.add_argument(
        "--dir",
        default=None,
        metavar="PATH",
        help="Repository root to migrate (default: current directory)",
    )
    parser_migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser_migrate.set_defaults(func=cmd_migrate)

    p_collab = subparsers.add_parser(
        "collab",
        help="Orchestration - run plan/impl/review/harden/resume workflows",
        description=(
            "Orchestration subcommands.\n\n"
            "Usage:\n"
            "  agentorch collab init      Initialize collab configs in this repo\n"
            "  agentorch collab plan      Generate a plan from a source document\n"
            "  agentorch collab impl      Implement changes from a source document\n"
            "  agentorch collab review    Review codebase against source criteria\n"
            "  agentorch collab harden    Apply hardening based on source criteria\n"
            "  agentorch collab resume    Resume a blocked task\n"
        ),
    )
    sub_collab = p_collab.add_subparsers(dest="collab_subcommand", metavar="subcommand")
    sub_collab.required = True

    p_collab_init = sub_collab.add_parser(
        "init", help="Initialize collab configs in this repo"
    )
    p_collab_init.add_argument(
        "--dir",
        default=None,
        metavar="PATH",
        help="Repository root to initialize (default: current directory)",
    )
    p_collab_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configs and wrapper if present",
    )

    for intent in _COLLAB_RUN_INTENTS:
        parser_intent = sub_collab.add_parser(
            intent, help=_COLLAB_RUN_INTENT_HELP[intent]
        )
        _add_run_options(parser_intent, include_with_harden=(intent == "review"))

    p_ctx = subparsers.add_parser(
        "ctx",
        help="Context management — manage task memory, decisions, and knowledge base",
        description=(
            "Context management subcommands. All arguments after 'ctx' are passed directly "
            "to the contexts runtime.\n\n"
            "Common commands:\n"
            "  agentorch ctx init               Initialize context DB in current repo\n"
            "  agentorch ctx doctor             Run diagnostic checks\n"
            "  agentorch ctx get-task-context   Get task context\n"
            "  agentorch ctx search-memory      Search context memory\n"
            "  agentorch ctx update-task-context Update task snapshot\n"
            "  agentorch ctx --help             List all available subcommands\n"
        ),
        add_help=False,
    )
    p_ctx.add_argument(
        "-h",
        "--help",
        action="store_true",
        dest="ctx_help",
        help=argparse.SUPPRESS,
    )
    p_ctx.add_argument(
        "ctx_args", nargs=argparse.REMAINDER, help="ctx subcommand and arguments"
    )

    p_task = subparsers.add_parser(
        "task",
        help="Task registry - track active tasks and provider participation",
    )
    sub_task = p_task.add_subparsers(dest="task_subcommand", metavar="subcommand")
    sub_task.required = True

    p_task_create = sub_task.add_parser("create", help="Create a new task")
    p_task_create.add_argument(
        "--summary", required=True, help="Human-readable task summary"
    )
    p_task_create.add_argument(
        "--task-id",
        default=None,
        help="Explicit task ID override (default: generated from summary)",
    )
    p_task_create.add_argument(
        "--parent",
        default=None,
        metavar="TASK_ID",
        help="Optional parent task ID",
    )
    p_task_create.add_argument(
        "--provider",
        default=None,
        help="Provider or agent participating in this task",
    )
    p_task_create.add_argument(
        "--collab-ref",
        default=None,
        metavar="TASK_ID",
        help="Linked collab task ID, if any",
    )
    p_task_create.set_defaults(func=cmd_task)

    p_task_current = sub_task.add_parser("current", help="Show the current active task")
    p_task_current.add_argument(
        "--provider",
        default=None,
        help="Filter to active tasks involving this provider",
    )
    p_task_current.set_defaults(func=cmd_task)

    p_task_list = sub_task.add_parser("list", help="List tasks")
    p_task_list.add_argument(
        "--status",
        default="all",
        choices=["active", "paused", "completed", "failed", "blocked", "all"],
        help="Filter by status (default: all)",
    )
    p_task_list.add_argument(
        "--parent",
        default=None,
        metavar="TASK_ID",
        help="Filter to child tasks of the given parent",
    )
    p_task_list.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum tasks to return (default: 20)",
    )
    p_task_list.set_defaults(func=cmd_task)

    p_task_status = sub_task.add_parser("status", help="Update a task status")
    p_task_status.add_argument("task_id", help="Task ID to update")
    p_task_status.add_argument(
        "--set",
        dest="set_status",
        required=True,
        choices=["active", "paused", "completed", "failed", "blocked"],
        help="New task status",
    )
    p_task_status.set_defaults(func=cmd_task)

    p_task_join = sub_task.add_parser("join", help="Join a provider to a task")
    p_task_join.add_argument("task_id", help="Task ID to join")
    p_task_join.add_argument(
        "--provider",
        required=True,
        help="Provider or agent name",
    )
    p_task_join.add_argument(
        "--role",
        default="worker",
        choices=["orchestrator", "worker"],
        help="Participant role (default: worker)",
    )
    p_task_join.set_defaults(func=cmd_task)

    p_task_show = sub_task.add_parser("show", help="Show a task")
    p_task_show.add_argument("task_id", help="Task ID to show")
    p_task_show.set_defaults(func=cmd_task)

    p_task_check = sub_task.add_parser(
        "check", help="Find stale active tasks whose PID is no longer running"
    )
    p_task_check.set_defaults(func=cmd_task)

    return parser


def cmd_version(_: argparse.Namespace) -> int:
    try:
        version = importlib.metadata.version("agentorch-ctx")
    except Exception:
        version = "0.1.0"
    print(f"agentorch {version}")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    use_color = sys.stdout.isatty()
    checks: list[tuple[str, bool, str]] = []

    py_ok = sys.version_info >= (3, 11)
    checks.append(
        (
            "Python >= 3.11",
            py_ok,
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )

    try:
        import yaml  # type: ignore[import-not-found]  # noqa: F401

        checks.append(("pyyaml importable", True, "import yaml succeeded"))
    except Exception as exc:
        checks.append(("pyyaml importable", False, f"import yaml failed: {exc}"))

    for cli in ("gemini", "codex", "copilot"):
        cli_path, source = _find_cli(cli)
        if cli_path:
            detail = cli_path if source == "PATH" else f"{cli_path} (from ~/.nvm)"
            checks.append((f"{cli} CLI", True, detail))
        else:
            checks.append(
                (
                    f"{cli} CLI",
                    False,
                    f"not found on PATH or ~/.nvm/versions/node/*/bin/{cli}",
                )
            )

    passed = 0
    for name, ok, detail in checks:
        if ok:
            passed += 1
        print(f"{_status_prefix(ok, use_color)} {name}: {detail}")

    all_ok = passed == len(checks)
    print(
        f"{_status_prefix(all_ok, use_color)} Summary: {passed}/{len(checks)} checks passed"
    )
    return 0 if all_ok else 1


def cmd_bootstrap(args: argparse.Namespace) -> int:
    from agentorch_ctx.cli.cmd_bootstrap import run as bootstrap_run

    return bootstrap_run(verbose=getattr(args, "verbose", False))


def cmd_init(args: argparse.Namespace) -> int:
    from agentorch_ctx.cli.cmd_full_init import run as full_init_run

    target = Path(args.dir).expanduser().resolve() if args.dir else None
    return full_init_run(target_dir=target, force=args.force)


def cmd_migrate(args: argparse.Namespace) -> int:
    from agentorch_ctx.cli.cmd_migrate import run as migrate_run

    target = Path(args.dir).expanduser().resolve() if args.dir else None
    return migrate_run(target_dir=target, dry_run=args.dry_run)


def cmd_run(args: argparse.Namespace, intent_override: str | None = None) -> int:
    intent = intent_override or args.intent

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"error: source file not found: {source_path}", file=sys.stderr)
        return 2

    # Root is auto-detected by walking up from CWD.  --root is an escape hatch.
    from agentorch_ctx.runtime.pathing import resolve_repo_root

    try:
        root_dir = (
            resolve_repo_root()
            if args.root is None
            else Path(args.root).expanduser().resolve()
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not root_dir.is_dir():
        print(f"error: root directory not found: {root_dir}", file=sys.stderr)
        return 2

    source_kind = "json" if source_path.suffix.lower() == ".json" else "markdown"
    live_mode = not args.dry_run

    # Append (not insert) to avoid shadowing stdlib modules with repo files.
    if str(root_dir) not in sys.path:
        sys.path.append(str(root_dir))

    from agentorch_ctx.runtime.claude_code_skill import ClaudeCodeSkill
    from agentorch_ctx.runtime.phase_runner import PhaseRunner

    # CLI flags are merged on top of whatever the JSON source already contains.
    # Prefer the JSON source for structured options; flags are a convenience override.
    selectors: dict = {}
    if args.strategy:
        selectors["strategy"] = args.strategy

    phase_options: dict = {}
    if getattr(args, "with_harden", False):
        if intent != "review":
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
            workflow_intent=intent,
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

    from agentorch_ctx.runtime.pathing import task_artifacts_dir

    artifacts_dir = task_artifacts_dir(root_dir, result.task_id)

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


def cmd_collab(args: argparse.Namespace) -> int:
    collab_sub = args.collab_subcommand
    if collab_sub == "init":
        from agentorch_ctx.cli.cmd_full_init import run_collab_init

        target = (Path(args.dir).expanduser().resolve() if args.dir else Path.cwd().resolve())
        return run_collab_init(target, force=args.force)
    return cmd_run(args, intent_override=collab_sub)


def cmd_ctx(args: argparse.Namespace) -> int:
    """Delegate to the contexts runtime. For 'ctx init', use the extended init."""
    forwarded_args = list(args.ctx_args or [])
    if getattr(args, "ctx_help", False):
        forwarded_args.insert(0, "--help")

    # Intercept 'ctx init' to run the extended version with agent instructions
    if forwarded_args and forwarded_args[0] == "init":
        from agentorch_ctx.cli.cmd_full_init import run_ctx_init
        from agentorch_ctx.runtime.pathing import resolve_repo_root

        try:
            repo_root = resolve_repo_root()
        except FileNotFoundError:
            repo_root = Path.cwd().resolve()
        force = "--force" in forwarded_args
        return run_ctx_init(repo_root, force=force)

    from agentorch_ctx.contexts.__main__ import main as ctx_main

    saved_argv = sys.argv
    sys.argv = ["agentorch ctx"] + forwarded_args
    try:
        try:
            result = ctx_main()
            return result if isinstance(result, int) else 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.argv = saved_argv


def cmd_task(args: argparse.Namespace) -> int:
    """Delegate to the task registry CLI."""
    from agentorch_ctx.task_registry.cli import (
        cmd_task_check,
        cmd_task_create,
        cmd_task_current,
        cmd_task_join,
        cmd_task_list,
        cmd_task_show,
        cmd_task_status,
    )

    handlers = {
        "create": cmd_task_create,
        "current": cmd_task_current,
        "list": cmd_task_list,
        "status": cmd_task_status,
        "join": cmd_task_join,
        "show": cmd_task_show,
        "check": cmd_task_check,
    }
    return handlers[args.task_subcommand](args)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.subcommand == "collab":
        return cmd_collab(args)
    if args.subcommand == "ctx":
        return cmd_ctx(args)
    if args.subcommand == "task":
        return cmd_task(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
