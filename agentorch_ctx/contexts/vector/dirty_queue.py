"""
Dirty queue operations for the vector index.

The dirty queue (vector_dirty_queue) records which entry_ids need their
vector embedding refreshed. The queue is consumed by sync-vector-index.
"""

from __future__ import annotations

import sqlite3

from ..core.ids import now_iso


def enqueue(
    conn: sqlite3.Connection,
    entry_id: str,
    reason: str = "insert",
) -> int:
    """
    Add entry_id to the dirty queue.
    Duplicate enqueues are allowed (idempotent by consumer skip logic).
    Returns the new queue row id.
    """
    now = now_iso()
    cur = conn.execute(
        "INSERT INTO vector_dirty_queue (entry_id, reason, queued_at) VALUES (?, ?, ?)",
        (entry_id, reason, now),
    )
    return cur.lastrowid


def dequeue_batch(
    conn: sqlite3.Connection,
    owner: str,
    max_items: int = 64,
) -> list[dict]:
    """
    Claim up to max_items unlocked queue rows for owner.
    Returns list of dicts with keys: id, entry_id, reason.
    """
    now = now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute(
            "SELECT id, entry_id, reason FROM vector_dirty_queue "
            "WHERE lock_owner IS NULL "
            "ORDER BY queued_at ASC "
            "LIMIT ?",
            (max_items,),
        ).fetchall()
        if not rows:
            conn.commit()
            return []
        ids = [r[0] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            "UPDATE vector_dirty_queue SET lock_owner = ?, locked_at = ? "
            "WHERE id IN ({})".format(placeholders),
            [owner, now] + ids,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return [{"id": r[0], "entry_id": r[1], "reason": r[2]} for r in rows]


def mark_done(conn: sqlite3.Connection, queue_id: int) -> None:
    """Delete a successfully processed queue row."""
    conn.execute("DELETE FROM vector_dirty_queue WHERE id = ?", (queue_id,))


def mark_failed(conn: sqlite3.Connection, queue_id: int, error: str) -> None:
    """Increment attempt_count, clear lock, record error."""
    conn.execute(
        "UPDATE vector_dirty_queue SET attempt_count = attempt_count + 1, "
        "last_error = ?, lock_owner = NULL, locked_at = NULL "
        "WHERE id = ?",
        (error, queue_id),
    )


def release_stale_locks(conn: sqlite3.Connection, stale_seconds: int = 3600) -> int:
    """Release locks held longer than stale_seconds. Returns count released."""
    cur = conn.execute(
        "UPDATE vector_dirty_queue SET lock_owner = NULL, locked_at = NULL "
        "WHERE lock_owner IS NOT NULL "
        "AND locked_at < datetime('now', '-' || ? || ' seconds')",
        (str(int(stale_seconds)),),
    )
    return cur.rowcount


def queue_depth(conn: sqlite3.Connection) -> dict:
    """Return counts: {total, unlocked, locked, failed, retrying}."""
    row = conn.execute(
        "SELECT "
        "COUNT(*) AS total, "
        "SUM(CASE WHEN lock_owner IS NULL THEN 1 ELSE 0 END) AS unlocked, "
        "SUM(CASE WHEN lock_owner IS NOT NULL THEN 1 ELSE 0 END) AS locked, "
        "SUM(CASE WHEN attempt_count >= 3 THEN 1 ELSE 0 END) AS failed, "
        "SUM(CASE WHEN attempt_count >= 1 AND attempt_count < 3 THEN 1 ELSE 0 END) "
        "AS retrying "
        "FROM vector_dirty_queue"
    ).fetchone()
    if row is None:
        return {"total": 0, "unlocked": 0, "locked": 0, "failed": 0, "retrying": 0}
    return {
        "total": row[0] or 0,
        "unlocked": row[1] or 0,
        "locked": row[2] or 0,
        "failed": row[3] or 0,
        "retrying": row[4] or 0,
    }
