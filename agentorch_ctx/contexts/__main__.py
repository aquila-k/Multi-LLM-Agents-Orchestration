"""CLI entrypoint for the contexts subsystem. Dispatches all 15 commands.

Normal invocation: ``agentorch ctx <command>`` or ``python3 -m agentorch_ctx ctx <command>``.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# DEV-ONLY: Bootstrap package context when invoked directly as a directory
# (e.g. ``python3 agentorch_ctx/contexts``).  In production the package is
# always imported via ``agentorch_ctx.contexts``, so this block is a no-op.
_need_bootstrap = __package__ is None or __package__ == ""
if _need_bootstrap:
    _runtime_dir = Path(__file__).resolve().parent
    _contexts_dir = _runtime_dir.parent
    if str(_contexts_dir) not in sys.path:
        sys.path.insert(0, str(_contexts_dir))
    __package__ = "contexts"  # noqa: F811
    import importlib as _importlib
    import warnings as _warnings

    _warnings.filterwarnings("ignore", message="__package__")
del _need_bootstrap

from .cli.agent import (
    cmd_get_project_context,
    cmd_get_task_context,
    cmd_log_decision,
    cmd_log_episode,
    cmd_propose_change,
    cmd_search_memory,
    cmd_update_task_context,
)
from .cli.operator import (
    cmd_doctor,
    cmd_init,
    cmd_inspect_entry,
    cmd_list_history,
    cmd_migrate,
    cmd_rebuild_projections,
    cmd_rebuild_vector_index,
    cmd_render_context,
    cmd_resolve_conflict,
    cmd_setup_vector,
    cmd_sync_vector_index,
    cmd_vector_doctor,
)
from .cli.shared import add_common_args, error_exit
from .core.config import find_repo_root, load_config, resolve_db_path
from .core.ids import now_iso
from .db.connection import open_db, open_db_with_vec


def main():
    parser = argparse.ArgumentParser(
        prog="contexts",
        description="SQLite-backed context management for AI agents",
    )
    add_common_args(parser)
    sub = parser.add_subparsers(dest="command")

    # --- Agent commands ---
    p = sub.add_parser("get-project-context", help="Assemble project-level context")
    add_common_args(p)
    p.add_argument("--branch-ref")
    p.add_argument("--max-bytes", type=int, default=32000)
    p.add_argument("--format", choices=["json", "markdown"], default="json")

    p = sub.add_parser("get-task-context", help="Assemble task-level context")
    add_common_args(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--session-id")
    p.add_argument("--max-bytes", type=int, default=16000)
    p.add_argument("--include-project", action="store_true")
    p.add_argument("--format", choices=["json", "markdown"], default="json")

    p = sub.add_parser("search-memory", help="Full-text search across context entries")
    add_common_args(p)
    p.add_argument("--query", required=True)
    p.add_argument("--scope")
    p.add_argument("--type")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--include-history", action="store_true")
    p.add_argument("--format", choices=["json", "markdown"], default="json")
    p.add_argument(
        "--mode",
        choices=["auto", "fts", "semantic", "hybrid"],
        default="auto",
        help="Search mode: auto (default), fts, semantic, or hybrid",
    )

    p = sub.add_parser(
        "update-task-context", help="Update task/session snapshot with CAS"
    )
    add_common_args(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--session-id")
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--from-file")
    p.add_argument(
        "--stdin",
        action="store_true",
        help="Read JSON payload from stdin (default when --from-file is omitted)",
    )
    p.add_argument("--change-reason")
    p.add_argument("--tags")
    p.add_argument("--related-files")

    p = sub.add_parser("log-decision", help="Log a decision entry")
    add_common_args(p)
    p.add_argument("--key", required=True)
    p.add_argument("--scope")
    p.add_argument("--task-id")
    p.add_argument("--session-id")
    p.add_argument("--branch-ref")
    p.add_argument("--from-file")
    p.add_argument("--change-reason")
    p.add_argument("--derived-from")
    p.add_argument("--confidence", type=float)
    p.add_argument("--tags")

    p = sub.add_parser("propose-change", help="Propose a new entry (always pending)")
    add_common_args(p)
    p.add_argument("--type", dest="entry_type", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--scope", required=True)
    p.add_argument("--change-reason", required=True)
    p.add_argument("--base-entry-id")
    p.add_argument("--from-file")
    p.add_argument("--derived-from")

    p = sub.add_parser("log-episode", help="Log an episode entry")
    add_common_args(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--session-id")
    p.add_argument("--from-file")
    p.add_argument("--change-reason")

    # --- Operator commands ---
    p = sub.add_parser("init", help="Initialize context database")
    add_common_args(p)
    p.add_argument("--repo-id")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("doctor", help="Run diagnostic checks")
    add_common_args(p)
    p.add_argument("--fix", action="store_true")

    p = sub.add_parser("migrate", help="Run pending schema migrations")
    add_common_args(p)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("inspect-entry", help="Inspect a single entry by ID")
    add_common_args(p)
    p.add_argument("--entry-id", required=True)

    p = sub.add_parser("list-history", help="List all revisions for a logical key")
    add_common_args(p)
    p.add_argument("--type", dest="entry_type", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--scope", required=True)
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("resolve-conflict", help="Approve or reject a pending entry")
    add_common_args(p)
    p.add_argument("--entry-id", required=True)
    p.add_argument("--decision", choices=["approve", "reject"], required=True)
    p.add_argument("--reason")
    p.add_argument("--approved-by", default="operator")

    p = sub.add_parser("render-context", help="Render context for any scope")
    add_common_args(p)
    p.add_argument("--scope", required=True)
    p.add_argument("--max-bytes", type=int, default=32000)
    p.add_argument(
        "--format", choices=["json", "markdown", "collab-markdown"], default="json"
    )
    p.add_argument("--mode", choices=["default", "recency-weighted"], default="default")
    p.add_argument("--include-episodes", action="store_true")
    p.add_argument("--out")

    p = sub.add_parser("rebuild-projections", help="Rebuild all projection tables")
    add_common_args(p)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser(
        "sync-vector-index", help="Consume dirty queue and update vector embeddings"
    )
    add_common_args(p)
    p.add_argument("--max-items", type=int, default=64)
    p.add_argument("--retry-failed", action="store_true")

    p = sub.add_parser("vector-doctor", help="Run vector stack diagnostics")
    add_common_args(p)

    p = sub.add_parser(
        "rebuild-vector-index",
        help="Full or partial rebuild of vector projections and embeddings",
    )
    add_common_args(p)
    p.add_argument(
        "--full",
        action="store_true",
        help="Force full rebuild (default when no filters)",
    )
    p.add_argument(
        "--since",
        default=None,
        help="ISO timestamp or revision int for partial rebuild",
    )
    p.add_argument("--scope", default=None, help="Filter by scope_ref prefix")
    p.add_argument(
        "--type", dest="entry_type", default=None, help="Filter by entry type"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what would be processed without writing",
    )
    p.add_argument(
        "--batch-size", type=int, default=32, help="Embedding batch size (default 32)"
    )

    p = sub.add_parser(
        "setup-vector",
        help="Install vector search dependencies (optional, enables semantic/hybrid search)",
    )
    add_common_args(p)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing",
    )
    p.add_argument(
        "--global",
        dest="use_global",
        action="store_true",
        help="Install to ~/.contexts-vector/ to share across projects",
    )
    p.add_argument(
        "--venv-path",
        default=None,
        help="Custom venv location (absolute path)",
    )
    p.add_argument(
        "--python",
        default=None,
        help="Python interpreter to use (default: auto-detect python3.12)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Recreate venv if it already exists",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    COMMAND_MAP = {
        "get-project-context": (cmd_get_project_context, False),
        "get-task-context": (cmd_get_task_context, False),
        "search-memory": (cmd_search_memory, False),
        "update-task-context": (cmd_update_task_context, True),
        "log-decision": (cmd_log_decision, True),
        "log-episode": (cmd_log_episode, True),
        "propose-change": (cmd_propose_change, True),
        "init": (cmd_init, False),
        "doctor": (cmd_doctor, False),
        "migrate": (cmd_migrate, False),
        "inspect-entry": (cmd_inspect_entry, False),
        "list-history": (cmd_list_history, False),
        "resolve-conflict": (cmd_resolve_conflict, True),
        "render-context": (cmd_render_context, False),
        "rebuild-projections": (cmd_rebuild_projections, True),
        "sync-vector-index": (cmd_sync_vector_index, True),
        "vector-doctor": (cmd_vector_doctor, False),
        "rebuild-vector-index": (cmd_rebuild_vector_index, True),
        "setup-vector": (cmd_setup_vector, False),
    }

    handler, needs_write = COMMAND_MAP[args.command]

    PRE_DB_COMMANDS = {"init", "setup-vector"}
    if args.command in PRE_DB_COMMANDS:
        try:
            result = handler(args, None, None)
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(0)
        except SystemExit:
            raise
        except Exception as exc:
            from .core.errors import ContextsError

            if isinstance(exc, ContextsError):
                error_exit(args.command, exc.code, str(exc))
            else:
                if os.environ.get("CONTEXTS_DEBUG") == "1":
                    import traceback

                    traceback.print_exc(file=sys.stderr)
                error_exit(args.command, "DB_ERROR", str(exc))

    # Resolve DB path and open connection
    try:
        db_path_str = getattr(args, "db_path", None)
        db_path = resolve_db_path(db_path_str)
        config = load_config(db_path)
    except FileNotFoundError as e:
        error_exit(
            args.command,
            "NOT_INITIALIZED",
            "Context manager not initialized: {}. Run 'init' first.".format(e),
        )

    # Inject _db_dir for WriteLock resolution
    config["_db_dir"] = str(db_path.parent)

    # Override project_id if given
    project_id_override = getattr(args, "project_id", None)
    if project_id_override:
        config["project_id"] = project_id_override

    _VECTOR_COMMANDS = {
        "rebuild-vector-index",
        "sync-vector-index",
        "vector-doctor",
        "search-memory",
    }
    if args.command in _VECTOR_COMMANDS:
        conn, _vec_loaded = open_db_with_vec(db_path)
    else:
        conn = open_db(db_path)
    try:
        result = handler(args, conn, config)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as exc:
        from .core.errors import ContextsError

        if isinstance(exc, ContextsError):
            error_exit(
                args.command, exc.code, str(exc), project_id=config.get("project_id")
            )
        else:
            if os.environ.get("CONTEXTS_DEBUG") == "1":
                import traceback

                traceback.print_exc(file=sys.stderr)
            error_exit(
                args.command, "DB_ERROR", str(exc), project_id=config.get("project_id")
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
