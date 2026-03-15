"""Search result formatting for the search-memory command."""

from ..core.ids import now_iso


def format_search_results(raw_results: list, format_: str = "json") -> dict:
    """
    Wrap raw FTS results (from search_fts) in the search-memory response envelope.

    Each raw result is expected to have:
      score, entry_id, type, key, scope_ref, status, excerpt
    """
    results = []
    for r in raw_results:
        item = {
            "entry_id": r.get("entry_id", ""),
            "type": r.get("type", ""),
            "key": r.get("key", ""),
            "scope_ref": r.get("scope_ref", ""),
            "status": r.get("status", ""),
            "score": r.get("score", 0.0),
            "excerpt": r.get("excerpt", ""),
        }
        results.append(item)

    return {
        "results": results,
        "total": len(results),
    }
