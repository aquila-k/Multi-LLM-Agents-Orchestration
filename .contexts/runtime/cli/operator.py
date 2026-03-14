"""Operator-facing CLI commands (8 commands)."""

import json
import os
import sqlite3
from pathlib import Path

from ..core.config import (
    auto_detect_project_id,
    auto_detect_repo_id,
    find_repo_root,
    load_config,
    save_config,
)
from ..core.errors import InvalidArg, NotFound
from ..core.ids import new_event_id, now_iso
from ..core.scope import logical_key as build_logical_key
from ..core.scope import parse_scope_ref
from ..db.connection import open_db
from ..db.fts import delete_fts_for_entry, sync_fts_for_entry
from ..db.locks import LOCK_FILENAME, WriteLock
from ..db.migrations import (
    get_applied_migrations,
    get_sql_dir,
    list_migration_files,
    run_migrations,
)
from ..db.projections import rebuild_all_projections
from ..db.query import (
    check_active_uniqueness,
    check_projection_sync,
    count_active_entries,
    count_active_policies,
    fetch_active_entry,
    fetch_all_revisions_for_logical_key,
    fetch_entry_by_id,
    get_schema_version,
)
from ..db.write import (
    append_event,
    supersede_entry,
    upsert_active_entry,
)
from ..render.context_render import (
    _entry_to_dict,
    render_context,
    render_context_recency_weighted,
)
from ..render.formatters import to_collab_markdown, to_json, to_markdown
from .shared import error_exit


def cmd_init(args, conn_or_none, config_or_none) -> dict:
    """Initialize the .contexts/ local database and config."""
    try:
        repo_root = find_repo_root(Path.cwd())
    except FileNotFoundError as e:
        error_exit(
            "init", "NOT_INITIALIZED", "Cannot find repository root: {}".format(e)
        )
        return {}  # unreachable

    db_dir = repo_root / ".contexts" / "local"
    config_path = db_dir / "config.json"
    db_path = db_dir / "context.db"
    force = getattr(args, "force", False)

    # Check for existing config
    if config_path.exists() and not force:
        try:
            with open(str(config_path), "r", encoding="utf-8") as f:
                existing_config = json.load(f)
            return {
                "ok": True,
                "command": "init",
                "already_initialized": True,
                "project_id": existing_config.get("project_id", ""),
                "repo_id": existing_config.get("repo_id", ""),
                "db_path": str(db_path),
                "generated_at": now_iso(),
            }
        except (json.JSONDecodeError, IOError):
            pass

    # Auto-detect IDs
    project_id = getattr(args, "project_id", None) or auto_detect_project_id(repo_root)
    repo_id = getattr(args, "repo_id", None) or auto_detect_repo_id(repo_root)

    # Create directories
    for subdir in [db_dir, db_dir.parent / "exports", db_dir.parent / "cache"]:
        subdir.mkdir(parents=True, exist_ok=True)

    # Write config atomically
    cfg = {
        "project_id": project_id,
        "repo_id": repo_id,
        "repo_root": str(repo_root),
        "db_path": str(db_path),
        "created_at": now_iso(),
        "schema_version": "0",
    }
    save_config(db_path, cfg)

    # Open DB and run migrations
    conn = open_db(db_path)
    try:
        runtime_root = Path(__file__).resolve().parent.parent
        sql_dir = get_sql_dir(runtime_root)
        migration_result = run_migrations(conn, sql_dir)
        schema_version = migration_result.get("schema_version", "0")
    finally:
        conn.close()

    # Update config with schema version
    cfg["schema_version"] = schema_version
    save_config(db_path, cfg)

    return {
        "ok": True,
        "command": "init",
        "project_id": project_id,
        "repo_id": repo_id,
        "db_path": str(db_path),
        "schema_version": schema_version,
        "generated_at": now_iso(),
    }


