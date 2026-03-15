"""Rebuild projection tables from source-of-truth revision tables."""

import json
import sqlite3

from ..core.ids import new_event_id, now_iso
from .fts import build_fts_body


def rebuild_all_projections(conn: sqlite3.Connection, project_id: str) -> dict:
    """
    Full rebuild of all projection tables inside one transaction.

    Steps:
      1. DELETE all from active_entries
      2. Re-populate from entry_revisions WHERE status='active'
      3. DELETE all from active_policies
      4. Re-populate from policy_revisions WHERE status='active'
      5. DELETE all from fts_documents
      6. Re-insert FTS docs for all active entries
      7. Append rebuild event to event_log

    Returns: {active_entries_rebuilt, active_policies_rebuilt,
              fts_documents_rebuilt, event_id}
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        # 1. Clear active_entries
        conn.execute("DELETE FROM active_entries")

        # 2. Re-populate active_entries from entry_revisions
        active_entries = conn.execute(
            "SELECT id, record_family, type, key, scope_ref, revision, "
            "updated_at FROM entry_revisions WHERE status = 'active'"
        ).fetchall()

        active_entries_count = 0
        for row in active_entries:
            lk = "{}:{}:{}:{}".format(
                row["record_family"], row["type"], row["key"], row["scope_ref"]
            )
            conn.execute(
                "INSERT OR REPLACE INTO active_entries "
                "(logical_key, entry_id, scope_ref, type, key, revision, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    lk,
                    row["id"],
                    row["scope_ref"],
                    row["type"],
                    row["key"],
                    row["revision"],
                    row["updated_at"],
                ),
            )
            active_entries_count += 1

        # 3. Clear active_policies
        conn.execute("DELETE FROM active_policies")

        # 4. Re-populate active_policies from policy_revisions
        active_policies = conn.execute(
            "SELECT id, key, scope_ref, enforcement, updated_at "
            "FROM policy_revisions WHERE status = 'active'"
        ).fetchall()

        active_policies_count = 0
        for row in active_policies:
            lk = "policy:rule:{}:{}".format(row["key"], row["scope_ref"])
            conn.execute(
                "INSERT OR REPLACE INTO active_policies "
                "(logical_key, policy_id, scope_ref, key, enforcement, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    lk,
                    row["id"],
                    row["scope_ref"],
                    row["key"],
                    row["enforcement"],
                    row["updated_at"],
                ),
            )
            active_policies_count += 1

        # 5. Clear FTS documents
        conn.execute("DELETE FROM fts_documents")

        # 6. Re-insert FTS docs for all active entries
        fts_entries = conn.execute(
            "SELECT id, type, key, tags_json, payload_json "
            "FROM entry_revisions WHERE status = 'active'"
        ).fetchall()

        fts_count = 0
        for row in fts_entries:
            payload = json.loads(row["payload_json"])
            tags_json = row["tags_json"]
            tags = json.loads(tags_json) if tags_json else []
            tags_str = " ".join(tags) if tags else ""
            body = build_fts_body(row["type"], payload)

            conn.execute(
                "INSERT INTO fts_documents (entry_id, type, key, tags, body) "
                "VALUES (?, ?, ?, ?, ?)",
                (row["id"], row["type"], row["key"], tags_str, body),
            )
            fts_count += 1

        # 7. Append rebuild event
        event_id = new_event_id()
        now = now_iso()
        conn.execute(
            "INSERT INTO event_log "
            "(id, event_type, subject_family, project_id, scope_ref, "
            " actor, reason, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                "rebuild",
                "system",
                project_id,
                "project/{}".format(project_id),
                "system",
                "Full projection rebuild",
                json.dumps(
                    {
                        "active_entries_rebuilt": active_entries_count,
                        "active_policies_rebuilt": active_policies_count,
                        "fts_documents_rebuilt": fts_count,
                    }
                ),
                now,
            ),
        )

        conn.commit()

        return {
            "active_entries_rebuilt": active_entries_count,
            "active_policies_rebuilt": active_policies_count,
            "fts_documents_rebuilt": fts_count,
            "event_id": event_id,
        }

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
