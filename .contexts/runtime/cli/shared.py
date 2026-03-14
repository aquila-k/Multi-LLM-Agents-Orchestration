"""Shared CLI utilities: output envelope, error handling, arg helpers."""

import json
import sys
from pathlib import Path

from ..core.errors import (
    ApprovalRequired,
    ConflictError,
    ContextsError,
    DBError,
    InvalidArg,
    InvalidPayload,
    LockTimeout,
    NotFound,
    NotInitialized,
)
from ..core.ids import now_iso
from ..core.scope import (
    compute_scope_ref,
    infer_scope_level,
    parse_scope_ref,
)


def emit(data: dict) -> None:
    """Print JSON to stdout and exit 0."""
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(0)


def error_exit(
    command: str, code: str, error: str, project_id: str = None, **extra
) -> None:
    """Print error JSON to stdout and exit 1."""
    d = {
        "ok": False,
        "command": command,
        "code": code,
        "error": error,
        "generated_at": now_iso(),
    }
    if project_id:
        d["project_id"] = project_id
    d.update(extra)
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(1)


_ERROR_CODE_MAP = {
    NotInitialized: "NOT_INITIALIZED",
    NotFound: "NOT_FOUND",
    ConflictError: "CONFLICT",
    InvalidArg: "INVALID_ARG",
    InvalidPayload: "INVALID_PAYLOAD",
    LockTimeout: "LOCK_TIMEOUT",
    DBError: "DB_ERROR",
    ApprovalRequired: "APPROVAL_REQUIRED",
}


def handle_error(command: str, exc: Exception, project_id: str = None) -> None:
    """Convert exceptions to error_exit. Handles ContextsError subclasses."""
    if isinstance(exc, ContextsError):
        code = getattr(exc, "code", "UNKNOWN")
        extra = {}
        if isinstance(exc, ConflictError):
            if exc.expected is not None:
                extra["expected_revision"] = exc.expected
            if exc.actual is not None:
                extra["actual_revision"] = exc.actual
            if exc.entry_id is not None:
                extra["entry_id"] = exc.entry_id
        error_exit(command, code, str(exc), project_id=project_id, **extra)
    elif isinstance(exc, ValueError):
        error_exit(command, "INVALID_ARG", str(exc), project_id=project_id)
    else:
        error_exit(command, "DB_ERROR", str(exc), project_id=project_id)


def read_payload(from_file: str = None) -> dict:
    """Read JSON payload from file or stdin. Raises InvalidPayload on parse error."""
    try:
        if from_file:
            with open(from_file, "r", encoding="utf-8") as f:
                raw = f.read()
        else:
            raw = sys.stdin.read()
        if not raw.strip():
            raise InvalidPayload("Empty payload")
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise InvalidPayload("Invalid JSON payload: {}".format(e))
    except IOError as e:
        raise InvalidPayload("Cannot read payload: {}".format(e))


def add_common_args(parser) -> None:
    """Add --db-path and --project-id to any argparse subparser."""
    parser.add_argument("--db-path", default=None, help="Path to context.db file")
    parser.add_argument("--project-id", default=None, help="Override project ID")


def add_scope_args(parser) -> None:
    """Add --scope, --task-id, --session-id, --branch-ref args for scope resolution."""
    parser.add_argument(
        "--scope", default=None, help="Explicit scope_ref (e.g. project/abc123)"
    )
    parser.add_argument("--task-id", default=None, help="Task ID for task-level scope")
    parser.add_argument(
        "--session-id", default=None, help="Session ID for session-level scope"
    )
    parser.add_argument(
        "--branch-ref", default=None, help="Branch ref for branch-level scope"
    )


def resolve_scope_from_args(args, config: dict):
    """
    From parsed args (with scope, task_id, session_id, branch_ref attrs),
    return (scope_ref, scope_level).
    If args.scope is given, parse it.
    Else infer from task_id/session_id/branch_ref.
    Fallback: project scope from config['project_id'].
    """
    scope = getattr(args, "scope", None)
    task_id = getattr(args, "task_id", None)
    session_id = getattr(args, "session_id", None)
    branch_ref = getattr(args, "branch_ref", None)

    if scope:
        scope_level, _ = parse_scope_ref(scope)
        return (scope, scope_level)

    scope_level = infer_scope_level(session_id, task_id, branch_ref)
    project_id = config.get("project_id", "")

    scope_ref = compute_scope_ref(
        scope_level,
        project_id,
        branch_ref=branch_ref,
        task_id=task_id,
        session_id=session_id,
    )
    return (scope_ref, scope_level)
