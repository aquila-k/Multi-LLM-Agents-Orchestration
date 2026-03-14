"""
rebuild-vector-index: full or partial rebuild of vector projections and embeddings.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from ..core.ids import now_iso
from .projection import (
    PROJECTION_SCHEMA_VERSION,
    build_search_text_en,
    detect_source_language,
    hash_json,
    hash_text,
)
from .vec_store import delete_vec, ensure_vec_table, upsert_vec


def rebuild_vector_index(
    conn: sqlite3.Connection,
    provider,                  # EmbeddingProvider
    mode: str = "full",        # "full" or "partial"
    since: str = None,         # ISO timestamp or revision int, for partial mode
    scope_ref: str = None,     # filter by scope prefix
    entry_type: str = None,    # filter by type
    dry_run: bool = False,
    batch_size: int = 32,
) -> dict:
    """
    Rebuild vector projections and embeddings.

    Full mode:
    - Query all active entries from entry_revisions
    - For each: build search_text_en, embed, upsert vec and projection
    - Remove stale vec entries (in vec table but not in active entries)
    - Update vector_index_state.last_full_rebuild_at

    Partial mode:
    - Only entries updated since `since` timestamp (or with revision >= since)
    - Respects scope_ref and entry_type filters

    Dry run: count what would be processed, don't write anything.

    Returns dict: {run_id, mode, processed, skipped, failed, duration_ms, dry_run}
    """
    start_ms = time.monotonic()
    run_id = str(uuid.uuid4())
    started_at = now_iso()

    processed = 0
    skipped = 0
    failed = 0
    provider_model_id = ""

    # Fetch entries to rebuild
    entries = _fetch_entries_for_rebuild(conn, mode, since, scope_ref, entry_type)

    if dry_run:
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        return {
            "run_id": run_id,
            "mode": mode,
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "would_process": len(entries),
            "duration_ms": duration_ms,
            "dry_run": True,
        }

    if provider is None:
        raise RuntimeError("embedding provider is required for rebuild")
    provider_model_id = provider.model_id()

    # Ensure vec virtual table exists before any upsert calls
    _sql_dir = Path(__file__).parent.parent.parent / "sql"
    ensure_vec_table(conn, _sql_dir)

    # Log run start
    try:
        conn.execute(
            "INSERT OR REPLACE INTO vector_build_log "
            "(run_id, mode, started_at, processed_count, skipped_count, failed_count) "
            "VALUES (?, ?, ?, 0, 0, 0)",
            (run_id, mode, started_at),
        )
    except Exception:
        pass

    active_ids: set[str] = set()

    # Process entries in batches
    for batch_start in range(0, len(entries), batch_size):
        batch = entries[batch_start: batch_start + batch_size]

        # Collect texts to embed for non-empty entries in batch
        texts_to_embed: list[str] = []
        entries_needing_embed: list[str] = []
        batch_meta: list[dict] = []

        for entry in batch:
            entry_id = entry["id"]
            entry_type_val = entry["type"]
            key = entry["key"]
            scope_ref_val = entry["scope_ref"]
            revision = entry["revision"]
            payload_json = entry["payload_json"]
            tags_json = entry.get("tags_json")

            try:
                payload = json.loads(payload_json) if payload_json else {}
            except Exception:
                payload = {}

            try:
                tags = json.loads(tags_json) if tags_json else []
            except Exception:
                tags = []

            search_text_en = build_search_text_en(
                entry_type=entry_type_val,
                key=key,
                payload=payload,
                tags=tags,
                scope_ref=scope_ref_val,
            )
            search_text_en_hash = hash_text(search_text_en)
            canonical_json_hash = hash_json(payload)
            source_language = detect_source_language(payload, tags)

            active_ids.add(entry_id)

            meta = {
                "entry_id": entry_id,
                "entry_type": entry_type_val,
                "key": key,
                "scope_ref": scope_ref_val,
                "revision": revision,
                "search_text_en": search_text_en,
                "search_text_en_hash": search_text_en_hash,
                "canonical_json_hash": canonical_json_hash,
                "source_language": source_language,
            }
            batch_meta.append(meta)

            if search_text_en.strip():
                texts_to_embed.append(search_text_en)
                entries_needing_embed.append(entry_id)

        # Embed all texts in the batch at once
        embeddings_map: dict[str, list] = {}
        if texts_to_embed:
            try:
                embeddings = provider.embed_texts(texts_to_embed)
                for idx, eid in enumerate(entries_needing_embed):
                    if embeddings and idx < len(embeddings) and embeddings[idx]:
                        embeddings_map[eid] = embeddings[idx]
            except Exception:
                pass

        # Write projections and vec entries
        for meta in batch_meta:
            entry_id = meta["entry_id"]
            try:
                # Upsert vec if we have an embedding
                requires_embedding = bool(meta["search_text_en"].strip())
                if requires_embedding:
                    embedding = embeddings_map.get(entry_id)
                    if not embedding:
                        failed += 1
                        continue
                    if not upsert_vec(conn, entry_id, embedding):
                        failed += 1
                        continue

                # Upsert vector_projection
                _upsert_vector_projection(
                    conn,
                    entry_id=entry_id,
                    entry_type=meta["entry_type"],
                    key=meta["key"],
                    revision=meta["revision"],
                    scope_ref=meta["scope_ref"],
                    search_text_en=meta["search_text_en"],
                    search_text_en_hash=meta["search_text_en_hash"],
                    canonical_json_hash=meta["canonical_json_hash"],
                    source_language=meta["source_language"],
                    model_id=provider_model_id,
                    is_deleted=False,
                )
                processed += 1
            except Exception:
                failed += 1

    # For full rebuild: remove stale vec entries
    if mode == "full" and not scope_ref and not entry_type:
        try:
            stale_removed = _remove_stale_vec_entries(conn, active_ids)
        except Exception:
            stale_removed = 0
    else:
        stale_removed = 0

    finished_at = now_iso()
    duration_ms = int((time.monotonic() - start_ms) * 1000)

    # Update vector_index_state
    try:
        if mode == "full":
            # Set enabled=1 if the rebuild succeeded with no failures.
            _enable = 1 if failed == 0 else None
            if _enable is not None:
                conn.execute(
                    "UPDATE vector_index_state SET last_full_rebuild_at = ?, "
                    "last_incremental_at = ?, updated_at = ?, enabled = ? "
                    "WHERE index_name = 'default'",
                    (finished_at, finished_at, finished_at, _enable),
                )
            else:
                conn.execute(
                    "UPDATE vector_index_state SET last_full_rebuild_at = ?, "
                    "last_incremental_at = ?, updated_at = ? "
                    "WHERE index_name = 'default'",
                    (finished_at, finished_at, finished_at),
                )
        else:
            conn.execute(
                "UPDATE vector_index_state SET last_incremental_at = ?, updated_at = ? "
                "WHERE index_name = 'default'",
                (finished_at, finished_at),
            )
    except Exception:
        pass

    # Update build log
    try:
        conn.execute(
            "UPDATE vector_build_log SET finished_at = ?, processed_count = ?, "
            "skipped_count = ?, failed_count = ?, duration_ms = ?, summary_json = ? "
            "WHERE run_id = ?",
            (
                finished_at,
                processed,
                skipped,
                failed,
                duration_ms,
                json.dumps({"stale_removed": stale_removed}),
                run_id,
            ),
        )
    except Exception:
        pass

    return {
        "run_id": run_id,
        "mode": mode,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "stale_removed": stale_removed,
        "duration_ms": duration_ms,
        "dry_run": False,
    }


def _fetch_entries_for_rebuild(
    conn: sqlite3.Connection,
    mode: str,
    since: str,
    scope_ref: str,
    entry_type: str,
) -> list[dict]:
    """
    Fetch active entry_revisions rows matching the rebuild criteria.
    Returns list of dicts with: id, type, key, scope_ref, revision, payload_json, tags_json
    """
    conditions = ["er.status = 'active'"]
    params: list = []

    if mode == "partial" and since is not None:
        # Try to interpret since as a revision int first, then as timestamp
        try:
            since_rev = int(since)
            conditions.append("er.revision >= ?")
            params.append(since_rev)
        except (ValueError, TypeError):
            conditions.append("er.updated_at >= ?")
            params.append(since)

    if scope_ref:
        conditions.append("er.scope_ref LIKE ?")
        params.append(scope_ref + "%")

    if entry_type:
        conditions.append("er.type = ?")
        params.append(entry_type)

    where_clause = " AND ".join(conditions)
    sql = (
        "SELECT er.id, er.type, er.key, er.scope_ref, er.revision, "
        "er.payload_json, er.tags_json "
        "FROM entry_revisions er "
        "WHERE {} "
        "ORDER BY er.updated_at ASC, er.id ASC"
    ).format(where_clause)

    try:
        rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            if isinstance(row, sqlite3.Row):
                result.append({
                    "id": row["id"],
                    "type": row["type"],
                    "key": row["key"],
                    "scope_ref": row["scope_ref"],
                    "revision": row["revision"],
                    "payload_json": row["payload_json"],
                    "tags_json": row["tags_json"] if "tags_json" in row.keys() else None,
                })
            else:
                result.append({
                    "id": row[0],
                    "type": row[1],
                    "key": row[2],
                    "scope_ref": row[3],
                    "revision": row[4],
                    "payload_json": row[5],
                    "tags_json": row[6] if len(row) > 6 else None,
                })
        return result
    except Exception:
        return []


def _remove_stale_vec_entries(conn: sqlite3.Connection, active_ids: set[str]) -> int:
    """
    Remove entries from vec_memory_entries that are no longer active.
    Returns count removed.
    """
    try:
        rows = conn.execute("SELECT entry_id FROM vec_memory_entries").fetchall()
        vec_ids = {r[0] for r in rows}
        stale_ids = vec_ids - active_ids
        count = 0
        for entry_id in stale_ids:
            try:
                conn.execute(
                    "DELETE FROM vec_memory_entries WHERE entry_id = ?", (entry_id,)
                )
                count += 1
            except Exception:
                pass
        return count
    except Exception:
        return 0


def _upsert_vector_projection(
    conn: sqlite3.Connection,
    entry_id: str,
    entry_type: str,
    key: str,
    revision: int,
    scope_ref: str,
    search_text_en: str,
    search_text_en_hash: str,
    canonical_json_hash: str,
    source_language: str,
    model_id: str,
    is_deleted: bool = False,
) -> None:
    """INSERT OR REPLACE into vector_projection."""
    now = now_iso()
    conn.execute(
        "INSERT OR REPLACE INTO vector_projection ("
        "  entry_id, entry_type, logical_key, revision, scope_ref, "
        "  source_language, search_text_en, search_text_en_hash, "
        "  canonical_json_hash, projection_schema_ver, updated_at, is_deleted"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry_id,
            entry_type,
            key,
            revision,
            scope_ref,
            source_language,
            search_text_en,
            search_text_en_hash,
            canonical_json_hash,
            _projection_schema_ver(model_id),
            now,
            1 if is_deleted else 0,
        ),
    )


def _projection_schema_ver(model_id: str) -> str:
    """Model-aware projection schema version token."""
    return "{}:{}".format(PROJECTION_SCHEMA_VERSION, model_id)
