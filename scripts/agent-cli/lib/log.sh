#!/usr/bin/env bash
# log.sh — Common logging utilities
# Usage: source this file

set -euo pipefail

# Color support detection
_LOG_COLOR=""
if [[ -t 2 ]]; then
  _LOG_COLOR="yes"
fi

_log() {
  local level="$1"
  local msg="$2"
  local ts
  ts=$(date -u +"%H:%M:%S")

  if [[ -n "$_LOG_COLOR" ]]; then
    case "$level" in
      INFO)  echo -e "\033[0;34m[${ts} INFO]\033[0m  $msg" >&2 ;;
      WARN)  echo -e "\033[0;33m[${ts} WARN]\033[0m  $msg" >&2 ;;
      ERROR) echo -e "\033[0;31m[${ts} ERROR]\033[0m $msg" >&2 ;;
      OK)    echo -e "\033[0;32m[${ts} OK]\033[0m    $msg" >&2 ;;
    esac
  else
    echo "[${ts} ${level}] $msg" >&2
  fi
}

log_info()  { _log "INFO"  "$*"; }
log_warn()  { _log "WARN"  "$*"; }
log_error() { _log "ERROR" "$*"; }
log_ok()    { _log "OK"    "$*"; }

# trim_log <file> <head_lines> <tail_lines>
# Outputs the head and tail of a file with a separator, to stdout.
trim_log() {
  local file="$1"
  local head_lines="${2:-20}"
  local tail_lines="${3:-20}"

  if [[ ! -f "$file" || ! -s "$file" ]]; then
    return 0
  fi

  local total_lines
  total_lines=$(wc -l < "$file" | tr -d ' ')

  if (( total_lines <= head_lines + tail_lines )); then
    cat "$file"
  else
    head -n "$head_lines" "$file"
    echo "... [$(( total_lines - head_lines - tail_lines )) lines omitted] ..."
    tail -n "$tail_lines" "$file"
  fi
}

# sha256_file <path> — outputs the SHA256 hex digest of a file
sha256_file() {
  local file="$1"
  if command -v sha256sum &>/dev/null; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum &>/dev/null; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$file"
  fi
}

# epoch_now — current Unix timestamp
epoch_now() {
  date +%s
}
