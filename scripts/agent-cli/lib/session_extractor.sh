#!/usr/bin/env bash
# session_extractor.sh — Extract session IDs from tool-specific sources
# Usage: source this file
#
# Functions:
#   session_snapshot_codex <snapshot_out>
#   session_snapshot_copilot <snapshot_out>
#   session_extract_codex <snapshot_file> <sid_out>
#   session_extract_copilot <snapshot_file> <sid_out>
#   session_extract_gemini <raw_log> <sid_out>
#   session_extract_for_tool <tool> ...

set -euo pipefail

SESSION_EXTRACTOR_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SESSION_EXTRACTOR_LIB_DIR}/log.sh"

# ── Snapshot functions (call BEFORE running the tool wrapper) ─────────────────

session_snapshot_codex() {
	local snapshot_out="$1"
	# Use find to enumerate all .jsonl session files (year/month/day/rollout-*.jsonl layout).
	# IMPORTANT: Use the same sessions_dir path as session_extract_codex (no trailing slash)
	# so that comm -13 path comparison is exact-match reliable.
	local sessions_dir="${HOME}/.codex/sessions"
	find "$sessions_dir" -name "*.jsonl" 2>/dev/null | LC_ALL=C sort >"$snapshot_out" || true
}

session_snapshot_copilot() {
	local snapshot_out="$1"
	# Use ls basename-only output to match session_extract_copilot which also uses ls.
	ls "${HOME}/.copilot/session-state" 2>/dev/null | LC_ALL=C sort >"$snapshot_out" || true
}

# ── Extraction functions (call AFTER running the tool wrapper) ────────────────

# session_extract_codex <snapshot_file> <sid_out>
# confidence: medium (state_dir diff)
session_extract_codex() {
	local snapshot_file="$1" sid_out="$2"
	local sessions_dir="${HOME}/.codex/sessions"

	if [[ ! -d $sessions_dir ]]; then
		echo "none" >"$sid_out"
		return 1
	fi

	local after
	after=$(find "$sessions_dir" -name "*.jsonl" 2>/dev/null | LC_ALL=C sort)
	local before=""
	[[ -f $snapshot_file ]] && before=$(cat "$snapshot_file")

	# comm -13 requires both inputs sorted with the same locale.
	# Use process substitution with printf to avoid echo adding spurious empty lines.
	local new_entries
	new_entries=$(comm -13 \
		<(printf '%s\n' "$before" | LC_ALL=C sort | grep .) \
		<(printf '%s\n' "$after" | LC_ALL=C sort | grep .) \
		2>/dev/null | head -2 || true)
	local count
	count=$(printf '%s\n' "$new_entries" | grep -c . || true)

	if [[ $count -eq 0 ]]; then
		log_warn "session_extract_codex: no new sessions found"
		echo "none" >"$sid_out"
		return 1
	fi

	if [[ $count -gt 1 ]]; then
		log_warn "session_extract_codex: ambiguous — ${count} new sessions found; cannot reliably identify"
		echo "none" >"$sid_out"
		return 1
	fi

	# Extract UUID from rollout filename: rollout-DATETIME-UUID.jsonl
	local rollout_path
	rollout_path=$(echo "$new_entries" | head -1)
	local sid
	sid=$(basename "$rollout_path" .jsonl | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | tail -1)
	if [[ -z $sid ]]; then
		log_warn "session_extract_codex: cannot parse session UUID from: ${rollout_path}"
		echo "none" >"$sid_out"
		return 1
	fi
	echo "$sid" >"$sid_out"
	return 0
}

# session_extract_copilot <snapshot_file> <sid_out>
# confidence: medium (state_dir diff)
session_extract_copilot() {
	local snapshot_file="$1" sid_out="$2"
	local sessions_dir="${HOME}/.copilot/session-state"

	if [[ ! -d $sessions_dir ]]; then
		echo "none" >"$sid_out"
		return 1
	fi

	local after
	after=$(ls "$sessions_dir" 2>/dev/null | LC_ALL=C sort)
	local before=""
	[[ -f $snapshot_file ]] && before=$(cat "$snapshot_file")

	local new_entries
	new_entries=$(comm -13 \
		<(printf '%s\n' "$before" | LC_ALL=C sort | grep .) \
		<(printf '%s\n' "$after" | LC_ALL=C sort | grep .) \
		2>/dev/null | head -2 || true)
	local count
	count=$(printf '%s\n' "$new_entries" | grep -c . || true)

	if [[ $count -eq 0 ]]; then
		log_warn "session_extract_copilot: no new sessions found"
		echo "none" >"$sid_out"
		return 1
	fi

	if [[ $count -gt 1 ]]; then
		log_warn "session_extract_copilot: ambiguous — ${count} new sessions found; cannot reliably identify"
		echo "none" >"$sid_out"
		return 1
	fi

	local sid
	sid=$(echo "$new_entries" | head -1)
	echo "$sid" >"$sid_out"
	return 0
}

# session_extract_gemini <raw_log> <sid_out>
# confidence: high (stream-json init event)
#
# NOTE: Gemini stream-json uses "type": "init" (with space after colon).
#       grep '"type":"init"' does NOT match. Use python3 JSON parsing.
session_extract_gemini() {
	local raw_log="$1" sid_out="$2"
	local sid
	sid=$(
		python3 - "$raw_log" <<'PYEOF'
import json, sys

path = sys.argv[1]
try:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "init" and "session_id" in obj:
                    print(obj["session_id"])
                    break
            except json.JSONDecodeError:
                pass
except FileNotFoundError:
    pass
PYEOF
	)

	if [[ -z $sid ]]; then
		log_warn "session_extract_gemini: no session_id found in init event: ${raw_log}"
		echo "none" >"$sid_out"
		return 1
	fi
	echo "$sid" >"$sid_out"
	return 0
}

# session_extract_codex_from_jsonl <jsonl_stdout> <sid_out>
# confidence: high (thread.started event in --json stdout output)
# Use this for codex exec --json or codex exec resume --json runs.
session_extract_codex_from_jsonl() {
	local jsonl_file="$1" sid_out="$2"
	local sid
	sid=$(
		python3 - "$jsonl_file" <<'PYEOF'
import json, sys
jsonl_path = sys.argv[1]
result = ""
try:
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
                if evt.get("type") == "thread.started":
                    result = evt.get("thread_id", "")
                    break
            except json.JSONDecodeError:
                pass
except FileNotFoundError:
    pass
print(result)
PYEOF
	)
	if [[ -z $sid || $sid == "none" ]]; then
		log_warn "session_extract_codex_from_jsonl: no thread_id in thread.started event: ${jsonl_file}"
		echo "none" >"$sid_out"
		return 1
	fi
	echo "$sid" >"$sid_out"
	return 0
}

# session_extract_for_tool <tool> <arg1> <sid_out>
# Dispatches to the appropriate extraction function.
# Codex/Copilot: arg1 = snapshot_file
# Gemini: arg1 = raw_log
session_extract_for_tool() {
	local tool="$1"
	shift
	case "$tool" in
	codex) session_extract_codex "$@" ;;
	copilot) session_extract_copilot "$@" ;;
	gemini) session_extract_gemini "$@" ;;
	*)
		log_warn "session_extract_for_tool: unknown tool: ${tool}"
		return 1
		;;
	esac
}
