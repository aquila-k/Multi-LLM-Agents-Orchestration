"""Write operations for entries, policies, and events."""

import json
import sqlite3

from ..core.errors import ConflictError
from ..core.ids import new_entry_id, new_event_id, now_iso
from ..core.scope import logical_key
from .fts import delete_fts_for_entry, sync_fts_for_entry
from .query import fetch_active_entry, fetch_entry_by_id


def _enqueue_vector(conn: sqlite3.Connection, entry_id: str, reason: str) -> None:
    """Best-effort vector dirty queue enqueue. Silently skipped if table absent."""
    try:
        conn.execute(
            "INSERT INTO vector_dirty_queue (entry_id, reason, queued_at) VALUES (?, ?, ?)",
            (entry_id, reason, now_iso()),
        )
    except Exception:
        pass  # table may not exist in core profile


def insert_entry(
    conn: sqlite3.Connection,
    project_id: str,
    entry_type: str,
    key: str,
    scope_ref: str,
    scope_level: str,
    payload: dict,
    status: str = "active",
    revision: int = 1,
    load_policy: str = "on_task_start",
    priority: int = 50,
    author: str = "agent",
    change_reason: str = None,
    tags: list = None,
    related_files: list = None,
    confidence: float = None,
    derived_from: list = None,
    source_refs: list = None,
    supersedes_id: str = None,
    repo_id: str = None,
    branch_ref: str = None,
    task_id: str = None,
    session_id: str = None,
) -> str:
    """Insert a new entry_revision row. Returns new entry_id."""
    entry_id = new_entry_id()
    now = now_iso()

    payload_json = json.dumps(payload, ensure_ascii=False)
    tags_json = json.dumps(tags) if tags else None
    related_files_json = json.dumps(related_files) if related_files else None
    derived_from_json = json.dumps(derived_from) if derived_from else None
    source_refs_json = json.dumps(source_refs) if source_refs else None

    conn.execute(
        "INSERT INTO entry_revisions ("
        "  id, schema_version, record_family, type, key, scope_ref, "
        "  project_id, repo_id, branch_ref, task_id, session_id, "
        "  scope_level, payload_json, status, revision, load_policy, "
        "  priority, author, change_reason, source_refs_json, "
        "  derived_from_json, confidence, supersedes, "
        "  tags_json, related_files_json, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry_id,
            "1",
            "memory",
            entry_type,
            key,
            scope_ref,
            project_id,
            repo_id,
            branch_ref,
            task_id,
            session_id,
            scope_level,
            payload_json,
            status,
            revision,
            load_policy,
            priority,
            author,
            change_reason,
            source_refs_json,
            derived_from_json,
            confidence,
            supersedes_id,
            tags_json,
            related_files_json,
            now,
            now,
        ),
    )
    return entry_id


def supersede_entry(
    conn: sqlite3.Connection, old_id: str, new_id: str, now: str
) -> None:
    """Set old entry status=superseded, superseded_by=new_id; link new entry."""
    conn.execute(
        "UPDATE entry_revisions SET status = 'superseded', "
        "superseded_by = ?, updated_at = ? WHERE id = ?",
        (new_id, now, old_id),
    )
    conn.execute(
        "UPDATE entry_revisions SET supersedes = ? WHERE id = ?", (old_id, new_id)
    )


def upsert_active_entry(
    conn: sqlite3.Connection,
    logical_key_str: str,
    entry_id: str,
    scope_ref: str,
    type_: str,
    key: str,
    revision: int,
    updated_at: str,
) -> None:
    """INSERT OR REPLACE INTO active_entries (...)."""
    conn.execute(
        "INSERT OR REPLACE INTO active_entries "
        "(logical_key, entry_id, scope_ref, type, key, revision, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (logical_key_str, entry_id, scope_ref, type_, key, revision, updated_at),
    )


def append_event(
    conn: sqlite3.Connection,
    event_type: str,
    subject_family: str,
    project_id: str,
    scope_ref: str,
    subject_id: str = None,
    actor: str = "agent",
    reason: str = None,
    payload: dict = None,
) -> str:
    """Insert into event_log, return event_id."""
    event_id = new_event_id()
    now = now_iso()
    payload_json = json.dumps(payload) if payload else None

    conn.execute(
        "INSERT INTO event_log "
        "(id, event_type, subject_family, subject_id, project_id, "
        " scope_ref, actor, reason, payload_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            event_type,
            subject_family,
            subject_id,
            project_id,
            scope_ref,
            actor,
            reason,
            payload_json,
            now,
        ),
    )
    return event_id


def insert_policy_revision(
    conn: sqlite3.Connection,
    project_id: str,
    key: str,
    scope_ref: str,
    scope_level: str,
    target_kind: str,
    match_pattern: str,
    enforcement: str,
    status: str = "pending",
    revision: int = 1,
    author: str = "agent",
    rationale: str = None,
    allowed_when: str = None,
    requires_human_approval: int = 1,
    change_reason: str = None,
    supersedes_id: str = None,
) -> str:
    """Insert a policy_revision row. Returns new policy_id (e_ prefix)."""
    policy_id = new_entry_id()
    now = now_iso()

    conn.execute(
        "INSERT INTO policy_revisions ("
        "  id, schema_version, key, scope_ref, project_id, scope_level, "
        "  target_kind, match_pattern, enforcement, rationale, allowed_when, "
        "  requires_human_approval, status, revision, author, change_reason, "
        "  supersedes, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            policy_id,
            "1",
            key,
            scope_ref,
            project_id,
            scope_level,
            target_kind,
            match_pattern,
            enforcement,
            rationale,
            allowed_when,
            requires_human_approval,
            status,
            revision,
            author,
            change_reason,
            supersedes_id,
            now,
            now,
        ),
    )
    return policy_id


