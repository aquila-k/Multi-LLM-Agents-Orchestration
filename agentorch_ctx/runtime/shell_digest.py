from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.artifact_store import ArtifactStore


@dataclass(frozen=True)
class PersistedShellDigest:
    path: Path
    payload: dict[str, Any]


def derive_shell_digest(
    *,
    task_id: str,
    concise_summary: str,
    execution_record_ref: str = "",
    response_ref: str = "",
    validation_ref: str = "",
) -> dict[str, Any]:
    status = _derive_status(concise_summary)
    stop_reason = "approval required" if "STOP_AND_CONFIRM" in concise_summary else ""
    resume_hint = (
        _extract_token(concise_summary, "step")
        or _extract_token(concise_summary, "phase")
        or ""
    )
    facts = []
    phase = _extract_token(concise_summary, "phase")
    step = _extract_token(concise_summary, "step")
    if phase:
        facts.append(
            {
                "summary": f"requested phase={phase}",
                "status": "observed",
                "affects": ["state", "routing"],
            }
        )
    if step:
        facts.append(
            {
                "summary": f"requested step={step}",
                "status": "observed",
                "affects": ["state", "resume"],
            }
        )
    warnings = ["operator approval required"] if stop_reason else []
    return {
        "schema_version": "1.0.0",
        "task_id": task_id,
        "status": status,
        "concise_summary": concise_summary[:1024],
        "stop_reason": stop_reason,
        "resume_hint": resume_hint,
        "facts": facts,
        "warnings": warnings,
        "refs": {
            "execution_record_ref": execution_record_ref,
            "response_ref": response_ref,
            "validation_ref": validation_ref,
        },
        "created_at": _isoformat(datetime.now(timezone.utc)),
    }


def bind_shell_digest_ref(
    *,
    shell_digest: dict[str, Any],
    shell_digest_ref: str,
) -> dict[str, Any]:
    updated = deepcopy(shell_digest)
    refs = dict(updated.get("refs", {}))
    refs["shell_digest_ref"] = shell_digest_ref
    updated["refs"] = refs
    return updated


def persist_shell_digest(
    *,
    root_dir: Path,
    task_id: str,
    shell_digest: dict[str, Any],
    phase: str,
    step: str,
    filename: str,
    attempt: int = 1,
    run: int = 1,
) -> PersistedShellDigest:
    store = ArtifactStore(root_dir.resolve())
    artifact_path = store.family_dir(task_id, "shell-digests") / filename
    payload = bind_shell_digest_ref(
        shell_digest=shell_digest,
        shell_digest_ref=str(artifact_path),
    )
    record = store.write_json_artifact(
        task_id=task_id,
        family="shell-digests",
        artifact_type="shell_digest",
        payload=payload,
        filename=filename,
        phase=phase,
        step=step,
        attempt=attempt,
        run=run,
        retention_class="standard",
    )
    return PersistedShellDigest(path=record.path, payload=payload)


def ingest_shell_digest(
    *,
    known_information: dict[str, Any],
    shell_digest: dict[str, Any],
) -> dict[str, Any]:
    updated = deepcopy(known_information)
    summary = shell_digest.get("concise_summary", "")
    updated["latest_shell_digestion_summary"] = {
        "summary": summary,
        "shell_digest_ref": shell_digest.get("refs", {}).get("shell_digest_ref", "")
        or shell_digest.get("refs", {}).get("execution_record_ref", ""),
    }
    updated.setdefault("entries", [])
    for index, fact in enumerate(shell_digest.get("facts", []), start=1):
        updated["entries"].append(
            {
                "key": f"shell_digest_fact_{index}",
                "value": fact.get("summary", ""),
                "status": fact.get("status", "observed"),
                "source": shell_digest.get("refs", {}).get(
                    "execution_record_ref", "shell-digest"
                ),
                "updated_at": shell_digest.get(
                    "created_at", _isoformat(datetime.now(timezone.utc))
                ),
                "affects": fact.get("affects", []),
            }
        )
    updated["updated_at"] = shell_digest.get("created_at", updated.get("updated_at"))
    return updated


def _derive_status(summary: str) -> str:
    if "STOP_AND_CONFIRM" in summary or "blocked" in summary.lower():
        return "blocked"
    if "failed" in summary.lower():
        return "failed"
    if "partial" in summary.lower():
        return "partial"
    if "ready" in summary.lower() or "accepted" in summary.lower():
        return "running"
    return "running"


def _extract_token(summary: str, name: str) -> str:
    match = re.search(rf"{name}=([A-Za-z0-9_-]+)", summary)
    return match.group(1) if match else ""


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
