"""
sync-vector-index: consume dirty queue and update vector projections + embeddings.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..core.ids import now_iso
from .dirty_queue import dequeue_batch, mark_done, mark_failed
from .projection import (
    PROJECTION_SCHEMA_VERSION,
    build_search_text_en,
    detect_source_language,
    hash_json,
    hash_text,
)
from .vec_store import delete_vec, ensure_vec_table, upsert_vec


def sync_vector_index(
    conn: sqlite3.Connection,
    provider,
    max_items: int = 64,
    retry_failed: bool = False,
    owner: str = "sync-worker",
) -> dict:
    """
    Consume up to max_items from vector_dirty_queue.

    For each item:
    1. Fetch entry from entry_revisions (skip if not found / is_deleted)
    2. Compute search_text_en via build_search_text_en()
    3. Check if re-embedding is needed (compare hashes in vector_projection)
    4. If needed: embed via provider, upsert into vec_memory_entries, upsert vector_projection
    5. Mark done or failed

    Returns dict: {processed, skipped, failed, duration_ms}
    """
    start_ms = time.monotonic()
    processed = 0
    skipped = 0
    failed = 0
    provider_model_id = provider.model_id()

    try:
        batch = dequeue_batch(conn, owner=owner, max_items=max_items)
    except Exception:
        batch = []

    # Ensure vec virtual table exists before any upsert/delete calls
    _sql_dir = Path(__file__).parent.parent.parent / "sql"
    ensure_vec_table(conn, _sql_dir)

    pending_items: list[dict] = []

    for item in batch:
        queue_id = item["id"]
        entry_id = item["entry_id"]

        try:
            # Fetch entry from entry_revisions
            row = conn.execute(
                "SELECT id, type, key, scope_ref, revision, payload_json, "
                "tags_json, status FROM entry_revisions WHERE id = ?",
                (entry_id,),
            ).fetchone()

            if row is None:
                # Entry not found — might be deleted; mark done and skip
                mark_done(conn, queue_id)
                skipped += 1
                continue

            # Skip deleted/superseded/archived
            status = row["status"] if isinstance(row, sqlite3.Row) else row[7]
            if status in ("superseded", "archived"):
                # Potentially delete vec if it exists
                try:
                    delete_vec(conn, entry_id)
                except Exception:
                    pass
                _upsert_vector_projection(
                    conn,
                    entry_id=entry_id,
                    entry_type=row["type"] if isinstance(row, sqlite3.Row) else row[1],
                    key=row["key"] if isinstance(row, sqlite3.Row) else row[2],
                    revision=(
                        row["revision"] if isinstance(row, sqlite3.Row) else row[4]
                    ),
                    scope_ref=(
                        row["scope_ref"] if isinstance(row, sqlite3.Row) else row[3]
                    ),
                    search_text_en="",
                    search_text_en_hash="",
                    canonical_json_hash="",
                    source_language="und",
                    model_id=provider_model_id,
                    is_deleted=True,
                )
                mark_done(conn, queue_id)
                skipped += 1
                continue

            # Extract fields
            if isinstance(row, sqlite3.Row):
                entry_type = row["type"]
                key = row["key"]
                scope_ref = row["scope_ref"]
                revision = row["revision"]
                payload_json = row["payload_json"]
                tags_json = row["tags_json"] if "tags_json" in row.keys() else None
            else:
                entry_type = row[1]
                key = row[2]
                scope_ref = row[3]
                revision = row[4]
                payload_json = row[5]
                tags_json = row[6]

            try:
                payload = json.loads(payload_json) if payload_json else {}
            except Exception:
                payload = {}

            try:
                tags = json.loads(tags_json) if tags_json else []
            except Exception:
                tags = []

            # Build search text
            search_text_en = build_search_text_en(
                entry_type=entry_type,
                key=key,
                payload=payload,
                tags=tags,
                scope_ref=scope_ref,
            )
            search_text_en_hash = hash_text(search_text_en)
            canonical_json_hash = hash_json(payload)
            source_language = detect_source_language(payload, tags)

            # Check if re-embedding is needed
            needs_embed = _needs_reembed(
                conn,
                entry_id=entry_id,
                search_text_en_hash=search_text_en_hash,
                canonical_json_hash=canonical_json_hash,
                provider_name=provider.name(),
                model_id=provider_model_id,
                dim=provider.dimension(),
            )
            pending_items.append(
                {
                    "queue_id": queue_id,
                    "entry_id": entry_id,
                    "entry_type": entry_type,
                    "key": key,
                    "revision": revision,
                    "scope_ref": scope_ref,
                    "search_text_en": search_text_en,
                    "search_text_en_hash": search_text_en_hash,
                    "canonical_json_hash": canonical_json_hash,
                    "source_language": source_language,
                    "needs_embed": needs_embed,
                }
            )

        except Exception as exc:
            try:
                mark_failed(conn, queue_id, str(exc)[:500])
            except Exception:
                pass
            failed += 1

    # Batch embed all queue items that require embeddings.
    embed_targets = [
        it for it in pending_items if it["needs_embed"] and it["search_text_en"].strip()
    ]
    embeddings_by_queue_id: dict[int, list] = {}
    if embed_targets:
        texts = [it["search_text_en"] for it in embed_targets]
        embeddings = provider.embed_texts(texts)
        for idx, target in enumerate(embed_targets):
            if embeddings and idx < len(embeddings) and embeddings[idx]:
                embeddings_by_queue_id[target["queue_id"]] = embeddings[idx]

    for item in pending_items:
        queue_id = item["queue_id"]
        entry_id = item["entry_id"]
        try:
            if item["needs_embed"] and item["search_text_en"].strip():
                embedding = embeddings_by_queue_id.get(queue_id)
                if not embedding:
                    mark_failed(
                        conn, queue_id, "embedding generation returned empty vector"
                    )
                    failed += 1
                    continue
                if not upsert_vec(conn, entry_id, embedding):
                    mark_failed(conn, queue_id, "vec upsert failed")
                    failed += 1
                    continue

            # Upsert vector_projection regardless of whether re-embed was needed.
            _upsert_vector_projection(
                conn,
                entry_id=entry_id,
                entry_type=item["entry_type"],
                key=item["key"],
                revision=item["revision"],
                scope_ref=item["scope_ref"],
                search_text_en=item["search_text_en"],
                search_text_en_hash=item["search_text_en_hash"],
                canonical_json_hash=item["canonical_json_hash"],
                source_language=item["source_language"],
                model_id=provider_model_id,
                is_deleted=False,
            )

            mark_done(conn, queue_id)
            processed += 1
        except Exception as exc:
            try:
                mark_failed(conn, queue_id, str(exc)[:500])
            except Exception:
                pass
            failed += 1

    # Update last_incremental_at
    try:
        now = now_iso()
        conn.execute(
            "UPDATE vector_index_state SET last_incremental_at = ?, updated_at = ? "
            "WHERE index_name = 'default'",
            (now, now),
        )
    except Exception:
        pass

    duration_ms = int((time.monotonic() - start_ms) * 1000)
    return {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "duration_ms": duration_ms,
    }


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


def _needs_reembed(
    conn: sqlite3.Connection,
    entry_id: str,
    search_text_en_hash: str,
    canonical_json_hash: str,
    provider_name: str,
    model_id: str,
    dim: int,
) -> bool:
    """Check vector_projection to see if embedding is current."""
    try:
        row = conn.execute(
            "SELECT search_text_en_hash, canonical_json_hash, projection_schema_ver "
            "FROM vector_projection WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()

        if row is None:
            return True

        # Check hashes and projection schema version
        if isinstance(row, sqlite3.Row):
            stored_text_hash = row["search_text_en_hash"]
            stored_json_hash = row["canonical_json_hash"]
            stored_schema_ver = row["projection_schema_ver"]
        else:
            stored_text_hash = row[0]
            stored_json_hash = row[1]
            stored_schema_ver = row[2]

        if stored_text_hash != search_text_en_hash:
            return True
        if stored_json_hash != canonical_json_hash:
            return True
        if stored_schema_ver != _projection_schema_ver(model_id):
            return True

        # Also check if a vec entry exists
        try:
            vec_row = conn.execute(
                "SELECT 1 FROM vec_memory_entries WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if vec_row is None:
                return True
        except Exception:
            # vec table might not exist
            pass

        return False
    except Exception:
        return True


def _projection_schema_ver(model_id: str) -> str:
    """Model-aware projection schema version token."""
    return "{}:{}".format(PROJECTION_SCHEMA_VERSION, model_id)
