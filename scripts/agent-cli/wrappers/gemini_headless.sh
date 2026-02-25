#!/usr/bin/env bash
# gemini_headless.sh — Headless Gemini CLI wrapper
#
# Usage:
#   gemini_headless.sh --prompt-file <path> --out <path> --err <path> \
#     [--model auto|pro|flash|flash-lite] \
#     [--sandbox] \
#     [--approval-mode default|auto_edit|yolo] \
#     [--timeout-ms <ms>] \
#     [--timeout-mode enforce|wait_done] \
#     [--done-marker <path>] \
#     [--pid-file <path>]
#     [--resume-session <session-id>] \
#     [--session-id-out <path>]
#
# Exit codes (wrapper-defined):
#   0   Success
#   10  gemini binary not found
#   11  prompt-file not found
#   12  General gemini failure
#   13  Timeout
#   14  Input error (gemini exit 42)
#
# NOTE: Output format is stream-json internally; text is transparently extracted
# and written to OUT_FILE. Callers do not need to handle stream-json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
source "${LIB_DIR}/log.sh"
source "${LIB_DIR}/atomic.sh"
source "${LIB_DIR}/path_resolve.sh"

# Defaults
PROMPT_FILE=""
OUT_FILE=""
ERR_FILE=""
MODEL="pro"
USE_SANDBOX=false
APPROVAL_MODE="default"
TIMEOUT_MS=300000
TIMEOUT_MODE="wait_done"
DONE_MARKER=""
PID_FILE=""
RESUME_SESSION=""
SESSION_ID_OUT=""

# Parse arguments
while [[ $# -gt 0 ]]; do
	case "$1" in
	--prompt-file)
		PROMPT_FILE="$2"
		shift 2
		;;
	--out)
		OUT_FILE="$2"
		shift 2
		;;
	--err)
		ERR_FILE="$2"
		shift 2
		;;
	--model)
		MODEL="$2"
		shift 2
		;;
	--sandbox)
		USE_SANDBOX=true
		shift
		;;
	--approval-mode)
		APPROVAL_MODE="$2"
		shift 2
		;;
	--timeout-ms)
		TIMEOUT_MS="$2"
		shift 2
		;;
	--timeout-mode)
		TIMEOUT_MODE="$2"
		shift 2
		;;
	--done-marker)
		DONE_MARKER="$2"
		shift 2
		;;
	--pid-file)
		PID_FILE="$2"
		shift 2
		;;
	--resume-session)
		RESUME_SESSION="$2"
		shift 2
		;;
	--session-id-out)
		SESSION_ID_OUT="$2"
		shift 2
		;;
	*)
		log_warn "Unknown argument: $1"
		shift
		;;
	esac
done

finish_exit() {
	local code="$1"
	if [[ -n $PID_FILE && $code -eq 0 ]]; then
		rm -f "$PID_FILE"
	fi
	exit "$code"
}

# Validate
resolve_tool_or_die gemini 10 || finish_exit 10
if [[ -z $PROMPT_FILE || ! -f $PROMPT_FILE ]]; then
	log_error "prompt-file not found: ${PROMPT_FILE:-<unset>}"
	finish_exit 11
fi
if [[ -z $OUT_FILE || -z $ERR_FILE ]]; then
	log_error "--out and --err are required"
	finish_exit 11
fi
if [[ ! $TIMEOUT_MS =~ ^[0-9]+$ ]]; then
	log_error "--timeout-ms must be a non-negative integer (got: ${TIMEOUT_MS})"
	finish_exit 11
fi
if [[ $TIMEOUT_MODE != "enforce" && $TIMEOUT_MODE != "wait_done" ]]; then
	log_error "--timeout-mode must be enforce|wait_done (got: ${TIMEOUT_MODE})"
	finish_exit 11
fi

ensure_dir "$OUT_FILE"
ensure_dir "$ERR_FILE"
if [[ -n $PID_FILE ]]; then
	ensure_dir "$PID_FILE"
	printf '%s\n' "$$" >"$PID_FILE"
fi

TIMEOUT_SEC=$((TIMEOUT_MS / 1000))

# Build gemini command arguments
# Always use stream-json for session_id extraction; text is transparently reconstructed.
GEMINI_ARGS=(
	"--model" "$MODEL"
	"--output-format" "stream-json"
	"--approval-mode" "$APPROVAL_MODE"
)
if [[ $USE_SANDBOX == "true" ]]; then
	GEMINI_ARGS+=("--sandbox")
fi
if [[ -n $RESUME_SESSION ]]; then
	GEMINI_ARGS+=("--resume" "$RESUME_SESSION")
fi

