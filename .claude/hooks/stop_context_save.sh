#!/usr/bin/env bash
# Stop hook: save session snapshot when conversation ends.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
CONTEXTS_RUN="$REPO_ROOT/.contexts/run"

[ -x "$CONTEXTS_RUN" ] || exit 0
[ "${CONTEXTS_ENABLED:-1}" = "0" ] && exit 0
[ -f "$REPO_ROOT/.contexts/local/config.json" ] || exit 0

TASK_ID="${CONTEXTS_CURRENT_TASK_ID-}"
[ -n "$TASK_ID" ] || exit 0

# Record episode for session end
payload=$(printf '{"observation":"session ended","action":"session-stop","result":"conversation closed"}')
printf '%s' "$payload" | "$CONTEXTS_RUN" log-episode --task-id "$TASK_ID" 2>/dev/null || true
