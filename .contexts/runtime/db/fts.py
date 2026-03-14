"""Full-text search operations using FTS5."""

import sqlite3

FTS_BODY_FIELDS = {
    "project_profile": ["goal", "constraints"],
    "task_snapshot": ["task_goal", "current_plan", "open_questions", "blockers"],
    "session_snapshot": ["session_goal", "working_notes"],
    "decision": ["decision", "context", "reason", "alternatives_considered"],
    "episode": ["observation", "thoughts", "action", "result", "lesson"],
    "procedural_rule": ["name", "instructions", "when_to_use", "checklist"],
    "policy_rule": ["match_pattern", "rationale"],
}


def build_fts_body(type_: str, payload: dict) -> str:
    """Concatenate relevant payload fields into a single searchable string."""
    fields = FTS_BODY_FIELDS.get(type_, [])
    parts = []
    for field in fields:
        value = payload.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
    return "\n".join(parts)


def sync_fts_for_entry(
    conn: sqlite3.Connection,
    entry_id: str,
    type_: str,
    key: str,
    tags: list,
    payload: dict,
) -> None:
    """INSERT OR REPLACE INTO fts_documents (entry_id, type, key, tags, body)."""
    body = build_fts_body(type_, payload)
    tags_str = " ".join(tags) if tags else ""
    # Delete first then insert (FTS5 doesn't support INSERT OR REPLACE directly)
    conn.execute("DELETE FROM fts_documents WHERE entry_id = ?", (entry_id,))
    conn.execute(
        "INSERT INTO fts_documents (entry_id, type, key, tags, body) "
        "VALUES (?, ?, ?, ?, ?)",
        (entry_id, type_, key, tags_str, body),
    )


def delete_fts_for_entry(conn: sqlite3.Connection, entry_id: str) -> None:
    """DELETE FROM fts_documents WHERE entry_id = ?"""
    conn.execute("DELETE FROM fts_documents WHERE entry_id = ?", (entry_id,))


def _escape_fts_query(query: str) -> str:
    """Escape FTS5 reserved characters by wrapping terms in double quotes."""
    reserved = set('"*():{}[]^~')
    has_reserved = any(c in reserved for c in query)
    if has_reserved:
        # Wrap each word in double quotes to escape special chars
        words = query.split()
        escaped = []
        for word in words:
            clean = word.replace('"', '""')
            escaped.append('"{}"'.format(clean))
        return " ".join(escaped)
    return query


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    scope_ref: str = None,
    type_filter: str = None,
    limit: int = 20,
    include_history: bool = False,
) -> list:
    """
    FTS5 query with BM25 ranking.
    Returns list of dicts: {score, entry_id, type, key, scope_ref, status, excerpt}
    """
    escaped_query = _escape_fts_query(query)

    sql_parts = [
        "SELECT fts.rank AS score, fts.entry_id, fts.type, fts.key, "
        "er.scope_ref, er.status, "
        "SUBSTR(fts.body, 1, 200) AS excerpt "
        "FROM fts_documents fts "
        "JOIN entry_revisions er ON fts.entry_id = er.id "
        "WHERE fts_documents MATCH ?"
    ]
    params = [escaped_query]

    if not include_history:
        sql_parts.append("AND er.status = 'active'")

    if scope_ref is not None:
        sql_parts.append("AND (er.scope_ref = ? OR er.scope_ref LIKE ?)")
        params.append(scope_ref)
        params.append(scope_ref + "/%")

    if type_filter is not None:
        sql_parts.append("AND fts.type = ?")
        params.append(type_filter)

    sql_parts.append("ORDER BY fts.rank")
    sql_parts.append("LIMIT ?")
    params.append(limit)

    sql = " ".join(sql_parts)

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []

    results = []
    for row in rows:
        results.append(
            {
                "score": row["score"],
                "entry_id": row["entry_id"],
                "type": row["type"],
                "key": row["key"],
                "scope_ref": row["scope_ref"],
                "status": row["status"],
                "excerpt": row["excerpt"],
            }
        )
    return results