def cmd_doctor(args, conn, config) -> dict:
    """Run diagnostic checks on the context database."""
    project_id = config.get("project_id", "")
    fix = getattr(args, "fix", False)
    checks = []

    db_path_str = config.get("db_path", "")
    db_path = Path(db_path_str) if db_path_str else None

    # 1. db_exists
    if db_path and db_path.exists():
        checks.append(
            {
                "name": "db_exists",
                "status": "pass",
                "detail": "Database file exists at {}".format(db_path),
            }
        )
    else:
        checks.append(
            {"name": "db_exists", "status": "fail", "detail": "Database file not found"}
        )

    # 2. wal_mode
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        mode = row[0] if row else "unknown"
        if mode == "wal":
            checks.append(
                {"name": "wal_mode", "status": "pass", "detail": "journal_mode=wal"}
            )
        else:
            checks.append(
                {
                    "name": "wal_mode",
                    "status": "warn",
                    "detail": "journal_mode={}, expected wal".format(mode),
                }
            )
    except Exception as e:
        checks.append({"name": "wal_mode", "status": "fail", "detail": str(e)})

    # 3. foreign_keys
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        fk = row[0] if row else 0
        if fk == 1:
            checks.append(
                {"name": "foreign_keys", "status": "pass", "detail": "foreign_keys=ON"}
            )
        else:
            checks.append(
                {"name": "foreign_keys", "status": "warn", "detail": "foreign_keys=OFF"}
            )
    except Exception as e:
        checks.append({"name": "foreign_keys", "status": "fail", "detail": str(e)})

    # 4. fts5_available
    try:
        conn.execute("SELECT 1 FROM fts_documents LIMIT 0")
        checks.append(
            {
                "name": "fts5_available",
                "status": "pass",
                "detail": "FTS5 table accessible",
            }
        )
    except sqlite3.OperationalError:
        checks.append(
            {
                "name": "fts5_available",
                "status": "warn",
                "detail": "FTS5 table not found; run migrate",
            }
        )

    # 5. schema_version
    try:
        runtime_root = Path(__file__).resolve().parent.parent
        sql_dir = get_sql_dir(runtime_root)
        all_files = list_migration_files(sql_dir)
        applied = get_applied_migrations(conn)
        current_version = get_schema_version(conn)
        if len(applied) >= len(all_files):
            checks.append(
                {
                    "name": "schema_version",
                    "status": "pass",
                    "detail": "schema_version={}, all {} migrations applied".format(
                        current_version, len(all_files)
                    ),
                }
            )
        else:
            checks.append(
                {
                    "name": "schema_version",
                    "status": "warn",
                    "detail": "{} migration(s) pending (applied={}, total={})".format(
                        len(all_files) - len(applied), len(applied), len(all_files)
                    ),
                }
            )
    except Exception as e:
        checks.append({"name": "schema_version", "status": "fail", "detail": str(e)})

    # 6. active_uniqueness
    try:
        is_unique = check_active_uniqueness(conn)
        if is_unique:
            checks.append(
                {
                    "name": "active_uniqueness",
                    "status": "pass",
                    "detail": "No duplicate active entries",
                }
            )
        else:
            checks.append(
                {
                    "name": "active_uniqueness",
                    "status": "fail",
                    "detail": "Duplicate active entries detected",
                }
            )
    except Exception as e:
        checks.append({"name": "active_uniqueness", "status": "fail", "detail": str(e)})

    # 7. projection_sync
    try:
        rev_count, ae_count = check_projection_sync(conn)
        if rev_count == ae_count:
            checks.append(
                {
                    "name": "projection_sync",
                    "status": "pass",
                    "detail": "Projections in sync ({} entries)".format(ae_count),
                }
            )
        else:
            status = "warn"
            detail = (
                "Projection mismatch: {} active revisions vs " "{} active_entries rows"
            ).format(rev_count, ae_count)
            if fix:
                if db_path:
                    with WriteLock(db_path.parent, command="doctor-fix"):
                        rebuild_all_projections(conn, project_id)
                else:
                    rebuild_all_projections(conn, project_id)
                detail += " (rebuilt)"
                status = "pass"
            checks.append(
                {"name": "projection_sync", "status": status, "detail": detail}
            )
    except Exception as e:
        checks.append({"name": "projection_sync", "status": "fail", "detail": str(e)})

    # 8. lock_file
    if db_path:
        lock_path = db_path.parent / LOCK_FILENAME
        if lock_path.exists():
            try:
                with open(str(lock_path), "r", encoding="utf-8") as f:
                    lock_data = json.load(f)
                pid = lock_data.get("pid")
                try:
                    os.kill(pid, 0)
                    checks.append(
                        {
                            "name": "lock_file",
                            "status": "warn",
                            "detail": "Write lock held by PID {}".format(pid),
                        }
                    )
                except (OSError, ProcessLookupError, TypeError):
                    checks.append(
                        {
                            "name": "lock_file",
                            "status": "warn",
                            "detail": "Stale lock file (PID {} not running)".format(
                                pid
                            ),
                        }
                    )
            except (json.JSONDecodeError, IOError):
                checks.append(
                    {
                        "name": "lock_file",
                        "status": "warn",
                        "detail": "Unreadable lock file exists",
                    }
                )
        else:
            checks.append(
                {
                    "name": "lock_file",
                    "status": "pass",
                    "detail": "No lock file present",
                }
            )
    else:
        checks.append(
            {
                "name": "lock_file",
                "status": "pass",
                "detail": "No db_path to check lock",
            }
        )

    # 9. config_readable
    try:
        if db_path:
            _ = load_config(db_path)
            checks.append(
                {
                    "name": "config_readable",
                    "status": "pass",
                    "detail": "config.json parsed successfully",
                }
            )
        else:
            checks.append(
                {
                    "name": "config_readable",
                    "status": "warn",
                    "detail": "No db_path; cannot locate config",
                }
            )
    except Exception as e:
        checks.append({"name": "config_readable", "status": "fail", "detail": str(e)})

    # Determine overall status
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "ok": True,
        "command": "doctor",
        "project_id": project_id,
        "generated_at": now_iso(),
        "overall": overall,
        "checks": checks,
    }


