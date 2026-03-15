"""Agent-facing CLI commands (6 commands)."""

import json

from ..core.entry import DEFAULT_LOAD_POLICY, mutation_class, validate_payload
from ..core.errors import InvalidArg, InvalidPayload
from ..core.ids import new_event_id, now_iso
from ..core.scope import (
    compute_scope_ref,
    infer_scope_level,
)
from ..core.scope import logical_key as build_logical_key
from ..core.scope import (
    parse_scope_ref,
)
from ..db.fts import search_fts
from ..db.locks import WriteLock
from ..db.query import (
    fetch_active_entries_by_scope_and_type,
    fetch_active_policies_by_scope,
)
from ..db.write import append_event, insert_entry, write_entry_transaction
from ..render.context_render import _entry_to_dict, _policy_to_dict, render_context
from ..render.formatters import to_markdown
from ..render.search import format_search_results
from .shared import error_exit, read_payload, resolve_scope_from_args


def cmd_get_project_context(args, conn, config) -> dict:
    """Assemble and return the project-level context."""
    project_id = getattr(args, "project_id", None) or config.get("project_id", "")
    branch_ref = getattr(args, "branch_ref", None)
    max_bytes = getattr(args, "max_bytes", 32000)
    fmt = getattr(args, "format", "json")

    scope_ref = "project/{}".format(project_id)

    # Fetch project_profile
    pp_rows = fetch_active_entries_by_scope_and_type(conn, scope_ref, "project_profile")
    project_profile = _entry_to_dict(pp_rows[0]) if pp_rows else None

    # Fetch decisions at project scope (and branch scope if given)
    scopes = [scope_ref]
    if branch_ref:
        scopes.append("branch/{}".format(branch_ref))

    decisions = []
    for sc in scopes:
        rows = fetch_active_entries_by_scope_and_type(conn, sc, "decision")
        for r in rows:
            decisions.append(_entry_to_dict(r))

    # Fetch procedural_rules
    procedural_rules = []
    for sc in scopes:
        rows = fetch_active_entries_by_scope_and_type(conn, sc, "procedural_rule")
        for r in rows:
            procedural_rules.append(_entry_to_dict(r))

    # Fetch policies
    policies = []
    for sc in scopes:
        rows = fetch_active_policies_by_scope(conn, sc)
        for r in rows:
            policies.append(_policy_to_dict(r))

    result = {
        "ok": True,
        "command": "get-project-context",
        "project_id": project_id,
        "scope_ref": scope_ref,
        "generated_at": now_iso(),
        "project_profile": project_profile,
        "decisions": decisions,
        "procedural_rules": procedural_rules,
        "policies": policies,
        "truncated": False,
        "bytes_used": 0,
    }

    # Byte budget truncation — actually shed data in drop priority order
    def _bsize(obj):
        return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    drop_order = ["policies", "procedural_rules", "decisions"]
    if _bsize(result) > max_bytes:
        for section_key in drop_order:
            if _bsize(result) <= max_bytes:
                break
            if isinstance(result.get(section_key), list):
                while result[section_key] and _bsize(result) > max_bytes:
                    result[section_key].pop()
                    result["truncated"] = True

    result["bytes_used"] = _bsize(result)
    return result


