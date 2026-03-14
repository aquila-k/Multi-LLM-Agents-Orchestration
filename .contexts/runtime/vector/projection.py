"""
search_text_en generation — deterministic English projection of canonical JSON.

The generated text is the embedding target. It is NOT the canonical source.
Rules:
- Order is fixed (always same output for same input)
- Missing fields are skipped
- No Markdown syntax
- Labels are included for context
- schema_version is embedded to detect projection changes
"""

from __future__ import annotations

import hashlib
import json
import re

PROJECTION_SCHEMA_VERSION = "1"
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\uf900-\ufaff]")

# ---- Field definitions per entry type ----

_FIELDS: dict[str, list[tuple[str, str]]] = {
    "project_profile": [
        ("goal", "Goal"),
        ("constraints", "Constraints"),
        ("tech_stack", "Tech Stack"),
        ("team_context", "Team Context"),
    ],
    "task_snapshot": [
        ("task_goal", "Task Goal"),
        ("current_plan", "Current Plan"),
        ("progress", "Progress"),
        ("open_questions", "Open Questions"),
        ("blockers", "Blockers"),
        ("next_actions", "Next Actions"),
        ("relevant_files", "Relevant Files"),
        ("assumptions", "Assumptions"),
    ],
    "session_snapshot": [
        ("session_goal", "Session Goal"),
        ("working_notes", "Working Notes"),
        ("recent_actions", "Recent Actions"),
        ("pending_items", "Pending Items"),
    ],
    "decision": [
        ("decision", "Decision"),
        ("context", "Context"),
        ("reason", "Reason"),
        ("alternatives_considered", "Alternatives"),
        ("impact", "Impact"),
        ("follow_up", "Follow Up"),
    ],
    "episode": [
        ("observation", "Observation"),
        ("thoughts", "Thoughts"),
        ("action", "Action"),
        ("result", "Result"),
        ("lesson", "Lesson"),
    ],
    "procedural_rule": [
        ("name", "Rule"),
        ("instructions", "Instructions"),
        ("when_to_use", "When To Use"),
        ("checklist", "Checklist"),
        ("examples", "Examples"),
    ],
    "policy_rule": [
        ("match_pattern", "Match Pattern"),
        ("rationale", "Rationale"),
    ],
}


def _flatten_value(value: object) -> str:
    """Convert a field value to a plain string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item.strip())
            elif isinstance(item, dict):
                # e.g. list of objects — join their string values
                parts.append(" ".join(str(v) for v in item.values() if v))
        return "; ".join(p for p in parts if p)
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if v)
    return str(value)


def build_search_text_en(
    entry_type: str,
    key: str,
    payload: dict,
    tags: list | None = None,
    scope_ref: str | None = None,
) -> str:
    """
    Build the English search projection string for a given entry.

    Output format (newline-separated labelled lines):
      [scope_ver] schema_version={ver}
      [key] {key}
      [tags] tag1 tag2
      {Label}: {value}
      ...
    """
    lines: list[str] = []

    # Header
    lines.append("[schema_version] {}".format(PROJECTION_SCHEMA_VERSION))
    lines.append("[key] {}".format(key))

    if scope_ref:
        lines.append("[scope] {}".format(scope_ref))

    if tags:
        lines.append("[tags] {}".format(" ".join(str(t) for t in tags)))

    # Per-type field projection
    field_defs = _FIELDS.get(entry_type, [])
    for field_name, label in field_defs:
        raw = payload.get(field_name)
        text = _flatten_value(raw)
        if text:
            lines.append("{}: {}".format(label, text))

    return "\n".join(lines)


def hash_text(text: str) -> str:
    """SHA-256 hex digest of UTF-8 encoded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_json(payload: dict) -> str:
    """Stable SHA-256 of canonical JSON (sorted keys, no extra whitespace)."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cjk_char_ratio(text: str) -> float:
    """Return CJK character ratio for a text sample."""
    if not text:
        return 0.0
    cjk_count = len(_CJK_CHAR_RE.findall(text))
    return cjk_count / len(text)


def detect_source_language(payload: dict, tags: list | None = None) -> str:
    """
    Simple heuristic to detect the dominant language of a payload.
    Returns ISO 639-1 code ('ja', 'en', etc.) or 'und' if undetermined.
    This is best-effort only — not translation.
    """
    # Collect text to analyse
    text_parts = []
    for v in payload.values():
        if isinstance(v, str):
            text_parts.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    text_parts.append(item)
    combined = " ".join(text_parts[:3])  # sample first few values only

    if not combined.strip():
        return "und"

    if cjk_char_ratio(combined) > 0.10:
        return "ja"

    return "en"
