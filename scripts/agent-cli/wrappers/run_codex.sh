#!/usr/bin/env bash
# run_codex.sh — OpenAI Codex CLI wrapper (non-interactive mode)
#
# Usage:
#   run_codex.sh --prompt-file <path> --out <path> --err <path> \
#     [--model <model>] \
#     [--effort low|medium|high|xhigh] \
#     [--timeout-ms <ms>] \
#     [--timeout-mode enforce|wait_done] \
#     [--done-marker <path>] \
#     [--pid-file <path>]
#
# Exit codes (wrapper-defined):
#   0    Success
#   2    prompt-file not found
#   12   General codex failure
#   13   codex binary not found (mapped from tooling error)
#   124  Timeout (perl alarm exit code)
#
# Uses codex exec --output-last-message to capture final response directly.
# stdin pipe is used for prompt input (avoids ARG_MAX for large inputs).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
source "${LIB_DIR}/log.sh"
source "${LIB_DIR}/atomic.sh"
source "${LIB_DIR}/path_resolve.sh"

PROMPT_FILE=""
OUT_FILE=""
ERR_FILE=""
MODEL="gpt-5.3-codex"
EFFORT="high"
TIMEOUT_MS=600000
TIMEOUT_MODE="wait_done"
DONE_MARKER=""
PID_FILE=""
RESUME_SESSION=""
SESSION_ID_OUT=""
SNAPSHOT_FILE=""

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
	--effort)
		EFFORT="$2"
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
	--snapshot-file)
		SNAPSHOT_FILE="$2"
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
resolve_tool_or_die codex 13 || finish_exit 13
if [[ -z $PROMPT_FILE || ! -f $PROMPT_FILE ]]; then
	log_error "prompt-file not found: ${PROMPT_FILE:-<unset>}"
	finish_exit 2
fi
if [[ -z $OUT_FILE || -z $ERR_FILE ]]; then
	log_error "--out and --err are required"
	finish_exit 2
fi
if [[ ! $TIMEOUT_MS =~ ^[0-9]+$ ]]; then
	log_error "--timeout-ms must be a non-negative integer (got: ${TIMEOUT_MS})"
	finish_exit 2
fi
if [[ $TIMEOUT_MODE != "enforce" && $TIMEOUT_MODE != "wait_done" ]]; then
	log_error "--timeout-mode must be enforce|wait_done (got: ${TIMEOUT_MODE})"
	finish_exit 2
fi

ensure_dir "$OUT_FILE"
ensure_dir "$ERR_FILE"
if [[ -n $PID_FILE ]]; then
	ensure_dir "$PID_FILE"
	printf '%s\n' "$$" >"$PID_FILE"
fi

TIMEOUT_SEC=$((TIMEOUT_MS / 1000))

OUT_PARTIAL="${OUT_FILE}.partial"
ERR_PARTIAL="${ERR_FILE}.partial"

if [[ $TIMEOUT_MODE == "wait_done" || $TIMEOUT_MS == "0" ]]; then
	log_info "run_codex: model=${MODEL} effort=${EFFORT} timeout=none mode=${TIMEOUT_MODE}${RESUME_SESSION:+ resume=${RESUME_SESSION}}"
else
	log_info "run_codex: model=${MODEL} effort=${EFFORT} timeout=${TIMEOUT_SEC}s mode=${TIMEOUT_MODE}${RESUME_SESSION:+ resume=${RESUME_SESSION}}"
fi

JSONL_RAW="${OUT_FILE}.jsonl"

