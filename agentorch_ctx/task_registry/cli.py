"""CLI handlers for the task registry namespace."""

from __future__ import annotations

import contextlib
import json
import os
import sys

from .db import (
    check_stale_tasks,
    create_task,
    generate_task_id,
    get_current_task,
    get_task,
    join_task,
    list_tasks,
    open_tasks_db,
    resolve_tasks_db_path,
    update_task_status,
)


def cmd_task_create(args) -> int:
    """Create a new task. Print task_id to stdout."""
    conn = None
    try:
        conn = open_tasks_db(resolve_tasks_db_path())
        task_id = args.task_id or generate_task_id(args.summary)
        created_by = args.provider or "user"
        conn.execute("BEGIN")
        create_task(
            conn,
            task_id=task_id,
            summary=args.summary,
            created_by=created_by,
            parent_id=args.parent,
            collab_ref=args.collab_ref,
            pid=os.getpid(),
        )
        if args.provider:
            join_task(
                conn,
                task_id=task_id,
                provider=args.provider,
                role="orchestrator",
            )
        conn.execute("COMMIT")
        print(task_id)
        return 0
    except Exception as exc:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def cmd_task_current(args) -> int:
    """Print the current active task_id. Exit 1 if none."""
    conn = None
    try:
        conn = open_tasks_db(resolve_tasks_db_path())
        task = get_current_task(conn, provider=getattr(args, "provider", None))
        if task is None:
            return 1
        print(task["task_id"])
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def cmd_task_list(args) -> int:
    """List tasks as JSON array."""
    conn = None
    try:
        conn = open_tasks_db(resolve_tasks_db_path())
        status = None if getattr(args, "status", "all") == "all" else args.status
        tasks = list_tasks(
            conn,
            status=status,
            parent_id=getattr(args, "parent", None),
            limit=getattr(args, "limit", 20),
        )
        print(json.dumps(tasks, indent=2, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def cmd_task_status(args) -> int:
    """Update task status."""
    conn = None
    try:
        conn = open_tasks_db(resolve_tasks_db_path())
        task = update_task_status(conn, args.task_id, args.set_status)
        print(json.dumps(task, indent=2, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def cmd_task_join(args) -> int:
    """Register provider participation."""
    conn = None
    try:
        conn = open_tasks_db(resolve_tasks_db_path())
        provider = join_task(conn, args.task_id, args.provider, role=args.role)
        print(json.dumps(provider, indent=2, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def cmd_task_show(args) -> int:
    """Show task details as JSON."""
    conn = None
    try:
        conn = open_tasks_db(resolve_tasks_db_path())
        task = get_task(conn, args.task_id)
        if task is None:
            print(f"error: Task not found: {args.task_id}", file=sys.stderr)
            return 1
        print(json.dumps(task, indent=2, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def cmd_task_check(args) -> int:
    """Check for stale tasks (active but PID gone). Print them."""
    conn = None
    try:
        conn = open_tasks_db(resolve_tasks_db_path())
        tasks = check_stale_tasks(conn)
        print(json.dumps(tasks, indent=2, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()
