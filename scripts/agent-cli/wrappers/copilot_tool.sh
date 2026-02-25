#!/usr/bin/env bash
# copilot_tool.sh — GitHub Copilot CLI wrapper (non-interactive mode)
#
# Usage:
#   copilot_tool.sh --prompt-file <path> --out <path> --err <path> \
#     [--model <model>] \
#     [--timeout-ms <ms>] \
#     [--timeout-mode enforce|wait_done] \
#     [--done-marker <path>] \
#     [--pid-file <path>]
#
# Exit codes (wrapper-defined):
#   0   Success
#   30  copilot binary not found
#   31  prompt-file not found or too large (>50KB)
#   32  General copilot failure
#   33  Timeout
#
# NOTE: Copilot -p flag embeds the entire prompt as a command-line argument.
# Prompts larger than 50KB may hit shell ARG_MAX limits and are rejected (exit 31).
# The dispatcher enforces digest_policy=aggressive for all Copilot invocations.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
source "${LIB_DIR}/log.sh"
source "${LIB_DIR}/atomic.sh"
source "${LIB_DIR}/path_resolve.sh"

MAX_PROMPT_BYTES=51200 # 50KB hard limit

PROMPT_FILE=""
OUT_FILE=""
ERR_FILE=""
MODEL="claude-sonnet-4.6"
TIMEOUT_MS=300000
TIMEOUT_MODE="wait_done"
DONE_MARKER=""
PID_FILE=""
RESUME_SESSION=""
SESSION_ID_OUT=""
SNAPSHOT_FILE=""
STAGE_ROLE=""

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
	--stage-role)
		STAGE_ROLE="$2"
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
resolve_tool_or_die copilot 30 || finish_exit 30
if [[ -z $PROMPT_FILE || ! -f $PROMPT_FILE ]]; then
	log_error "prompt-file not found: ${PROMPT_FILE:-<unset>}"
	finish_exit 31
fi
if [[ -z $OUT_FILE || -z $ERR_FILE ]]; then
	log_error "--out and --err are required"
	finish_exit 31
fi
if [[ ! $TIMEOUT_MS =~ ^[0-9]+$ ]]; then
	log_error "--timeout-ms must be a non-negative integer (got: ${TIMEOUT_MS})"
	finish_exit 31
fi
if [[ $TIMEOUT_MODE != "enforce" && $TIMEOUT_MODE != "wait_done" ]]; then
	log_error "--timeout-mode must be enforce|wait_done (got: ${TIMEOUT_MODE})"
	finish_exit 31
fi

# Size check — copilot embeds prompt in -p arg; enforce limit
PROMPT_SIZE=$(wc -c <"$PROMPT_FILE" | tr -d ' ')
if ((PROMPT_SIZE > MAX_PROMPT_BYTES)); then
	log_error "Prompt too large: ${PROMPT_SIZE} bytes > ${MAX_PROMPT_BYTES} byte limit"
	log_error "Use digest_policy=aggressive or reduce attachments"
	finish_exit 31
fi

ensure_dir "$OUT_FILE"
ensure_dir "$ERR_FILE"
if [[ -n $PID_FILE ]]; then
	ensure_dir "$PID_FILE"
	printf '%s\n' "$$" >"$PID_FILE"
fi

TIMEOUT_SEC=$((TIMEOUT_MS / 1000))

# Export prompt content so perl exec can read it from env
export _COPILOT_PROMPT
_COPILOT_PROMPT=$(cat "$PROMPT_FILE")
export _COPILOT_MODEL="$MODEL"
export _COPILOT_RESUME="$RESUME_SESSION"

OUT_PARTIAL="${OUT_FILE}.partial"
ERR_PARTIAL="${ERR_FILE}.partial"

if [[ $TIMEOUT_MODE == "wait_done" || $TIMEOUT_MS == "0" ]]; then
	log_info "copilot_tool: model=${MODEL} timeout=none mode=${TIMEOUT_MODE} size=${PROMPT_SIZE}B${RESUME_SESSION:+ resume=${RESUME_SESSION}}"
else
	log_info "copilot_tool: model=${MODEL} timeout=${TIMEOUT_SEC}s mode=${TIMEOUT_MODE} size=${PROMPT_SIZE}B${RESUME_SESSION:+ resume=${RESUME_SESSION}}"
fi

# ── Exception policy for Copilot fresh fallback ───────────────────────────────
# Called when resume is requested but probe indicates it's not supported.
# Returns 0 (allow fresh) for single-shot roles; 1 (fail-fast) otherwise.
copilot_fresh_exception_allowed() {
	local role="${1:-unknown}"
	case "$role" in
	review_consolidate | runbook) return 0 ;;
	*) return 1 ;;
	esac
}

