#!/usr/bin/env bash
# triage_error.sh — Classify errors and update stats.json
#
# Usage:
#   triage_error.sh \
#     --exit-code <n> \
#     --stderr <path> \
#     --gate-result <pass|contract_violation|scope_violation|other_failure> \
#     --stats <path>
#
# Outputs JSON to stdout:
#   { "class": "...", "signature": "...", "exit_code": N, "suggested_actions": [...] }
#
# Also updates --stats file (stats.json) with the signature count.
#
# Error classes:
#   transient           Network/timing issue, retry once
#   prompt_too_large    Prompt exceeded model context or arg limit
#   auth                Authentication failure, stop immediately
#   tooling             Binary missing or environment issue
#   scope_violation     Gate detected out-of-scope changes
#   contract_violation  Gate detected output missing required structure
#   unknown             Unclassified

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/log.sh"

EXIT_CODE=0
STDERR_FILE=""
GATE_RESULT="pass"
STATS_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --exit-code)   EXIT_CODE="$2";   shift 2 ;;
    --stderr)      STDERR_FILE="$2"; shift 2 ;;
    --gate-result) GATE_RESULT="$2"; shift 2 ;;
    --stats)       STATS_FILE="$2";  shift 2 ;;
    *) log_warn "Unknown argument: $1"; shift ;;
  esac
done

# Read stderr content (limited to first 100 lines for pattern matching)
STDERR_CONTENT=""
if [[ -n "$STDERR_FILE" && -f "$STDERR_FILE" ]]; then
  STDERR_CONTENT=$(head -n 100 "$STDERR_FILE" 2>/dev/null || true)
fi

# ── Classify error ────────────────────────────────────────────────────────────

ERROR_CLASS="unknown"
SUGGESTED_ACTIONS=()

# Gate-based classification takes precedence
if [[ "$GATE_RESULT" == "scope_violation" ]]; then
  ERROR_CLASS="scope_violation"
  SUGGESTED_ACTIONS=("Review scope.allow/deny in manifest" "Split task into smaller scope" "Clarify scope with user")

elif [[ "$GATE_RESULT" == "contract_violation" ]]; then
  ERROR_CLASS="contract_violation"
  SUGGESTED_ACTIONS=("Review role prompt template" "Try alternate tool for this role" "Check gate requirements match prompt")

else
  # Exit-code-based classification
  case "$EXIT_CODE" in
    10|30)
      ERROR_CLASS="tooling"
      SUGGESTED_ACTIONS=("Run preflight.sh" "Verify CLI installations")
      ;;
    11|2)
      ERROR_CLASS="tooling"
      SUGGESTED_ACTIONS=("Check input file paths" "Run preflight.sh")
      ;;
    31)
      # File not found — could be tooling or prompt_too_large
      if echo "$STDERR_CONTENT" | grep -qiE "too large|size|50kb|limit"; then
        ERROR_CLASS="prompt_too_large"
        SUGGESTED_ACTIONS=("Enable digest_policy=aggressive in manifest" "Remove attachments" "Reduce context pack size")
      else
        ERROR_CLASS="tooling"
        SUGGESTED_ACTIONS=("Check input file paths" "Run preflight.sh")
      fi
      ;;
    13|33|124)
      # Timeout codes
      ERROR_CLASS="transient"
      SUGGESTED_ACTIONS=("Retry once" "Increase budgets.max_wallclock_sec in manifest" "Reduce prompt size")
      ;;
    14)
      # Gemini exit 42 mapped to 14 = input error
      ERROR_CLASS="prompt_too_large"
      SUGGESTED_ACTIONS=("Enable digest_policy=aggressive" "Reduce prompt size" "Remove attachments from compose")
      ;;
    *)
      # Pattern match on stderr content
      if echo "$STDERR_CONTENT" | grep -qiE "401|403|unauthorized|forbidden|invalid.*(token|key|credential)|authentication"; then
        ERROR_CLASS="auth"
        SUGGESTED_ACTIONS=("Re-authenticate CLI" "Check API key/token expiry" "No auto-retry — manual intervention required")
      elif echo "$STDERR_CONTENT" | grep -qiE "context.*(length|window)|too (large|long|many)|token.*(limit|exceed)|prompt.*too"; then
        ERROR_CLASS="prompt_too_large"
        SUGGESTED_ACTIONS=("Enable digest_policy=aggressive" "Trim attachments" "Split task into smaller pieces")
      elif echo "$STDERR_CONTENT" | grep -qiE "connection|network|timeout|socket|refused|ECONNRESET|ETIMEDOUT"; then
        ERROR_CLASS="transient"
        SUGGESTED_ACTIONS=("Retry once" "Check network connectivity")
      elif echo "$STDERR_CONTENT" | grep -qiE "not found|command not found|No such file|binary|executable|ENOENT"; then
        ERROR_CLASS="tooling"
        SUGGESTED_ACTIONS=("Run preflight.sh" "Verify PATH includes CLI tools")
      elif [[ "$EXIT_CODE" -ne 0 ]]; then
        # Generic non-zero: assume transient on first occurrence
        ERROR_CLASS="transient"
        SUGGESTED_ACTIONS=("Retry once (first occurrence of this error)" "Check stderr for details")
      fi
      ;;
  esac
