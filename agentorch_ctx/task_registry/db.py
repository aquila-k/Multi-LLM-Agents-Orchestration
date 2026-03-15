"""SQLite task registry for lightweight task tracking."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from agentorch_ctx.contexts.core.config import resolve_db_path
from agentorch_ctx.contexts.core.ids import now_iso

VALID_STATUSES = ("active", "paused", "completed", "failed", "blocked")
VALID_ROLES = ("orchestrator", "worker")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id       TEXT PRIMARY KEY,
    parent_id     TEXT REFERENCES tasks(task_id),
    summary       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK(status IN ('active','paused','completed','failed','blocked')),
    created_by    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    collab_ref    TEXT,
    pid           INTEGER,
    metadata_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS task_providers (
    task_id       TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    provider      TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'worker' CHECK(role IN ('orchestrator','worker')),
    joined_at     TEXT NOT NULL,
    last_active   TEXT NOT NULL,
    PRIMARY KEY (task_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_updated
    ON tasks(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_parent
    ON tasks(parent_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_task_providers_provider_active
    ON task_providers(provider, last_active DESC);
"""


def resolve_tasks_db_path(db_path_arg: str | Path | None = None) -> Path:
    """Resolve the tasks DB path using the same logic as context.db."""
    if db_path_arg:
        db_path = Path(db_path_arg)
    else:
        db_path = resolve_db_path().with_name("tasks.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def open_tasks_db(db_path: Path) -> sqlite3.Connection:
    """Open or create tasks.db with WAL mode. Auto-create tables if missing."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        check_same_thread=False,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def create_task(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    summary: str,
    created_by: str = "user",
    parent_id: str | None = None,
    collab_ref: str | None = None,
    pid: int | None = None,
    metadata: dict | None = None,
) -> dict:
    """Insert a new task. Return the task record as dict."""
    timestamp = now_iso()
    payload = json.dumps(metadata or {}, sort_keys=True, ensure_ascii=True)
    try:
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, parent_id, summary, status, created_by,
                created_at, updated_at, collab_ref, pid, metadata_json
            ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                parent_id,
                summary,
                created_by,
                timestamp,
                timestamp,
                collab_ref,
                pid,
                payload,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(_describe_integrity_error(task_id, parent_id, exc)) from exc
    task = get_task(conn, task_id)
    if task is None:
        raise RuntimeError(f"Created task disappeared unexpectedly: {task_id}")
    return task


def get_current_task(
    conn: sqlite3.Connection,
    *,
    provider: str | None = None,
) -> dict | None:
    """Return the most recent 'active' task. If provider given, filter by task_providers."""
    if provider:
        row = conn.execute(
            """
            SELECT t.task_id
            FROM tasks AS t
            INNER JOIN task_providers AS tp
                ON tp.task_id = t.task_id
            WHERE t.status = 'active' AND tp.provider = ?
            ORDER BY tp.last_active DESC, t.updated_at DESC, t.created_at DESC, t.rowid DESC
            LIMIT 1
            """,
            (provider,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT task_id
            FROM tasks
            WHERE status = 'active'
            ORDER BY updated_at DESC, created_at DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    return get_task(conn, row["task_id"])


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    parent_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List tasks, optionally filtered by status or parent_id."""
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Expected one of: {', '.join(VALID_STATUSES)}"
        )
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    clauses: list[str] = []
    params: list[object] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if parent_id is not None:
        clauses.append("parent_id = ?")
        params.append(parent_id)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT *
        FROM tasks
        {where_sql}
        ORDER BY updated_at DESC, created_at DESC, rowid DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [_task_row_to_dict(row) for row in rows]


def update_task_status(
    conn: sqlite3.Connection,
    task_id: str,
    new_status: str,
) -> dict:
    """Update status and updated_at. Return updated record."""
    _require_valid_status(new_status)
    existing = get_task(conn, task_id)
    if existing is None:
        raise ValueError(f"Task not found: {task_id}")

    conn.execute(
        "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
        (new_status, now_iso(), task_id),
    )
    updated = get_task(conn, task_id)
    if updated is None:
        raise RuntimeError(f"Updated task disappeared unexpectedly: {task_id}")
    return updated


