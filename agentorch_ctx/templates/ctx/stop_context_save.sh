#!/usr/bin/env bash
# Stop hook: persist a final task snapshot summary and log an episode.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ "${CONTEXTS_ENABLED:-1}" = "0" ] && exit 0
[ -f "$REPO_ROOT/.contexts/local/config.json" ] || exit 0

HOOK_EVENT_JSON="$(cat)"
export HOOK_EVENT_JSON

PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - "$REPO_ROOT" <<'PY'
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agentorch_ctx.runtime.context_bridge import (
    get_current_revision,
    load_task_context,
    log_episode,
    save_task_snapshot,
)


def _run_agentorch(*args: str) -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "agentorch_ctx", *args],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _resolve_task_id() -> str:
    current = os.environ.get("CONTEXTS_CURRENT_TASK_ID", "").strip()
    if current:
        return current

    for args in (("task", "current", "--provider", "claude"), ("task", "current")):
        current = _run_agentorch(*args)
        if current:
            return current.splitlines()[-1].strip()
    return ""


def _task_summary(task_id: str) -> str:
    output = _run_agentorch("task", "show", task_id)
    if not output:
        return ""
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return ""
    summary = data.get("summary")
    return summary.strip() if isinstance(summary, str) else ""


def _normalize_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    collapsed = " ".join(value.split())
    return collapsed[:limit]


repo_root = Path(sys.argv[1]).resolve()
env = os.environ.copy()
env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(repo_root)

try:
    event = json.loads(os.environ.get("HOOK_EVENT_JSON", "") or "{}")
except json.JSONDecodeError:
    event = {}

task_id = _resolve_task_id()
if not task_id:
    raise SystemExit(0)

stored = load_task_context(repo_root, task_id, include_project=False, max_bytes=8000)
snapshot = stored.get("task_snapshot") if isinstance(stored, dict) else None
payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
if not isinstance(payload, dict):
    payload = {}

payload.setdefault("task_goal", _task_summary(task_id) or f"Task {task_id}")
payload.setdefault("current_plan", payload.get("current_plan", ""))
if not isinstance(payload.get("progress"), str) or not payload.get("progress", "").strip():
    payload["progress"] = "Session ended"

for field in ("open_questions", "blockers", "relevant_files", "assumptions", "next_actions"):
    value = payload.get(field)
    if not isinstance(value, list):
        payload[field] = [] if value in (None, "") else [str(value)]

last_message = _normalize_text(event.get("last_assistant_message"), 4000)
if last_message:
    payload["last_session_summary"] = last_message

revision = get_current_revision(repo_root, task_id)
save_task_snapshot(
    repo_root,
    task_id,
    payload,
    expected_revision=revision,
    change_reason="stop hook final snapshot",
)

episode_payload = {
    "observation": "Session ended",
    "action": "Persisted final stop-hook context",
    "result": last_message or "Conversation closed",
    "semantic_hint": "stop hook recorded final assistant summary and task snapshot",
}
log_episode(
    repo_root,
    task_id,
    episode_payload,
    change_reason="stop hook final episode",
)
PY