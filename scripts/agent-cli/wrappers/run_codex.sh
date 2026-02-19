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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prompt-file) PROMPT_FILE="$2"; shift 2 ;;
    --out)         OUT_FILE="$2";    shift 2 ;;
    --err)         ERR_FILE="$2";    shift 2 ;;
    --model)       MODEL="$2";       shift 2 ;;
    --effort)      EFFORT="$2";      shift 2 ;;
    --timeout-ms)  TIMEOUT_MS="$2";  shift 2 ;;
    --timeout-mode) TIMEOUT_MODE="$2"; shift 2 ;;
    --done-marker) DONE_MARKER="$2"; shift 2 ;;
    --pid-file)    PID_FILE="$2";    shift 2 ;;
    *) log_warn "Unknown argument: $1"; shift ;;
  esac
done

finish_exit() {
  local code="$1"
  if [[ -n "$PID_FILE" && "$code" -eq 0 ]]; then
    rm -f "$PID_FILE"
  fi
  exit "$code"
}

# Validate
resolve_tool_or_die codex 13 || finish_exit 13
if [[ -z "$PROMPT_FILE" || ! -f "$PROMPT_FILE" ]]; then
  log_error "prompt-file not found: ${PROMPT_FILE:-<unset>}"
  finish_exit 2
fi
if [[ -z "$OUT_FILE" || -z "$ERR_FILE" ]]; then
  log_error "--out and --err are required"
  finish_exit 2
fi
if [[ ! "$TIMEOUT_MS" =~ ^[0-9]+$ ]]; then
  log_error "--timeout-ms must be a non-negative integer (got: ${TIMEOUT_MS})"
  finish_exit 2
fi
if [[ "$TIMEOUT_MODE" != "enforce" && "$TIMEOUT_MODE" != "wait_done" ]]; then
  log_error "--timeout-mode must be enforce|wait_done (got: ${TIMEOUT_MODE})"
  finish_exit 2
fi

ensure_dir "$OUT_FILE"
ensure_dir "$ERR_FILE"
if [[ -n "$PID_FILE" ]]; then
  ensure_dir "$PID_FILE"
  printf '%s\n' "$$" > "$PID_FILE"
fi

TIMEOUT_SEC=$(( TIMEOUT_MS / 1000 ))

OUT_PARTIAL="${OUT_FILE}.partial"
ERR_PARTIAL="${ERR_FILE}.partial"

if [[ "$TIMEOUT_MODE" == "wait_done" || "$TIMEOUT_MS" == "0" ]]; then
  log_info "run_codex: model=${MODEL} effort=${EFFORT} timeout=none mode=${TIMEOUT_MODE}"
else
  log_info "run_codex: model=${MODEL} effort=${EFFORT} timeout=${TIMEOUT_SEC}s mode=${TIMEOUT_MODE}"
fi

# Use --output-last-message to capture final response directly.
# stdin pipe feeds the full prompt without ARG_MAX concerns.
# --full-auto + --sandbox workspace-write for unattended, non-interactive use.
if [[ "$TIMEOUT_MODE" == "enforce" && "$TIMEOUT_MS" != "0" ]]; then
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
    2> "$ERR_PARTIAL"
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
    < "$PROMPT_FILE" \
    2> "$ERR_PARTIAL"
  CODEX_EXIT=$?
  set -e
fi

if [[ $CODEX_EXIT -eq 124 ]]; then
  log_error "run_codex: TIMEOUT after ${TIMEOUT_SEC}s"
  [[ -f "$ERR_PARTIAL" ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
  # Preserve partial output if it exists
  [[ -f "$OUT_PARTIAL" ]] && mv "$OUT_PARTIAL" "${OUT_FILE}.failed" || true
  finish_exit 124
fi

if [[ $CODEX_EXIT -ne 0 ]]; then
  log_error "run_codex: failed with exit ${CODEX_EXIT}"
  [[ -f "$ERR_PARTIAL" ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
  [[ -f "$OUT_PARTIAL" ]] && mv "$OUT_PARTIAL" "${OUT_FILE}.failed" || true
  finish_exit 12
fi

# Verify output was written by --output-last-message
if [[ ! -f "$OUT_PARTIAL" ]]; then
  log_error "run_codex: codex succeeded but output file not found: ${OUT_PARTIAL}"
  log_error "Saving failed output for inspection"
  [[ -f "$ERR_PARTIAL" ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || true
  finish_exit 12
fi

# Success: atomic rename
atomic_write "$OUT_PARTIAL" "$OUT_FILE"
[[ -f "$ERR_PARTIAL" ]] && atomic_write "$ERR_PARTIAL" "$ERR_FILE" || touch "$ERR_FILE"

local_lines=$(wc -l < "$OUT_FILE" | tr -d ' ')
log_ok "run_codex: completed (${local_lines} lines output)"

if [[ -n "$DONE_MARKER" ]]; then
  write_done_marker "$DONE_MARKER"
fi

finish_exit 0