fi

# ── Compute normalized signature ──────────────────────────────────────────────
# Normalize stderr by removing timestamps, task IDs, file paths, and specific tokens
NORMALIZED_STDERR=$(echo "$STDERR_CONTENT" | python3 -c "
import sys, re, hashlib

content = sys.stdin.read()

# Remove timestamps (ISO8601, Unix timestamps, time patterns)
content = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', 'TIMESTAMP', content)
content = re.sub(r'\b\d{10,13}\b', 'EPOCH', content)

# Remove task IDs (UUIDs and date-based IDs)
content = re.sub(r'\b[0-9]{8}-[0-9]{3,}\b', 'TASK_ID', content)
content = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UUID', content)

# Remove .tmp/ task paths
content = re.sub(r'\.tmp/task/[^\s/]+', '.tmp/task/TASK', content)

# Remove specific tokens/keys
content = re.sub(r'(sk-|ghp_|Bearer )[a-zA-Z0-9._\-]{10,}', 'REDACTED_TOKEN', content)

# Take first 500 chars for signature stability
normalized = content[:500].strip()
sig = hashlib.sha256(normalized.encode()).hexdigest()[:16]
print(f'sig:{sig}')
" 2>/dev/null || echo "sig:unknown")

SIGNATURE="${ERROR_CLASS}:${NORMALIZED_STDERR}"

# ── Build suggested_actions JSON array ────────────────────────────────────────
ACTIONS_JSON="["
first=true
for action in "${SUGGESTED_ACTIONS[@]}"; do
  if [[ "$first" == "true" ]]; then
    first=false
  else
    ACTIONS_JSON+=","
  fi
  ACTIONS_JSON+="\"$(echo "$action" | sed 's/"/\\"/g')\""
done
ACTIONS_JSON+="]"

# ── Output JSON to stdout ─────────────────────────────────────────────────────
python3 - <<PYEOF
import json, sys

result = {
    "class": "${ERROR_CLASS}",
    "signature": "${NORMALIZED_STDERR}",
    "exit_code": ${EXIT_CODE},
    "gate_result": "${GATE_RESULT}",
    "suggested_actions": ${ACTIONS_JSON}
}
print(json.dumps(result, indent=2))
PYEOF

# ── Update stats.json ─────────────────────────────────────────────────────────
if [[ -n "$STATS_FILE" ]]; then
  python3 - "$STATS_FILE" "$NORMALIZED_STDERR" "$ERROR_CLASS" <<'PYEOF'
import json, sys, os
from datetime import datetime, timezone

stats_file = sys.argv[1]
signature = sys.argv[2]
error_class = sys.argv[3]
now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

# Load existing stats
if os.path.isfile(stats_file):
    with open(stats_file) as f:
        try:
            stats = json.load(f)
        except Exception:
            stats = {}
else:
    stats = {}

# Ensure required structure
if 'paid_calls_used' not in stats:
    stats['paid_calls_used'] = 0
if 'stages_completed' not in stats:
    stats['stages_completed'] = []
if 'signatures' not in stats:
    stats['signatures'] = {}

# Update signature count
if signature not in stats['signatures']:
    stats['signatures'][signature] = {'count': 0, 'class': error_class, 'first_seen': now}
stats['signatures'][signature]['count'] += 1
stats['signatures'][signature]['last_seen'] = now
stats['signatures'][signature]['class'] = error_class

# Write atomically
os.makedirs(os.path.dirname(os.path.abspath(stats_file)), exist_ok=True)
partial = stats_file + '.partial'
with open(partial, 'w') as f:
    json.dump(stats, f, indent=2)
os.replace(partial, stats_file)
PYEOF
  log_info "triage: stats.json updated (class=${ERROR_CLASS})"
fi

exit 0