def cmd_get_task_context(args, conn, config) -> dict:
    """Assemble and return task-level context."""
    project_id = getattr(args, "project_id", None) or config.get("project_id", "")
    task_id = args.task_id
    session_id = getattr(args, "session_id", None)
    max_bytes = getattr(args, "max_bytes", 16000)
    include_project = getattr(args, "include_project", False)

    task_scope = "task/{}".format(task_id)

    # Fetch task_snapshot
    rows = fetch_active_entries_by_scope_and_type(conn, task_scope, "task_snapshot")
    task_snapshot = _entry_to_dict(rows[0]) if rows else None

    # Fetch session_snapshot if session_id given
    session_snapshot = None
    if session_id:
        session_scope = "session/{}".format(session_id)
        rows = fetch_active_entries_by_scope_and_type(
            conn, session_scope, "session_snapshot"
        )
        session_snapshot = _entry_to_dict(rows[0]) if rows else None

    # Fetch decisions at task (and session) scope
    decisions = []
    decision_scopes = [task_scope]
    if session_id:
        decision_scopes.append("session/{}".format(session_id))
    for sc in decision_scopes:
        rows = fetch_active_entries_by_scope_and_type(conn, sc, "decision")
        for r in rows:
            decisions.append(_entry_to_dict(r))

    # Project context
    project_context = None
    if include_project:
        ctx = render_context(
            conn,
            "project/{}".format(project_id),
            project_id,
            max_bytes=max_bytes,
        )
        project_context = ctx

    scope_ref = task_scope

    result = {
        "ok": True,
        "command": "get-task-context",
        "project_id": project_id,
        "scope_ref": scope_ref,
        "generated_at": now_iso(),
        "task_snapshot": task_snapshot,
        "session_snapshot": session_snapshot,
        "decisions": decisions,
        "project_context": project_context,
        "truncated": False,
        "bytes_used": 0,
    }

    # Byte budget truncation — actually shed data in drop priority order
    def _bsize(obj):
        return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    drop_order_task = ["project_context", "decisions", "session_snapshot"]
    if _bsize(result) > max_bytes:
        for section_key in drop_order_task:
            if _bsize(result) <= max_bytes:
                break
            if isinstance(result.get(section_key), list):
                while result[section_key] and _bsize(result) > max_bytes:
                    result[section_key].pop()
                    result["truncated"] = True
            elif result.get(section_key) is not None:
                result[section_key] = None
                result["truncated"] = True

    result["bytes_used"] = _bsize(result)
    return result


def cmd_search_memory(args, conn, config) -> dict:
    """Run FTS/semantic/hybrid search and return results."""
    project_id = getattr(args, "project_id", None) or config.get("project_id", "")
    query = args.query
    scope = getattr(args, "scope", None)
    type_filter = getattr(args, "type", None)
    limit = getattr(args, "limit", 20)
    include_history = getattr(args, "include_history", False)
    fmt = getattr(args, "format", "json")
    mode = getattr(args, "mode", "auto")
    mode_requested = mode  # preserve original request before any resolution

    # Determine vector availability
    try:
        from ..vector.enabled import is_vector_enabled, load_sqlite_vec
        from ..vector.provider import FastEmbedProvider

        vec_loaded = load_sqlite_vec(conn)
        vec_available = vec_loaded and is_vector_enabled(conn)
    except Exception:
        vec_available = False

    # Resolve actual mode
    if mode == "auto":
        from ..vector.search import select_search_mode

        mode_used = select_search_mode(query, vec_available)
    else:
        mode_used = mode

    # Run search
    raw = []
    if mode_used == "fts" or not vec_available:
        # FTS path (also the fallback for semantic/hybrid when vec unavailable)
        raw = search_fts(
            conn,
            query,
            scope_ref=scope,
            type_filter=type_filter,
            limit=limit,
            include_history=include_history,
        )
        mode_used = "fts"
    elif mode_used == "semantic":
        try:
            provider = FastEmbedProvider()
            from ..vector.search import search_semantic

            raw = search_semantic(conn, query, provider, limit=limit, scope_ref=scope)
        except Exception:
            raw = search_fts(
                conn,
                query,
                scope_ref=scope,
                type_filter=type_filter,
                limit=limit,
                include_history=include_history,
            )
            mode_used = "fts"
    elif mode_used == "hybrid":
        try:
            provider = FastEmbedProvider()
            from ..vector.search import search_hybrid

            raw = search_hybrid(conn, query, provider, limit=limit, scope_ref=scope)
        except Exception:
            raw = search_fts(
                conn,
                query,
                scope_ref=scope,
                type_filter=type_filter,
                limit=limit,
                include_history=include_history,
            )
            mode_used = "fts"

    formatted = format_search_results(raw, format_=fmt)

    result = {
        "ok": True,
        "command": "search-memory",
        "project_id": project_id,
        "generated_at": now_iso(),
        "mode_used": mode_used,
    }
    result.update(formatted)

    if (
        mode_requested in ("semantic", "hybrid")
        and mode_used == "fts"
        and not vec_available
    ):
        result["vector_unavailable"] = True
        result["setup_hint"] = (
            "Vector search is not available. "
            "Run '.contexts/run setup-vector' to enable semantic/hybrid search. "
            "Use '.contexts/run setup-vector --dry-run' to see disk/time requirements first."
        )

    return result


