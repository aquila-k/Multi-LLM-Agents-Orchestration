#!/usr/bin/env bash
# SessionStart hook: recover the active task ID and inject stored context.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
CONTEXTS_RUN="$REPO_ROOT/.contexts/run"
PYTHON_BIN="${PYTHON_BIN:-python3}"

[ -x "$CONTEXTS_RUN" ] || exit 0
[ "${CONTEXTS_ENABLED:-1}" = "0" ] && exit 0
[ -f "$REPO_ROOT/.contexts/local/config.json" ] || exit 0

resolve_task_id() {
  if [ -n "${CONTEXTS_CURRENT_TASK_ID:-}" ]; then
    printf '%s' "$CONTEXTS_CURRENT_TASK_ID"
    return 0
  fi

  if PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON_BIN" -m agentorch_ctx task current --provider claude 2>/dev/null; then
    return 0
  fi

  if PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON_BIN" -m agentorch_ctx task current 2>/dev/null; then
    return 0
  fi

  return 1
}

TASK_ID="$(resolve_task_id || true)"

if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -n "$TASK_ID" ]; then
  printf 'export CONTEXTS_CURRENT_TASK_ID=%q\n' "$TASK_ID" >> "$CLAUDE_ENV_FILE"
fi

if [ -n "$TASK_ID" ]; then
  CONTEXT_MARKDOWN="$($CONTEXTS_RUN get-task-context \
    --task-id "$TASK_ID" \
    --include-project \
    --max-bytes "${CONTEXTS_BYTE_BUDGET:-8000}" \
    --format markdown 2>/dev/null || true)"
else
  CONTEXT_MARKDOWN="$($CONTEXTS_RUN get-project-context \
    --max-bytes "${CONTEXTS_BYTE_BUDGET:-8000}" \
    --format markdown 2>/dev/null || true)"
fi

[ -n "$CONTEXT_MARKDOWN" ] || exit 0

HOOK_CONTEXT="$CONTEXT_MARKDOWN" "$PYTHON_BIN" - <<'PY'
import json
import os

context = os.environ.get("HOOK_CONTEXT", "").strip()
if not context:
    raise SystemExit(0)

print(
    json.dumps(
        {
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            },
        }
    )
)
PY