def cmd_migrate(args, conn, config) -> dict:
    """Run pending database migrations."""
    project_id = config.get("project_id", "")
    dry_run = getattr(args, "dry_run", False)

    runtime_root = Path(__file__).resolve().parent.parent
    sql_dir = get_sql_dir(runtime_root)

    db_path_str = config.get("db_path", "")
    db_dir = Path(db_path_str).parent if db_path_str else None

    if dry_run or db_dir is None:
        result = run_migrations(conn, sql_dir, dry_run=dry_run)
    else:
        with WriteLock(db_dir, command="migrate"):
            result = run_migrations(conn, sql_dir, dry_run=dry_run)

    return {
        "ok": True,
        "command": "migrate",
        "project_id": project_id,
        "generated_at": now_iso(),
        "applied": result["applied"],
        "skipped": result["skipped"],
        "schema_version": result["schema_version"],
        "dry_run": dry_run,
    }


def cmd_inspect_entry(args, conn, config) -> dict:
    """Inspect a single entry by ID."""
    project_id = config.get("project_id", "")
    entry_id = args.entry_id

    row = fetch_entry_by_id(conn, entry_id)
    if row is None:
        raise NotFound("Entry not found: {}".format(entry_id))

    entry = _entry_to_dict(row)
    # Add extra fields not included by default _entry_to_dict
    entry["supersedes"] = row["supersedes"] if "supersedes" in row.keys() else None
    entry["superseded_by"] = (
        row["superseded_by"] if "superseded_by" in row.keys() else None
    )
    entry["scope_level"] = row["scope_level"] if "scope_level" in row.keys() else None
    entry["project_id"] = row["project_id"] if "project_id" in row.keys() else None
    entry["load_policy"] = row["load_policy"] if "load_policy" in row.keys() else None
    entry["priority"] = row["priority"] if "priority" in row.keys() else None
    entry["approved_by"] = row["approved_by"] if "approved_by" in row.keys() else None
    entry["approved_at"] = row["approved_at"] if "approved_at" in row.keys() else None

    return {
        "ok": True,
        "command": "inspect-entry",
        "project_id": project_id,
        "scope_ref": entry.get("scope_ref", ""),
        "generated_at": now_iso(),
        "entry": entry,
    }


