from __future__ import annotations

import re
from typing import Any

PATTERNS = [
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{8,}"), "<REDACTED:OPENAI_KEY>"),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{8,}"), "<REDACTED:GITHUB_TOKEN>"),
    (
        "bearer_token",
        re.compile(r"Bearer\s+[A-Za-z0-9._-]{8,}"),
        "Bearer <REDACTED:TOKEN>",
    ),
    (
        "password_assignment",
        re.compile(r"(?i)(password\s*[=:]\s*)(\S+)"),
        r"\1<REDACTED:PASSWORD>",
    ),
]


def redact_text(text: str) -> dict[str, Any]:
    redacted = text
    redactions: list[dict[str, Any]] = []
    for kind, pattern, replacement in PATTERNS:
        updated, count = pattern.subn(replacement, redacted)
        if count:
            redactions.append({"kind": kind, "count": count})
            redacted = updated
    confidence = 1.0 if redactions else 0.75
    return {
        "redacted_text": redacted,
        "redactions": redactions,
        "confidence": confidence,
        "safe_to_persist": confidence >= 0.75,
    }
