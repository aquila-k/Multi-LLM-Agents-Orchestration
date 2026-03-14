"""
sqlite-vec virtual table operations for vec_memory_entries.

All functions require vec to be loaded in the connection.
Functions gracefully return empty results if the virtual table doesn't exist.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def ensure_vec_table(conn: sqlite3.Connection, sql_dir) -> bool:
    """
    Create vec_memory_entries virtual table if it doesn't exist.
    Reads sql/ext/vec_virtual_table.sql and executes it.
    sql_dir: Path to .contexts/sql/ directory.
    Returns True on success.
    """
    try:
        sql_path = Path(sql_dir) / "ext" / "vec_virtual_table.sql"
        sql = sql_path.read_text(encoding="utf-8")
        conn.executescript(sql)
        return True
    except Exception:
        return False


def upsert_vec(conn: sqlite3.Connection, entry_id: str, embedding: list) -> bool:
    """Insert or replace a vector embedding for entry_id. Returns True on success."""
    try:
        conn.execute(
            "INSERT OR REPLACE INTO vec_memory_entries (entry_id, embedding) VALUES (?, ?)",
            (entry_id, _serialize_embedding(embedding)),
        )
        return True
    except Exception:
        return False


def delete_vec(conn: sqlite3.Connection, entry_id: str) -> None:
    """Remove entry from vec_memory_entries."""
    try:
        conn.execute(
            "DELETE FROM vec_memory_entries WHERE entry_id = ?",
            (entry_id,),
        )
    except Exception:
        pass


def search_vec(
    conn: sqlite3.Connection,
    query_embedding: list,
    limit: int = 20,
    entry_ids: list | None = None,
) -> list:
    """
    KNN search in vec_memory_entries.
    Returns list of {entry_id, distance} sorted by distance ascending.
    If entry_ids is given, only search within those ids (for hybrid filtering).
    """
    try:
        fetch_limit = limit if entry_ids is None else limit + (len(entry_ids) if entry_ids else 0)
        rows = conn.execute(
            "SELECT entry_id, distance FROM vec_memory_entries "
            "WHERE embedding MATCH ? AND k = ?",
            (_serialize_embedding(query_embedding), max(fetch_limit * 2, 40)),
        ).fetchall()
        results = [{"entry_id": r[0], "distance": r[1]} for r in rows]
        if entry_ids is not None:
            id_set = set(entry_ids)
            results = [r for r in results if r["entry_id"] in id_set]
        return results[:limit]
    except Exception:
        return []


def vec_table_exists(conn: sqlite3.Connection) -> bool:
    """Check if vec_memory_entries virtual table exists."""
    try:
        conn.execute("SELECT 1 FROM vec_memory_entries LIMIT 0")
        return True
    except Exception:
        return False


def count_vec_entries(conn: sqlite3.Connection) -> int:
    """Count rows in vec_memory_entries."""
    try:
        row = conn.execute("SELECT COUNT(*) FROM vec_memory_entries").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _serialize_embedding(embedding: list) -> bytes:
    """Serialize a list of floats to bytes for sqlite-vec."""
    import struct

    return struct.pack("{}f".format(len(embedding)), *embedding)