def join_task(
    conn: sqlite3.Connection,
    task_id: str,
    provider: str,
    role: str = "worker",
) -> dict:
    """Register a provider as participant. Upsert on (task_id, provider)."""
    if not provider or not provider.strip():
        raise ValueError("provider is required")
    _require_valid_role(role)
    if get_task(conn, task_id) is None:
        raise ValueError(f"Task not found: {task_id}")

    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO task_providers (
            task_id, provider, role, joined_at, last_active
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(task_id, provider) DO UPDATE SET
            role = excluded.role,
            last_active = excluded.last_active
        """,
        (task_id, provider, role, timestamp, timestamp),
    )
    conn.execute(
        "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
        (timestamp, task_id),
    )
    row = conn.execute(
        """
        SELECT task_id, provider, role, joined_at, last_active
        FROM task_providers
        WHERE task_id = ? AND provider = ?
        """,
        (task_id, provider),
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"Joined provider disappeared unexpectedly: {task_id}:{provider}"
        )
    return _provider_row_to_dict(row)


def get_task(
    conn: sqlite3.Connection,
    task_id: str,
) -> dict | None:
    """Return a single task with its providers list."""
    row = conn.execute(
        "SELECT * FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        return None

    task = _task_row_to_dict(row)
    provider_rows = conn.execute(
        """
        SELECT task_id, provider, role, joined_at, last_active
        FROM task_providers
        WHERE task_id = ?
        ORDER BY joined_at ASC, provider ASC
        """,
        (task_id,),
    ).fetchall()
    task["providers"] = [
        _provider_row_to_dict(provider_row) for provider_row in provider_rows
    ]
    return task


def check_stale_tasks(conn: sqlite3.Connection) -> list[dict]:
    """Find tasks with status='active' whose pid is no longer running."""
    rows = conn.execute(
        """
        SELECT task_id
        FROM tasks
        WHERE status = 'active' AND pid IS NOT NULL
        ORDER BY updated_at DESC, created_at DESC, rowid DESC
        """
    ).fetchall()

    stale: list[dict] = []
    for row in rows:
        task = get_task(conn, row["task_id"])
        if task is None:
            continue
        pid = task.get("pid")
        if not _pid_is_running(pid):
            stale.append(task)
    return stale


def generate_task_id(summary: str) -> str:
    """Generate task_id from summary."""
    normalized = unicodedata.normalize("NFKD", summary or "")
    ascii_summary = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_summary.lower()).strip("-")
    slug = slug[:40].strip("-") or "task"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{slug}-{timestamp}"


def _task_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "task_id": row["task_id"],
        "parent_id": row["parent_id"],
        "summary": row["summary"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "collab_ref": row["collab_ref"],
        "pid": row["pid"],
        "metadata": _decode_metadata(row["metadata_json"]),
    }


def _provider_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "task_id": row["task_id"],
        "provider": row["provider"],
        "role": row["role"],
        "joined_at": row["joined_at"],
        "last_active": row["last_active"],
    }


def _decode_metadata(payload: str | None) -> dict:
    if not payload:
        return {}
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _describe_integrity_error(
    task_id: str,
    parent_id: str | None,
    exc: sqlite3.IntegrityError,
) -> str:
    message = str(exc)
    if "UNIQUE constraint failed: tasks.task_id" in message:
        return f"Task already exists: {task_id}"
    if "FOREIGN KEY constraint failed" in message and parent_id is not None:
        return f"Parent task not found: {parent_id}"
    return f"Failed to create task '{task_id}': {message}"


def _require_valid_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Expected one of: {', '.join(VALID_STATUSES)}"
        )


def _require_valid_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise ValueError(
            f"Invalid role '{role}'. Expected one of: {', '.join(VALID_ROLES)}"
        )


def _pid_is_running(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