def cmd_update_task_context(args, conn, config) -> dict:
    """Update (or create) a task or session snapshot with CAS."""
    project_id = getattr(args, "project_id", None) or config.get("project_id", "")
    task_id = args.task_id
    session_id = getattr(args, "session_id", None)
    expected_revision = args.expected_revision
    from_file = getattr(args, "from_file", None)
    use_stdin = getattr(args, "stdin", False)
    change_reason = getattr(args, "change_reason", None)

    if from_file and use_stdin:
        raise InvalidArg("Use either --from-file or --stdin, not both")

    # Parse optional JSON array args
    tags = None
    tags_raw = getattr(args, "tags", None)
    if tags_raw:
        try:
            tags = json.loads(tags_raw)
        except json.JSONDecodeError:
            raise InvalidArg("--tags must be a JSON array")

    related_files = None
    rf_raw = getattr(args, "related_files", None)
    if rf_raw:
        try:
            related_files = json.loads(rf_raw)
        except json.JSONDecodeError:
            raise InvalidArg("--related-files must be a JSON array")

    # Determine scope and entry type
    if session_id:
        scope_ref = "session/{}".format(session_id)
        scope_level = "session"
        entry_type = "session_snapshot"
        entry_key = session_id
    else:
        scope_ref = "task/{}".format(task_id)
        scope_level = "task"
        entry_type = "task_snapshot"
        entry_key = task_id

    # Read payload
    payload = read_payload(from_file=from_file)
    validate_payload(entry_type, payload)

    mc = mutation_class(entry_type, scope_level)

    db_dir = config.get("_db_dir")
    if not db_dir:
        from ..core.config import resolve_db_path

        db_path = resolve_db_path(getattr(args, "db_path", None))
        db_dir = db_path.parent

    with WriteLock(db_dir, command="update-task-context"):
        result = write_entry_transaction(
            conn,
            project_id=project_id,
            entry_type=entry_type,
            key=entry_key,
            scope_ref=scope_ref,
            scope_level=scope_level,
            payload=payload,
            mutation_class=mc,
            expected_revision=expected_revision,
            change_reason=change_reason,
            tags=tags,
            related_files=related_files,
            task_id=task_id,
            session_id=session_id,
            load_policy=DEFAULT_LOAD_POLICY.get(entry_type, "on_task_start"),
        )

    response = {
        "ok": True,
        "command": "update-task-context",
        "project_id": project_id,
        "scope_ref": scope_ref,
        "generated_at": now_iso(),
    }
    response.update(result)

    return response


def cmd_log_decision(args, conn, config) -> dict:
    """Log a decision entry."""
    project_id = getattr(args, "project_id", None) or config.get("project_id", "")
    key = args.key
    from_file = getattr(args, "from_file", None)
    change_reason = getattr(args, "change_reason", None)
    derived_from_raw = getattr(args, "derived_from", None)
    confidence = getattr(args, "confidence", None)

    tags = None
    tags_raw = getattr(args, "tags", None)
    if tags_raw:
        try:
            tags = json.loads(tags_raw)
        except json.JSONDecodeError:
            raise InvalidArg("--tags must be a JSON array")

    derived_from = None
    if derived_from_raw:
        try:
            derived_from = json.loads(derived_from_raw)
        except json.JSONDecodeError:
            derived_from = [derived_from_raw]

    scope_ref, scope_level = resolve_scope_from_args(args, config)

    payload = read_payload(from_file=from_file)
    validate_payload("decision", payload)

    mc = mutation_class("decision", scope_level)

    db_dir = config.get("_db_dir")
    if not db_dir:
        from ..core.config import resolve_db_path

        db_path = resolve_db_path(getattr(args, "db_path", None))
        db_dir = db_path.parent

    with WriteLock(db_dir, command="log-decision"):
        result = write_entry_transaction(
            conn,
            project_id=project_id,
            entry_type="decision",
            key=key,
            scope_ref=scope_ref,
            scope_level=scope_level,
            payload=payload,
            mutation_class=mc,
            change_reason=change_reason,
            tags=tags,
            confidence=confidence,
            derived_from=derived_from,
            load_policy=DEFAULT_LOAD_POLICY.get("decision", "on_task_start"),
        )

    response = {
        "ok": True,
        "command": "log-decision",
        "project_id": project_id,
        "scope_ref": scope_ref,
        "generated_at": now_iso(),
    }
    response.update(result)

    return response