if [[ -n $RESUME_SESSION ]]; then
	# Resume mode: codex exec resume does NOT support --output-last-message.
	# Use --json to capture JSONL events, then extract the last assistant message.
	if [[ $TIMEOUT_MODE == "enforce" && $TIMEOUT_MS != "0" ]]; then
		export _CODEX_RESUME="$RESUME_SESSION"
		export _CODEX_MODEL="$MODEL"
		export _CODEX_EFFORT="$EFFORT"
		export _CODEX_PROMPT_FILE="$PROMPT_FILE"
		set +e
		perl -e "
      alarm(${TIMEOUT_SEC});
      \$SIG{ALRM} = sub { exit(124) };
      open(STDIN, '<', \$ENV{_CODEX_PROMPT_FILE}) or die \"Cannot open prompt: \$!\";
      exec('codex', 'exec', 'resume', \$ENV{_CODEX_RESUME},
        '--model', \$ENV{_CODEX_MODEL},
        '-c', 'model_reasoning_effort=' . \$ENV{_CODEX_EFFORT},
        '--json',
        '--full-auto',
        '-'
      ) or die \"exec failed: \$!\";
    " \
			>"$JSONL_RAW" \
			2>"$ERR_PARTIAL"
		CODEX_EXIT=$?
		set -e
		unset _CODEX_RESUME _CODEX_MODEL _CODEX_EFFORT _CODEX_PROMPT_FILE
	else
		set +e
		codex exec resume "$RESUME_SESSION" \
			--model "$MODEL" \
			-c "model_reasoning_effort=${EFFORT}" \
			--json \
			--full-auto \
			- \
			<"$PROMPT_FILE" \
			>"$JSONL_RAW" \
			2>"$ERR_PARTIAL"
		CODEX_EXIT=$?
		set -e
	fi

	if [[ $CODEX_EXIT -eq 124 ]]; then
		log_error "run_codex: TIMEOUT after ${TIMEOUT_SEC}s (resume mode)"
		[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
		[[ -f $JSONL_RAW ]] && mv "$JSONL_RAW" "${OUT_FILE}.failed.jsonl" || true
		finish_exit 124
	fi

	if [[ $CODEX_EXIT -ne 0 ]]; then
		log_error "run_codex: failed with exit ${CODEX_EXIT} (resume mode)"
		[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
		[[ -f $JSONL_RAW ]] && mv "$JSONL_RAW" "${OUT_FILE}.failed.jsonl" || true
		finish_exit 12
	fi

	# Extract last assistant message from JSONL events
	python3 - "$JSONL_RAW" "$OUT_PARTIAL" <<'PYEOF'
import json, sys

jsonl_path, out_path = sys.argv[1], sys.argv[2]
last_parts = []

with open(jsonl_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Format A (codex exec resume --json): item.completed with agent_message
        if evt.get("type") == "item.completed":
            item = evt.get("item", {})
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text", "")
                if text:
                    last_parts = [text]
            continue
        # Format B (older/alternative): payload-wrapped or direct message events
        payload = evt.get("payload", evt)
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            content = payload.get("content", [])
            parts = []
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        parts.append(part.get("text", part.get("output_text", "")))
                    elif isinstance(part, str):
                        parts.append(part)
            if parts:
                last_parts = parts

with open(out_path, "w") as f:
    f.write("".join(last_parts))
    if last_parts:
        f.write("\n")
PYEOF

else
	# Fresh mode: use --output-last-message for direct output capture
	if [[ $TIMEOUT_MODE == "enforce" && $TIMEOUT_MS != "0" ]]; then
		export _CODEX_PROMPT_FILE="$PROMPT_FILE"
		export _CODEX_MODEL="$MODEL"
		export _CODEX_EFFORT="$EFFORT"
		export _CODEX_OUT_PARTIAL="$OUT_PARTIAL"
		set +e
		perl -e "
      alarm(${TIMEOUT_SEC});
      \$SIG{ALRM} = sub { exit(124) };
      open(STDIN, '<', \$ENV{_CODEX_PROMPT_FILE}) or die \"Cannot open prompt: \$!\";
      exec('codex', 'exec',
        '--model', \$ENV{_CODEX_MODEL},
        '-c', 'model_reasoning_effort=' . \$ENV{_CODEX_EFFORT},
        '--output-last-message', \$ENV{_CODEX_OUT_PARTIAL},
        '--full-auto',
        '--sandbox', 'workspace-write'
      ) or die \"exec failed: \$!\";
    " \
			2>"$ERR_PARTIAL"
		CODEX_EXIT=$?
		set -e
		unset _CODEX_PROMPT_FILE _CODEX_MODEL _CODEX_EFFORT _CODEX_OUT_PARTIAL
	else
		set +e
		codex exec \
			--model "$MODEL" \
			-c "model_reasoning_effort=${EFFORT}" \
			--output-last-message "$OUT_PARTIAL" \
			--full-auto \
			--sandbox workspace-write \
			<"$PROMPT_FILE" \
			2>"$ERR_PARTIAL"
		CODEX_EXIT=$?
		set -e
	fi

	if [[ $CODEX_EXIT -eq 124 ]]; then
		log_error "run_codex: TIMEOUT after ${TIMEOUT_SEC}s"
		[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
		[[ -f $OUT_PARTIAL ]] && mv "$OUT_PARTIAL" "${OUT_FILE}.failed" || true
		finish_exit 124
	fi

	if [[ $CODEX_EXIT -ne 0 ]]; then
		log_error "run_codex: failed with exit ${CODEX_EXIT}"
		[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
		[[ -f $OUT_PARTIAL ]] && mv "$OUT_PARTIAL" "${OUT_FILE}.failed" || true
		finish_exit 12
	fi

	# Verify output was written by --output-last-message
	if [[ ! -f $OUT_PARTIAL ]]; then
		log_error "run_codex: codex succeeded but output file not found: ${OUT_PARTIAL}"
		[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
		finish_exit 12
	fi
fi

# Session ID extraction (both modes)
if [[ -n $SESSION_ID_OUT ]]; then
	source "${LIB_DIR}/session_extractor.sh"
	# Resume mode: extract thread_id from --json stdout (high confidence)
	# Fresh mode: fall back to state_dir diff (medium confidence)
	if [[ -n $RESUME_SESSION && -f $JSONL_RAW ]]; then
		session_extract_codex_from_jsonl "$JSONL_RAW" "$SESSION_ID_OUT" ||
			session_extract_codex "$SNAPSHOT_FILE" "$SESSION_ID_OUT" || true
	else
		session_extract_codex "$SNAPSHOT_FILE" "$SESSION_ID_OUT" || true
	fi
fi

# Success: atomic rename
atomic_write "$OUT_PARTIAL" "$OUT_FILE"
[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || touch "$ERR_FILE"

local_lines=$(wc -l <"$OUT_FILE" | tr -d ' ')
log_ok "run_codex: completed (${local_lines} lines output)"

if [[ -n $DONE_MARKER ]]; then
	write_done_marker "$DONE_MARKER"
fi

finish_exit 0
