from __future__ import annotations

from typing import Any


def render_shell_digest(digest: dict[str, Any]) -> str:
    parts = [f"status={digest.get('status', 'unknown')}"]
    if digest.get("stop_reason"):
        parts.append(f"stop={digest['stop_reason']}")
    if digest.get("resume_hint"):
        parts.append(f"resume={digest['resume_hint']}")
    return " | ".join(parts)


def render_validation(validation: dict[str, Any]) -> str:
    summary = [f"outcome={validation.get('overall_outcome', 'unknown')}"]
    codes = validation.get("apply_readiness", {}).get("codes", [])
    if codes:
        summary.append("codes=" + ",".join(codes))
    return " | ".join(summary)
