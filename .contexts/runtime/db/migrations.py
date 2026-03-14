"""Schema migration management for the .contexts database."""

import json
import os
import re
import sqlite3
from pathlib import Path


def get_sql_dir(runtime_root: Path) -> Path:
    """Returns path to .contexts/sql/ directory (two levels up from runtime/)."""
    return runtime_root.parent / "sql"


def get_applied_migrations(conn: sqlite3.Connection) -> list:
    """Read meta.applied_migrations JSON array. Returns [] if missing."""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'applied_migrations'"
        ).fetchone()
        if row is None:
            return []
        return json.loads(row[0])
    except sqlite3.OperationalError:
        return []


def list_migration_files(sql_dir: Path) -> list:
    """Return sorted list of .sql filenames matching /^\\d{4}_.*\\.sql$/."""
    pattern = re.compile(r"^\d{4}_.*\.sql$")
    files = []
    if sql_dir.exists():
        for name in os.listdir(str(sql_dir)):
            if pattern.match(name):
                files.append(name)
    files.sort()
    return files


def run_migrations(
    conn: sqlite3.Connection, sql_dir: Path, dry_run: bool = False
) -> dict:
    """
    Apply unapplied migration files in order.
    Each migration runs in its own transaction.
    Updates meta.applied_migrations after each file.
    Returns {'applied': [...], 'skipped': [...], 'schema_version': '...'}
    """
    all_files = list_migration_files(sql_dir)
    already_applied = set(get_applied_migrations(conn))

    applied = []
    skipped = []

    for filename in all_files:
        if filename in already_applied:
            skipped.append(filename)
            continue

        if dry_run:
            applied.append(filename)
            continue

        file_path = sql_dir / filename
        with open(str(file_path), "r", encoding="utf-8") as f:
            sql_content = f.read()

        # executescript() implicitly commits any pending tx and runs
        # the file verbatim; DDL in WAL mode is auto-committed anyway.
        try:
            conn.executescript(sql_content)
        except Exception:
            raise

        # Update the applied_migrations list (manual tx with isolation_level=None)
        current_applied = get_applied_migrations(conn)
        current_applied.append(filename)
        conn.execute("BEGIN")
        try:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("applied_migrations", json.dumps(current_applied)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        applied.append(filename)

    # Compute schema version: total number of applied migrations
    total_applied = len(already_applied) + len(applied)
    schema_version = str(total_applied)

    if not dry_run and applied:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", schema_version),
        )
        conn.commit()

    return {
        "applied": applied,
        "skipped": skipped,
        "schema_version": schema_version,
    }
