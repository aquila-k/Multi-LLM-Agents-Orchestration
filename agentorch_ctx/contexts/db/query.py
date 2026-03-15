"""Read-only database query helpers. No locking required."""

import sqlite3


def fetch_active_entry(conn: sqlite3.Connection, logical_key: str):
    """
    Fetch the active entry for a given logical key.
    Returns sqlite3.Row or None.
    """
    row = conn.execute(
        "SELECT er.* FROM active_entries ae "
        "JOIN entry_revisions er ON ae.entry_id = er.id "
        "WHERE ae.logical_key = ?",
        (logical_key,),
    ).fetchone()
    return row


def fetch_active_entries_by_scope_and_type(
    conn: sqlite3.Connection, scope_ref: str, type_: str
) -> list:
    """
    Fetch active entries filtered by scope_ref and type.
    ORDER BY er.updated_at DESC, er.id ASC.
    """
    rows = conn.execute(
        "SELECT er.* FROM active_entries ae "
        "JOIN entry_revisions er ON ae.entry_id = er.id "
        "WHERE ae.scope_ref = ? AND ae.type = ? "
        "ORDER BY er.updated_at DESC, er.id ASC",
        (scope_ref, type_),
    ).fetchall()
    return list(rows)


def fetch_active_entries_by_project(
    conn: sqlite3.Connection, project_id: str, load_policy: str = None
) -> list:
    """Fetch active entries for a project, optionally filtered by load_policy."""
    if load_policy is not None:
        rows = conn.execute(
            "SELECT er.* FROM active_entries ae "
            "JOIN entry_revisions er ON ae.entry_id = er.id "
            "WHERE er.project_id = ? AND er.load_policy = ? "
            "ORDER BY er.updated_at DESC, er.id ASC",
            (project_id, load_policy),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT er.* FROM active_entries ae "
            "JOIN entry_revisions er ON ae.entry_id = er.id "
            "WHERE er.project_id = ? "
            "ORDER BY er.updated_at DESC, er.id ASC",
            (project_id,),
        ).fetchall()
    return list(rows)


def fetch_entry_by_id(conn: sqlite3.Connection, entry_id: str):
    """Fetch a single entry revision by ID. Returns sqlite3.Row or None."""
    row = conn.execute(
        "SELECT * FROM entry_revisions WHERE id = ?", (entry_id,)
    ).fetchone()
    return row


def fetch_all_revisions_for_logical_key(
    conn: sqlite3.Connection,
    record_family: str,
    type_: str,
    key: str,
    scope_ref: str,
    limit: int = 20,
) -> list:
    """Fetch all revisions for a logical key, newest first."""
    rows = conn.execute(
        "SELECT * FROM entry_revisions "
        "WHERE record_family = ? AND type = ? AND key = ? AND scope_ref = ? "
        "ORDER BY revision DESC, created_at DESC "
        "LIMIT ?",
        (record_family, type_, key, scope_ref, limit),
    ).fetchall()
    return list(rows)


def fetch_active_policies_by_scope(conn: sqlite3.Connection, scope_ref: str) -> list:
    """
    Fetch active policies for a given scope_ref.
    ORDER BY pr.updated_at DESC.
    """
    rows = conn.execute(
        "SELECT pr.* FROM active_policies ap "
        "JOIN policy_revisions pr ON ap.policy_id = pr.id "
        "WHERE ap.scope_ref = ? "
        "ORDER BY pr.updated_at DESC",
        (scope_ref,),
    ).fetchall()
    return list(rows)


def count_active_entries(conn: sqlite3.Connection) -> int:
    """Return the count of active entries."""
    row = conn.execute("SELECT COUNT(*) FROM active_entries").fetchone()
    return row[0]


def count_active_policies(conn: sqlite3.Connection) -> int:
    """Return the count of active policies."""
    row = conn.execute("SELECT COUNT(*) FROM active_policies").fetchone()
    return row[0]


def get_schema_version(conn: sqlite3.Connection) -> str:
    """Read meta.schema_version. Returns '0' if missing."""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            return "0"
        return row[0]
    except sqlite3.OperationalError:
        return "0"


def check_active_uniqueness(conn: sqlite3.Connection) -> bool:
    """
    Returns True if no duplicate active entries exist.
    Checks for count per (record_family, type, key, scope_ref)
    WHERE status='active' HAVING count > 1.
    """
    rows = conn.execute(
        "SELECT record_family, type, key, scope_ref, COUNT(*) as cnt "
        "FROM entry_revisions "
        "WHERE status = 'active' "
        "GROUP BY record_family, type, key, scope_ref "
        "HAVING cnt > 1"
    ).fetchall()
    return len(rows) == 0


def check_projection_sync(conn: sqlite3.Connection):
    """Returns (count_in_entry_revisions_active, count_in_active_entries)."""
    rev_row = conn.execute(
        "SELECT COUNT(*) FROM entry_revisions WHERE status = 'active'"
    ).fetchone()
    ae_row = conn.execute("SELECT COUNT(*) FROM active_entries").fetchone()
    return (rev_row[0], ae_row[0])
