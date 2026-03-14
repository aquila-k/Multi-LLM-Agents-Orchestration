"""Context assembly engine with byte-budget truncation."""

import json
import math
from datetime import datetime, timezone

from ..core.ids import now_iso
from ..db.query import (
    fetch_active_entries_by_scope_and_type,
    fetch_active_policies_by_scope,
)


def _entry_to_dict(row) -> dict:
    """Convert sqlite3.Row from entry_revisions to response dict."""
    d = {
        "id": row["id"],
        "type": row["type"],
        "key": row["key"],
        "scope_ref": row["scope_ref"],
        "status": row["status"],
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    payload_raw = row["payload_json"]
    if payload_raw:
        try:
            d["payload"] = json.loads(payload_raw)
        except (json.JSONDecodeError, TypeError):
            d["payload"] = {}
    else:
        d["payload"] = {}

    tags_raw = row["tags_json"] if "tags_json" in row.keys() else None
    if tags_raw:
        try:
            d["tags"] = json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
    else:
        d["tags"] = []

    related_raw = (
        row["related_files_json"] if "related_files_json" in row.keys() else None
    )
    if related_raw:
        try:
            d["related_files"] = json.loads(related_raw)
        except (json.JSONDecodeError, TypeError):
            d["related_files"] = []
    else:
        d["related_files"] = []

    d["change_reason"] = row["change_reason"] if "change_reason" in row.keys() else None
    d["author"] = row["author"] if "author" in row.keys() else "agent"
    d["confidence"] = row["confidence"] if "confidence" in row.keys() else None

    return d


def _policy_to_dict(row) -> dict:
    """Convert sqlite3.Row from policy_revisions to response dict."""
    return {
        "id": row["id"],
        "key": row["key"],
        "scope_ref": row["scope_ref"],
        "target_kind": row["target_kind"],
        "match_pattern": row["match_pattern"],
        "enforcement": row["enforcement"],
        "rationale": row["rationale"] if "rationale" in row.keys() else None,
        "status": row["status"],
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _byte_size(obj) -> int:
    """Compute byte size of a JSON-serializable object."""
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def render_context(
    conn,
    scope_ref: str,
    project_id: str,
    max_bytes: int = 32000,
    include_project: bool = False,
    include_episodes: bool = False,
) -> dict:
    """
    Assembles a context dict from active entries.

    Section order (8 sections, dropped in reverse order when over budget):
      8. episodes (optional, dropped first)
      7. procedural_rules
      6. decisions
      5. session_snapshot
      4. task_snapshot
      3. tools (from project_profile)
      2. constraints (from project_profile)
      1. project_profile.goal + non_goals (last to drop)

    Returns dict with all context sections and metadata.
    """
    from ..core.scope import parse_scope_ref

    scope_level, scope_id = parse_scope_ref(scope_ref)
    project_scope = "project/{}".format(project_id)

    # Gather project-level data
    project_profile = None
    pp_rows = fetch_active_entries_by_scope_and_type(
        conn, project_scope, "project_profile"
    )
    if pp_rows:
        project_profile = _entry_to_dict(pp_rows[0])

    # Gather decisions from relevant scopes
    decisions = []
    decision_scopes = [scope_ref]
    if scope_level != "project" and (
        include_project or scope_level in ("task", "session")
    ):
        decision_scopes.append(project_scope)
    for sc in decision_scopes:
        rows = fetch_active_entries_by_scope_and_type(conn, sc, "decision")
        for r in rows:
            decisions.append(_entry_to_dict(r))

    # Gather procedural_rules from relevant scopes
    procedural_rules = []
    for sc in decision_scopes:
        rows = fetch_active_entries_by_scope_and_type(conn, sc, "procedural_rule")
        for r in rows:
            procedural_rules.append(_entry_to_dict(r))

    # Task snapshot — only fetchable at task scope.
    # For session scope, task_id is not known from scope_ref alone,
    # so task_snapshot is omitted; callers needing it should query task scope directly.
    task_snapshot = None
    if scope_level == "task":
        rows = fetch_active_entries_by_scope_and_type(conn, scope_ref, "task_snapshot")
        if rows:
            task_snapshot = _entry_to_dict(rows[0])

    # Session snapshot
    session_snapshot = None
    if scope_level == "session":
        rows = fetch_active_entries_by_scope_and_type(
            conn, scope_ref, "session_snapshot"
        )
        if rows:
            session_snapshot = _entry_to_dict(rows[0])

    # Episodes
    episodes = []
    if include_episodes:
        rows = fetch_active_entries_by_scope_and_type(conn, scope_ref, "episode")
        for r in rows:
            episodes.append(_entry_to_dict(r))

    # Policies
    policies = []
    policy_scopes = [scope_ref]
    if scope_level != "project":
        policy_scopes.append(project_scope)
    for sc in policy_scopes:
        rows = fetch_active_policies_by_scope(conn, sc)
        for r in rows:
            policies.append(_policy_to_dict(r))

    # Build context sections in priority order (1=highest, 8=lowest)
    # We build the result dict and then apply byte budget
    context = {
        "project_profile": project_profile,
        "decisions": decisions,
        "procedural_rules": procedural_rules,
        "task_snapshot": task_snapshot,
        "session_snapshot": session_snapshot,
        "policies": policies,
    }
    if include_episodes:
        context["episodes"] = episodes

    # Apply byte budget — drop sections in reverse priority order
    # Priority (lowest number = keep longest):
    #   1. project_profile (goal/non_goals)
    #   2. constraints (from project_profile payload)
    #   3. tools (from project_profile payload)
    #   4. task_snapshot
    #   5. session_snapshot
    #   6. decisions
    #   7. procedural_rules
    #   8. episodes
    truncated = False
    current_size = _byte_size(context)

    if current_size > max_bytes:
        # Drop sections in reverse priority
        drop_order = [
            "episodes",
            "procedural_rules",
            "decisions",
            "session_snapshot",
            "task_snapshot",
            "policies",
        ]
        for section_key in drop_order:
            if current_size <= max_bytes:
                break
            if section_key in context and context[section_key]:
                if (
                    isinstance(context[section_key], list)
                    and len(context[section_key]) > 0
                ):
                    # Try partial truncation first
                    while (
                        len(context[section_key]) > 0
                        and _byte_size(context) > max_bytes
                    ):
                        context[section_key].pop()
                        truncated = True
                    current_size = _byte_size(context)
                elif isinstance(context[section_key], dict):
                    context[section_key] = None
                    truncated = True
                    current_size = _byte_size(context)

        # If still over, truncate project_profile payload
        if _byte_size(context) > max_bytes and context.get("project_profile"):
            pp = context["project_profile"]
            if isinstance(pp, dict) and "payload" in pp:
                payload = pp["payload"]
                # Remove optional fields in order
                for field in ["tools", "constraints", "non_goals"]:
                    if field in payload:
                        del payload[field]
                        truncated = True
                        if _byte_size(context) <= max_bytes:
                            break
            current_size = _byte_size(context)

    bytes_used = _byte_size(context)
    context["truncated"] = truncated
    context["bytes_used"] = bytes_used

    return context


class RecencyWeightedRender:
    """
    Recency-weighted context renderer.
    Scores entries by recency and returns highest-priority items within byte budget.
    """

    def __init__(self, conn, scope_ref: str, max_bytes: int = 16000):
        self.conn = conn
        self.scope_ref = scope_ref
        self.max_bytes = max_bytes

    def _score(self, item: dict) -> float:
        """Compute recency score: priority × exp(-λ × age_in_hours), λ=0.1."""
        priority = float(item.get("priority") or 1.0)
        updated_raw = item.get("updated_at") or item.get("created_at") or ""
        try:
            if updated_raw.endswith("Z"):
                updated_raw = updated_raw[:-1] + "+00:00"
            updated_dt = datetime.fromisoformat(updated_raw)
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            age_hours = (now - updated_dt).total_seconds() / 3600.0
        except (ValueError, AttributeError):
            age_hours = 0.0
        lam = 0.1
        return priority * math.exp(-lam * age_hours)

    def _sort_desc(self, rows):
        return sorted(rows, key=self._score, reverse=True)

    def render(self) -> dict:
        """
        Returns context dict with entries scored and sorted by recency.
        Scoring: entries updated more recently get higher weight.
        Priority order (same as render_context but recency-weighted):
          1. project_profile
          2. decisions
          3. task_snapshot
          4. procedural_rules
          5. episodes
        """
        from ..core.scope import parse_scope_ref

        scope_level, _ = parse_scope_ref(self.scope_ref)

        project_id = ""
        project_rows = fetch_active_entries_by_scope_and_type(
            self.conn,
            self.scope_ref if scope_level == "project" else "",
            "project_profile",
        )
        if scope_level == "project" and self.scope_ref.startswith("project/"):
            project_id = self.scope_ref.split("/", 1)[1]
        if scope_level != "project":
            row = self.conn.execute(
                "SELECT project_id FROM entry_revisions WHERE scope_ref = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (self.scope_ref,),
            ).fetchone()
            if row and "project_id" in row.keys():
                project_id = row["project_id"] or ""

        base = render_context(
            self.conn,
            self.scope_ref,
            project_id,
            max_bytes=max(self.max_bytes * 3, self.max_bytes),
            include_episodes=True,
        )

        if not project_rows and project_id:
            project_rows = fetch_active_entries_by_scope_and_type(
                self.conn, "project/{}".format(project_id), "project_profile"
            )

        project_profile = (
            _entry_to_dict(project_rows[0])
            if project_rows
            else base.get("project_profile")
        )

        decisions = self._sort_desc(base.get("decisions") or [])
        procedural_rules = self._sort_desc(base.get("procedural_rules") or [])
        episodes = self._sort_desc(base.get("episodes") or [])
        task_snapshot = base.get("task_snapshot")
        session_snapshot = base.get("session_snapshot")
        policies = self._sort_desc(base.get("policies") or [])

        context = {
            "project_profile": project_profile,
            "decisions": decisions,
            "procedural_rules": procedural_rules,
            "task_snapshot": task_snapshot,
            "session_snapshot": session_snapshot,
            "policies": policies,
            "episodes": episodes,
        }

        truncated = False
        if _byte_size(context) > self.max_bytes:
            list_drop_order = ["episodes", "procedural_rules", "decisions", "policies"]
            for key in list_drop_order:
                while context.get(key) and _byte_size(context) > self.max_bytes:
                    context[key].pop()
                    truncated = True
                if _byte_size(context) <= self.max_bytes:
                    break

            if _byte_size(context) > self.max_bytes and context.get("session_snapshot"):
                context["session_snapshot"] = None
                truncated = True
            if _byte_size(context) > self.max_bytes and context.get("task_snapshot"):
                context["task_snapshot"] = None
                truncated = True

            if _byte_size(context) > self.max_bytes and context.get("project_profile"):
                pp = context["project_profile"]
                if isinstance(pp, dict):
                    payload = pp.get("payload")
                    if isinstance(payload, dict):
                        for field in ("tools", "constraints", "non_goals"):
                            if (
                                field in payload
                                and _byte_size(context) > self.max_bytes
                            ):
                                del payload[field]
                                truncated = True

        context["truncated"] = truncated
        context["bytes_used"] = _byte_size(context)
        return context


def render_context_recency_weighted(
    conn,
    scope_ref: str,
    project_id: str,
    max_bytes: int,
) -> dict:
    renderer = RecencyWeightedRender(conn, scope_ref=scope_ref, max_bytes=max_bytes)
    return renderer.render()