def supersede_policy(
    conn: sqlite3.Connection, old_id: str, new_id: str, now: str
) -> None:
    """Set old policy status=superseded, superseded_by=new_id; link new policy."""
    conn.execute(
        "UPDATE policy_revisions SET status = 'superseded', "
        "superseded_by = ?, updated_at = ? WHERE id = ?",
        (new_id, now, old_id),
    )
    conn.execute(
        "UPDATE policy_revisions SET supersedes = ? WHERE id = ?", (old_id, new_id)
    )


def upsert_active_policy(
    conn: sqlite3.Connection,
    logical_key_str: str,
    policy_id: str,
    scope_ref: str,
    key: str,
    enforcement: str,
    updated_at: str,
) -> None:
    """INSERT OR REPLACE INTO active_policies (...)."""
    conn.execute(
        "INSERT OR REPLACE INTO active_policies "
        "(logical_key, policy_id, scope_ref, key, enforcement, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (logical_key_str, policy_id, scope_ref, key, enforcement, updated_at),
    )


def write_entry_transaction(
    conn: sqlite3.Connection,
    project_id: str,
    entry_type: str,
    key: str,
    scope_ref: str,
    scope_level: str,
    payload: dict,
    mutation_class: str,
    expected_revision: int = None,
    **kwargs
) -> dict:
    """
    Full write transaction with BEGIN IMMEDIATE.

    Steps:
      1. CAS check (if expected_revision is not None)
      2. Fetch current active (if any)
      3. Insert new revision (status based on mutation_class)
      4. If auto_activate and old active exists: supersede old
      5. If auto_activate: upsert active_entries
      6. Sync FTS if auto_activate
      7. Append event_log events
    COMMIT

    Returns dict with: entry_id, revision, status, active_changed,
                       approval_required, event_id
    Raises: ConflictError (CAS mismatch)
    """
    lk = logical_key("memory", entry_type, key, scope_ref)
    now = now_iso()

    is_auto = mutation_class == "auto_activate"
    new_status = "active" if is_auto else "pending"
    is_episode = entry_type == "episode"

    tags = kwargs.get("tags")
    load_policy = kwargs.get("load_policy", "on_task_start")

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Fetch current active entry
        existing = fetch_active_entry(conn, lk)
        current_revision = 0
        old_id = None

        if existing is not None:
            current_revision = existing["revision"]
            old_id = existing["id"]

        # CAS check
        if expected_revision is not None:
            if expected_revision != current_revision:
                conn.rollback()
                raise ConflictError(
                    "CAS conflict: expected revision {} but found {}".format(
                        expected_revision, current_revision
                    ),
                    expected=expected_revision,
                    actual=current_revision,
                    entry_id=old_id,
                )

        # Compute new revision number
        if is_episode:
            new_revision = 1
        elif existing is not None:
            new_revision = current_revision + 1
        else:
            new_revision = 1

        active_changed = False

        # Supersede old entry BEFORE inserting new active one
        # (the partial unique index on status='active' requires this order)
        if is_auto and old_id and not is_episode:
            # Mark old as superseded first (new_id updated after insert)
            conn.execute(
                "UPDATE entry_revisions SET status = 'superseded', "
                "updated_at = ? WHERE id = ?",
                (now, old_id),
            )
            delete_fts_for_entry(conn, old_id)
            active_changed = True

        # Insert new entry revision
        entry_id = insert_entry(
            conn,
            project_id=project_id,
            entry_type=entry_type,
            key=key,
            scope_ref=scope_ref,
            scope_level=scope_level,
            payload=payload,
            status=new_status,
            revision=new_revision,
            load_policy=load_policy,
            priority=kwargs.get("priority", 50),
            author=kwargs.get("author", "agent"),
            change_reason=kwargs.get("change_reason"),
            tags=tags,
            related_files=kwargs.get("related_files"),
            confidence=kwargs.get("confidence"),
            derived_from=kwargs.get("derived_from"),
            source_refs=kwargs.get("source_refs"),
            supersedes_id=old_id if (is_auto and old_id and not is_episode) else None,
            repo_id=kwargs.get("repo_id"),
            branch_ref=kwargs.get("branch_ref"),
            task_id=kwargs.get("task_id"),
            session_id=kwargs.get("session_id"),
        )

        # Now update the supersede links with the new entry_id
        if is_auto and old_id and not is_episode:
            conn.execute(
                "UPDATE entry_revisions SET superseded_by = ? WHERE id = ?",
                (entry_id, old_id),
            )
            conn.execute(
                "UPDATE entry_revisions SET supersedes = ? WHERE id = ?",
                (old_id, entry_id),
            )

        # Upsert active_entries if auto_activate
        if is_auto:
            upsert_active_entry(
                conn, lk, entry_id, scope_ref, entry_type, key, new_revision, now
            )
            active_changed = True

            # Sync FTS
            sync_fts_for_entry(conn, entry_id, entry_type, key, tags, payload)

        # Append event
        event_type = "activate" if is_auto else "insert"
        event_id = append_event(
            conn,
            event_type=event_type,
            subject_family="memory",
            project_id=project_id,
            scope_ref=scope_ref,
            subject_id=entry_id,
            actor=kwargs.get("author", "agent"),
            reason=kwargs.get("change_reason"),
        )

        conn.commit()

        # Enqueue for vector index update (best-effort, after commit)
        _enqueue_vector(
            conn, entry_id, reason="insert" if new_revision == 1 else "update"
        )

        return {
            "entry_id": entry_id,
            "revision": new_revision,
            "status": new_status,
            "active_changed": active_changed,
            "approval_required": not is_auto,
            "event_id": event_id,
        }

    except ConflictError:
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