def cmd_log_episode(args, conn, config) -> dict:
    """Log an episode entry."""
    project_id = getattr(args, "project_id", None) or config.get("project_id", "")
    task_id = getattr(args, "task_id", None)
    session_id = getattr(args, "session_id", None)
    from_file = getattr(args, "from_file", None)
    change_reason = getattr(args, "change_reason", None)

    if not task_id:
        raise InvalidArg("--task-id is required")

    if session_id:
        scope_ref = "session/{}".format(session_id)
        scope_level = "session"
    else:
        scope_ref = "task/{}".format(task_id)
        scope_level = "task"

    payload = read_payload(from_file=from_file)
    validate_payload("episode", payload)

    allowed_fields = {
        "observation",
        "thoughts",
        "action",
        "result",
        "lesson",
        "environment",
    }
    payload = {k: v for k, v in payload.items() if k in allowed_fields}

    key = now_iso()
    mc = mutation_class("episode", scope_level)

    db_dir = config.get("_db_dir")
    if not db_dir:
        from ..core.config import resolve_db_path

        db_path = resolve_db_path(getattr(args, "db_path", None))
        db_dir = db_path.parent

    with WriteLock(db_dir, command="log-episode"):
        result = write_entry_transaction(
            conn,
            project_id=project_id,
            entry_type="episode",
            key=key,
            scope_ref=scope_ref,
            scope_level=scope_level,
            payload=payload,
            mutation_class=mc,
            change_reason=change_reason,
            load_policy=DEFAULT_LOAD_POLICY.get("episode", "on_explicit_search"),
        )

    response = {
        "ok": True,
        "command": "log-episode",
        "project_id": project_id,
        "scope_ref": scope_ref,
        "generated_at": now_iso(),
    }
    response.update(result)
    return response


def cmd_propose_change(args, conn, config) -> dict:
    """Propose a new entry (always status=pending, never auto-activates)."""
    project_id = getattr(args, "project_id", None) or config.get("project_id", "")
    entry_type = args.entry_type
    key = args.key
    scope_str = args.scope
    change_reason = args.change_reason
    base_entry_id = getattr(args, "base_entry_id", None)
    from_file = getattr(args, "from_file", None)
    derived_from_raw = getattr(args, "derived_from", None)

    derived_from = None
    if derived_from_raw:
        try:
            derived_from = json.loads(derived_from_raw)
        except json.JSONDecodeError:
            derived_from = [derived_from_raw]

    scope_level, _ = parse_scope_ref(scope_str)
    scope_ref = scope_str

    payload = read_payload(from_file=from_file)
    validate_payload(entry_type, payload)

    db_dir = config.get("_db_dir")
    if not db_dir:
        from ..core.config import resolve_db_path

        db_path = resolve_db_path(getattr(args, "db_path", None))
        db_dir = db_path.parent

    with WriteLock(db_dir, command="propose-change"):
        conn.execute("BEGIN IMMEDIATE")
        try:
            entry_id = insert_entry(
                conn,
                project_id=project_id,
                entry_type=entry_type,
                key=key,
                scope_ref=scope_ref,
                scope_level=scope_level,
                payload=payload,
                status="pending",
                revision=1,
                load_policy=DEFAULT_LOAD_POLICY.get(entry_type, "on_task_start"),
                author="agent",
                change_reason=change_reason,
                derived_from=derived_from,
                supersedes_id=base_entry_id,
            )

            event_id = append_event(
                conn,
                event_type="insert",
                subject_family="memory",
                project_id=project_id,
                scope_ref=scope_ref,
                subject_id=entry_id,
                actor="agent",
                reason=change_reason,
            )

            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise

    return {
        "ok": True,
        "command": "propose-change",
        "project_id": project_id,
        "scope_ref": scope_ref,
        "generated_at": now_iso(),
        "entry_id": entry_id,
        "status": "pending",
        "active_changed": False,
        "approval_required": True,
        "event_id": event_id,
    }