def cmd_list_history(args, conn, config) -> dict:
    """List all revisions for a logical key."""
    project_id = config.get("project_id", "")
    entry_type = args.entry_type
    key = args.key
    scope_ref = args.scope
    limit = getattr(args, "limit", 20)

    rows = fetch_all_revisions_for_logical_key(
        conn,
        "memory",
        entry_type,
        key,
        scope_ref,
        limit=limit,
    )

    lk = build_logical_key("memory", entry_type, key, scope_ref)
    revisions = []
    for r in rows:
        revisions.append(
            {
                "entry_id": r["id"],
                "revision": r["revision"],
                "status": r["status"],
                "created_at": r["created_at"],
            }
        )

    return {
        "ok": True,
        "command": "list-history",
        "project_id": project_id,
        "scope_ref": scope_ref,
        "generated_at": now_iso(),
        "logical_key": lk,
        "total": len(revisions),
        "revisions": revisions,
    }


def cmd_resolve_conflict(args, conn, config) -> dict:
    """Approve or reject a pending entry."""
    project_id = config.get("project_id", "")
    entry_id = args.entry_id
    decision = args.decision
    reason = getattr(args, "reason", None)
    approved_by = getattr(args, "approved_by", "operator")

    db_path_str = config.get("db_path", "")
    db_dir = Path(db_path_str).parent if db_path_str else None
    if not db_dir:
        from ..core.config import resolve_db_path

        db_path = resolve_db_path(getattr(args, "db_path", None))
        db_dir = db_path.parent

    with WriteLock(db_dir, command="resolve-conflict"):
        row = fetch_entry_by_id(conn, entry_id)
        if row is None:
            raise NotFound("Entry not found: {}".format(entry_id))

        previous_status = row["status"]
        if previous_status != "pending":
            raise InvalidArg(
                "Entry {} has status '{}', expected 'pending'".format(
                    entry_id, previous_status
                )
            )

        entry_type = row["type"]
        key = row["key"]
        scope_ref = row["scope_ref"]
        now = now_iso()
        superseded_entry_id = None

        if decision == "approve":
            lk = build_logical_key("memory", entry_type, key, scope_ref)

            conn.execute("BEGIN IMMEDIATE")
            try:
                # Find current active for this logical key
                current_active = fetch_active_entry(conn, lk)
                if current_active:
                    superseded_entry_id = current_active["id"]
                    # Supersede old entry
                    conn.execute(
                        "UPDATE entry_revisions SET status = 'superseded', "
                        "superseded_by = ?, updated_at = ? WHERE id = ?",
                        (entry_id, now, superseded_entry_id),
                    )
                    conn.execute(
                        "UPDATE entry_revisions SET supersedes = ? WHERE id = ?",
                        (superseded_entry_id, entry_id),
                    )
                    delete_fts_for_entry(conn, superseded_entry_id)

                # Activate the entry — use correct revision to avoid regression.
                # If a prior active entry was superseded at revision N, the new
                # canonical revision must be N+1 so future writes continue monotonically.
                if superseded_entry_id:
                    _sup = conn.execute(
                        "SELECT revision FROM entry_revisions WHERE id = ?",
                        (superseded_entry_id,),
                    ).fetchone()
                    revision = (_sup["revision"] + 1) if _sup else 1
                else:
                    revision = row["revision"]

                conn.execute(
                    "UPDATE entry_revisions SET status = 'active', revision = ?, "
                    "approved_by = ?, approved_at = ?, updated_at = ? "
                    "WHERE id = ?",
                    (revision, approved_by, now, now, entry_id),
                )

                # Upsert active_entries
                upsert_active_entry(
                    conn,
                    lk,
                    entry_id,
                    scope_ref,
                    entry_type,
                    key,
                    revision,
                    now,
                )

                # Sync FTS
                payload_raw = row["payload_json"]
                payload = json.loads(payload_raw) if payload_raw else {}
                tags_raw = row["tags_json"] if "tags_json" in row.keys() else None
                tags = json.loads(tags_raw) if tags_raw else []
                sync_fts_for_entry(conn, entry_id, entry_type, key, tags, payload)

                # Append events
                approve_event_id = append_event(
                    conn,
                    event_type="approve",
                    subject_family="memory",
                    project_id=project_id,
                    scope_ref=scope_ref,
                    subject_id=entry_id,
                    actor=approved_by,
                    reason=reason,
                )

                event_id = append_event(
                    conn,
                    event_type="activate",
                    subject_family="memory",
                    project_id=project_id,
                    scope_ref=scope_ref,
                    subject_id=entry_id,
                    actor=approved_by,
                    reason=reason,
                )

                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

            new_status = "active"

        else:  # reject
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "UPDATE entry_revisions SET status = 'archived', "
                    "updated_at = ? WHERE id = ?",
                    (now, entry_id),
                )

                event_id = append_event(
                    conn,
                    event_type="reject",
                    subject_family="memory",
                    project_id=project_id,
                    scope_ref=scope_ref,
                    subject_id=entry_id,
                    actor=approved_by,
                    reason=reason,
                )

                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

            new_status = "archived"

    return {
        "ok": True,
        "command": "resolve-conflict",
        "project_id": project_id,
        "scope_ref": scope_ref,
        "generated_at": now_iso(),
        "entry_id": entry_id,
        "decision": decision,
        "previous_status": previous_status,
        "new_status": new_status,
        "superseded_entry_id": superseded_entry_id,
        "event_id": event_id,
    }