# Instruction to gemini: process content from stdin
# (stdin pipe avoids ARG_MAX limits for large prompts)
GEMINI_PROMPT="You are operating in headless mode. Process the content provided on stdin according to the role instructions embedded at the top of the input. Produce your response and exit."

OUT_PARTIAL="${OUT_FILE}.partial"
ERR_PARTIAL="${ERR_FILE}.partial"
RAW_OUT="${OUT_FILE}.raw"

if [[ $TIMEOUT_MODE == "wait_done" || $TIMEOUT_MS == "0" ]]; then
	log_info "gemini_headless: model=${MODEL} timeout=none mode=${TIMEOUT_MODE}${RESUME_SESSION:+ resume=${RESUME_SESSION}}"
else
	log_info "gemini_headless: model=${MODEL} timeout=${TIMEOUT_SEC}s mode=${TIMEOUT_MODE}${RESUME_SESSION:+ resume=${RESUME_SESSION}}"
fi

# Use perl for timeout (macOS doesn't ship GNU timeout by default)
# stream-json goes to stdout (RAW_OUT); stderr gets log lines only
if [[ $TIMEOUT_MODE == "enforce" && $TIMEOUT_MS != "0" ]]; then
	set +e
	perl -e "
    alarm(${TIMEOUT_SEC});
    \$SIG{ALRM} = sub { exit(124) };
    exec('gemini', @ARGV) or die \$!;
  " -- "${GEMINI_ARGS[@]}" "$GEMINI_PROMPT" \
		<"$PROMPT_FILE" \
		>"$RAW_OUT" \
		2>"$ERR_PARTIAL"
	GEMINI_EXIT=$?
	set -e
else
	set +e
	gemini "${GEMINI_ARGS[@]}" "$GEMINI_PROMPT" \
		<"$PROMPT_FILE" \
		>"$RAW_OUT" \
		2>"$ERR_PARTIAL"
	GEMINI_EXIT=$?
	set -e
fi

# Map exit codes
if [[ $GEMINI_EXIT -eq 124 ]]; then
	log_error "gemini_headless: TIMEOUT after ${TIMEOUT_SEC}s"
	[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
	[[ -f $RAW_OUT ]] && atomic_write "$RAW_OUT" "${OUT_FILE}.failed" || true
	finish_exit 13
fi

if [[ $GEMINI_EXIT -eq 42 ]]; then
	log_error "gemini_headless: Input error (exit 42)"
	[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
	finish_exit 14
fi

if [[ $GEMINI_EXIT -eq 53 ]]; then
	log_warn "gemini_headless: Turn limit exceeded (exit 53)"
	[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
	[[ -f $RAW_OUT ]] && atomic_write "$RAW_OUT" "${OUT_FILE}.failed" || true
	finish_exit 12
fi

if [[ $GEMINI_EXIT -ne 0 ]]; then
	log_error "gemini_headless: failed with exit ${GEMINI_EXIT}"
	[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
	[[ -f $RAW_OUT ]] && atomic_write "$RAW_OUT" "${OUT_FILE}.failed" || true
	finish_exit 12
fi

# Extract plain text from stream-json: concatenate all assistant message content
if [[ -f $RAW_OUT && -s $RAW_OUT ]]; then
	python3 - "$RAW_OUT" "$OUT_PARTIAL" <<'PYEOF'
import json, sys

raw_path, out_path = sys.argv[1], sys.argv[2]
parts = []
with open(raw_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "message" and evt.get("role") == "assistant":
            content = evt.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                # future-proof: handle list of content parts
                for part in content:
                    if isinstance(part, dict):
                        parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        parts.append(part)

with open(out_path, "w") as f:
    f.write("\n".join(parts))
    if parts:
        f.write("\n")
PYEOF
else
	log_error "gemini_headless: RAW_OUT missing or empty after successful exit"
	finish_exit 12
fi

# Extract session_id if requested
if [[ -n $SESSION_ID_OUT ]]; then
	source "${LIB_DIR}/session_extractor.sh"
	session_extract_gemini "$RAW_OUT" "$SESSION_ID_OUT" || true
fi

# Success: atomic rename
[[ -f $OUT_PARTIAL ]] && atomic_write "$OUT_PARTIAL" "$OUT_FILE"
[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || touch "$ERR_FILE"
# Keep RAW_OUT for debugging (session_id re-extraction if needed)

local_lines=$(wc -l <"$OUT_FILE" | tr -d ' ')
log_ok "gemini_headless: completed (${local_lines} lines output)"

if [[ -n $DONE_MARKER ]]; then
	write_done_marker "$DONE_MARKER"
fi

finish_exit 0