# ── Resume vs fresh execution ─────────────────────────────────────────────────
_run_copilot_with_resume() {
	local use_resume="$1" # "true" or "false"
	if [[ $TIMEOUT_MODE == "enforce" && $TIMEOUT_MS != "0" ]]; then
		set +e
		if [[ $use_resume == "true" ]]; then
			perl -e "
        alarm(${TIMEOUT_SEC});
        \$SIG{ALRM} = sub { exit(124) };
        exec('copilot',
          '--resume', \$ENV{_COPILOT_RESUME},
          '-p', \$ENV{_COPILOT_PROMPT},
          '--silent',
          '--no-ask-user',
          '--allow-all-tools',
          '--model', \$ENV{_COPILOT_MODEL}
        ) or die \"exec failed: \$!\";
      " \
				>"$OUT_PARTIAL" \
				2>"$ERR_PARTIAL"
		else
			perl -e "
        alarm(${TIMEOUT_SEC});
        \$SIG{ALRM} = sub { exit(124) };
        exec('copilot',
          '-p', \$ENV{_COPILOT_PROMPT},
          '--silent',
          '--no-ask-user',
          '--allow-all-tools',
          '--model', \$ENV{_COPILOT_MODEL}
        ) or die \"exec failed: \$!\";
      " \
				>"$OUT_PARTIAL" \
				2>"$ERR_PARTIAL"
		fi
		COPILOT_EXIT=$?
		set -e
	else
		set +e
		if [[ $use_resume == "true" ]]; then
			copilot \
				--resume "$_COPILOT_RESUME" \
				-p "$_COPILOT_PROMPT" \
				--silent \
				--no-ask-user \
				--allow-all-tools \
				--model "$_COPILOT_MODEL" \
				>"$OUT_PARTIAL" \
				2>"$ERR_PARTIAL"
		else
			copilot \
				-p "$_COPILOT_PROMPT" \
				--silent \
				--no-ask-user \
				--allow-all-tools \
				--model "$_COPILOT_MODEL" \
				>"$OUT_PARTIAL" \
				2>"$ERR_PARTIAL"
		fi
		COPILOT_EXIT=$?
		set -e
	fi
}

if [[ -n $RESUME_SESSION ]]; then
	# Probe gate: only resume if capability confirmed
	source "${LIB_DIR}/session_probe.sh"
	_PROBE_TASK_ROOT="${TMPDIR:-/tmp}/copilot-probe-$$"
	mkdir -p "${_PROBE_TASK_ROOT}/state/session-probe"
	session_probe_copilot "$_PROBE_TASK_ROOT"
	PROBE_RESULT=$(session_probe_resume_supported "$_PROBE_TASK_ROOT" "copilot")
	rm -rf "$_PROBE_TASK_ROOT"

	if [[ $PROBE_RESULT == "true" ]]; then
		_run_copilot_with_resume "true"
	else
		# probe failed — check if fresh exception is allowed
		if copilot_fresh_exception_allowed "$STAGE_ROLE"; then
			log_warn "copilot_tool: resume not supported; fresh exception applied (role=${STAGE_ROLE:-unknown})"
			RESUME_SESSION=""
			_run_copilot_with_resume "false"
		else
			log_error "copilot_tool: resume required (RESUME_SESSION set) but not supported; fail-fast (role=${STAGE_ROLE:-unknown})"
			unset _COPILOT_PROMPT _COPILOT_MODEL _COPILOT_RESUME
			finish_exit 32
		fi
	fi
else
	_run_copilot_with_resume "false"
fi

# Unset exported vars
unset _COPILOT_PROMPT _COPILOT_MODEL _COPILOT_RESUME

# Map exit codes
if [[ $COPILOT_EXIT -eq 124 ]]; then
	log_error "copilot_tool: TIMEOUT after ${TIMEOUT_SEC}s"
	[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
	[[ -f $OUT_PARTIAL ]] && atomic_write "$OUT_PARTIAL" "$OUT_FILE" || true
	finish_exit 33
fi

if [[ $COPILOT_EXIT -ne 0 ]]; then
	log_error "copilot_tool: failed with exit ${COPILOT_EXIT}"
	[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
	[[ -f $OUT_PARTIAL ]] && atomic_write "$OUT_PARTIAL" "$OUT_FILE" || true
	finish_exit 32
fi

# Session ID extraction
# Resume mode: copilot reuses the existing session (no new session created)
# Fresh mode: detect new session via snapshot diff
if [[ -n $SESSION_ID_OUT ]]; then
	if [[ -n $RESUME_SESSION ]]; then
		echo "$RESUME_SESSION" >"$SESSION_ID_OUT"
	else
		source "${LIB_DIR}/session_extractor.sh"
		session_extract_copilot "$SNAPSHOT_FILE" "$SESSION_ID_OUT" || true
	fi
fi

# Success: atomic rename
[[ -f $OUT_PARTIAL ]] && atomic_write "$OUT_PARTIAL" "$OUT_FILE"
[[ -f $ERR_PARTIAL ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || touch "$ERR_FILE"

local_lines=$(wc -l <"$OUT_FILE" | tr -d ' ')
log_ok "copilot_tool: completed (${local_lines} lines output)"

if [[ -n $DONE_MARKER ]]; then
	write_done_marker "$DONE_MARKER"
fi

finish_exit 0
