#!/usr/bin/env bash
# PreToolUse hook: if session snapshot is stale, re-inject context
# Throttled to run at most once per 5 minutes.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
CONTEXTS_RUN="$REPO_ROOT/.contexts/run"

[ -x "$CONTEXTS_RUN" ] || exit 0
[ "${CONTEXTS_ENABLED:-1}" = "0" ] && exit 0
[ -f "$REPO_ROOT/.contexts/local/config.json" ] || exit 0

# Throttle: only run once per 5 minutes
THROTTLE_FILE="${TMPDIR:-/tmp}/contexts_hook_throttle"
if [[ -f $THROTTLE_FILE ]]; then
  last_run=$(cat "$THROTTLE_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  if ((now - last_run < 300)); then
    exit 0
  fi
fi
date +%s >"$THROTTLE_FILE"

TASK_ID="${CONTEXTS_CURRENT_TASK_ID-}"
[ -n "$TASK_ID" ] || exit 0

"$CONTEXTS_RUN" get-task-context \
  --task-id "$TASK_ID" \
  --include-project \
  --max-bytes 8000 \
  --format markdown 2>/dev/null || true