def cmd_render_context(args, conn, config) -> dict:
    """Render context for any scope_ref."""
    project_id = config.get("project_id", "")
    scope_ref = args.scope
    max_bytes = getattr(args, "max_bytes", 32000)
    fmt = getattr(args, "format", "json")
    mode = getattr(args, "mode", "default")
    include_episodes = getattr(args, "include_episodes", False)
    out_path = getattr(args, "out", None)

    if mode == "recency-weighted":
        ctx = render_context_recency_weighted(
            conn, scope_ref, project_id, max_bytes=max_bytes
        )
    else:
        ctx = render_context(
            conn,
            scope_ref,
            project_id,
            max_bytes=max_bytes,
            include_episodes=include_episodes,
        )

    result = {
        "ok": True,
        "command": "render-context",
        "project_id": project_id,
        "scope_ref": scope_ref,
        "generated_at": now_iso(),
    }
    result.update(ctx)

    if out_path:
        if fmt == "markdown":
            content = to_markdown(ctx)
        elif fmt == "collab-markdown":
            content = to_collab_markdown(ctx)
        else:
            content = to_json(ctx)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
        result["output_path"] = out_path

    return result


def cmd_rebuild_projections(args, conn, config) -> dict:
    """Rebuild all projection tables."""
    project_id = config.get("project_id", "")
    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        rev_count, ae_count = check_projection_sync(conn)
        ap_count = count_active_policies(conn)

        return {
            "ok": True,
            "command": "rebuild-projections",
            "project_id": project_id,
            "generated_at": now_iso(),
            "dry_run": True,
            "active_entries_current": ae_count,
            "active_revisions_current": rev_count,
            "active_policies_current": ap_count,
        }

    db_path_str = config.get("db_path", "")
    db_dir = Path(db_path_str).parent if db_path_str else None
    if not db_dir:
        from ..core.config import resolve_db_path

        db_path = resolve_db_path(getattr(args, "db_path", None))
        db_dir = db_path.parent

    with WriteLock(db_dir, command="rebuild-projections"):
        result = rebuild_all_projections(conn, project_id)

    response = {
        "ok": True,
        "command": "rebuild-projections",
        "project_id": project_id,
        "generated_at": now_iso(),
    }
    response.update(result)

    return response
