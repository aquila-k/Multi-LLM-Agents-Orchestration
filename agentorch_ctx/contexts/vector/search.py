"""
Vector and hybrid search for the --mode extension to search-memory.
"""

from __future__ import annotations

import sqlite3

from .projection import cjk_char_ratio


def normalize_query_en(query: str) -> str:
    """
    Simple English normalization. If query appears to be Japanese (CJK chars > 10%),
    return it as-is (we can't translate locally without a model).
    Otherwise return query stripped. This is a best-effort normalizer.
    """
    if not query:
        return query
    if cjk_char_ratio(query) > 0.10:
        return query
    return query.strip()


def select_search_mode(query: str, vec_available: bool) -> str:
    """
    Auto-select search mode based on query characteristics.
    Rules:
    - If vec_available is False: always return "fts"
    - If query looks like an identifier/filename (no spaces, has _, /, or .): return "fts"
    - If query is 1-2 words: return "fts"
    - Otherwise: return "hybrid"
    Returns: "fts", "semantic", or "hybrid"
    """
    if not vec_available:
        return "fts"

    stripped = query.strip()

    # Identifier/filename heuristic: no spaces and contains _, / or .
    if " " not in stripped and any(c in stripped for c in ("_", "/", ".")):
        return "fts"

    # Word count heuristic
    words = stripped.split()
    if len(words) <= 2:
        return "fts"

    return "hybrid"


def search_semantic(
    conn: sqlite3.Connection,
    query: str,
    provider,
    limit: int = 20,
    scope_ref: str = None,
) -> list[dict]:
    """
    Semantic-only search.
    1. Normalize query to English
    2. Embed query via provider
    3. Get top-N from vec_memory_entries via search_vec()
    4. Join with entry_revisions to get type, key, scope_ref, status
    5. Filter by scope_ref if given (prefix match)
    6. Return list of {entry_id, type, key, scope_ref, status, score, match_mode: "semantic"}
    """
    from .vec_store import search_vec

    normalized = normalize_query_en(query)
    embeddings = provider.embed_texts([normalized])
    if not embeddings:
        return []

    query_embedding = embeddings[0]
    vec_results = search_vec(conn, query_embedding, limit=limit * 2)

    if not vec_results:
        return []

    entry_ids = [r["entry_id"] for r in vec_results]
    dist_map = {r["entry_id"]: r["distance"] for r in vec_results}

    placeholders = ",".join("?" for _ in entry_ids)
    try:
        rows = conn.execute(
            "SELECT id, type, key, scope_ref, status FROM entry_revisions "
            "WHERE id IN ({}) AND status = 'active'".format(placeholders),
            entry_ids,
        ).fetchall()
    except Exception:
        return []

    results = []
    for row in rows:
        eid = row[0] if isinstance(row, (list, tuple)) else row["id"]
        etype = row[1] if isinstance(row, (list, tuple)) else row["type"]
        ekey = row[2] if isinstance(row, (list, tuple)) else row["key"]
        escope = row[3] if isinstance(row, (list, tuple)) else row["scope_ref"]
        estatus = row[4] if isinstance(row, (list, tuple)) else row["status"]

        if scope_ref is not None:
            if not (escope == scope_ref or escope.startswith(scope_ref + "/")):
                continue

        distance = dist_map.get(eid, 1.0)
        score = max(0.0, 1.0 - distance)

        results.append(
            {
                "entry_id": eid,
                "type": etype,
                "key": ekey,
                "scope_ref": escope,
                "status": estatus,
                "score": score,
                "excerpt": "",
                "match_mode": "semantic",
            }
        )

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def search_hybrid(
    conn: sqlite3.Connection,
    query: str,
    provider,
    limit: int = 20,
    scope_ref: str = None,
) -> list[dict]:
    """
    Hybrid search: FTS + semantic, merged via reciprocal rank fusion (RRF).

    RRF formula: score = sum(1 / (k + rank)) for k=60

    Steps:
    1. Run FTS (top limit*2)
    2. Run semantic (top limit*2)
    3. Assign ranks, compute RRF score
    4. Merge: union of both result sets
    5. Sort by RRF score descending
    6. Return top limit results with match_mode: "hybrid"
    """
    from ..db.fts import search_fts

    k = 60

    fts_results = search_fts(conn, query, scope_ref=scope_ref, limit=limit * 2)
    sem_results = search_semantic(
        conn, query, provider, limit=limit * 2, scope_ref=scope_ref
    )

    # Build rank maps (1-indexed)
    fts_rank_map: dict[str, int] = {}
    for i, r in enumerate(fts_results, start=1):
        fts_rank_map[r["entry_id"]] = i

    sem_rank_map: dict[str, int] = {}
    for i, r in enumerate(sem_results, start=1):
        sem_rank_map[r["entry_id"]] = i

    # Collect all unique entry_ids
    all_ids = set(fts_rank_map.keys()) | set(sem_rank_map.keys())

    # Build lookup for metadata
    meta: dict[str, dict] = {}
    for r in fts_results:
        meta[r["entry_id"]] = r
    for r in sem_results:
        if r["entry_id"] not in meta:
            meta[r["entry_id"]] = r

    merged = []
    for eid in all_ids:
        fts_rank = fts_rank_map.get(eid)
        vec_rank = sem_rank_map.get(eid)

        rrf_score = 0.0
        if fts_rank is not None:
            rrf_score += 1.0 / (k + fts_rank)
        if vec_rank is not None:
            rrf_score += 1.0 / (k + vec_rank)

        entry_meta = meta[eid]
        merged.append(
            {
                "entry_id": eid,
                "type": entry_meta.get("type", ""),
                "key": entry_meta.get("key", ""),
                "scope_ref": entry_meta.get("scope_ref", ""),
                "status": entry_meta.get("status", ""),
                "score": rrf_score,
                "excerpt": entry_meta.get("excerpt", ""),
                "match_mode": "hybrid",
                "score_components": {
                    "fts_rank": fts_rank,
                    "vec_rank": vec_rank,
                    "rrf_score": rrf_score,
                },
            }
        )

    merged.sort(key=lambda x: x["score"], reverse=True)
    return merged[:limit]
