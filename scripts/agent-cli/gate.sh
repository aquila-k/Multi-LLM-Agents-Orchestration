#!/usr/bin/env bash
# gate.sh — Validate stage outputs against role contracts
#
# Usage:
#   gate.sh --task <task-dir> --stage <stage-name> --role <role>
#
# Roles: brief | impl | verify | review | runbook | test_design | static_verify | test_impl
#
# Exit codes:
#   0   Gate PASSED
#   1   Gate FAILED (contract violation or file missing)
#   2   Bad arguments
#
# On failure, writes a human-readable reason to stdout (for triage/summary).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/log.sh"
source "${SCRIPT_DIR}/lib/manifest.sh"

TASK_DIR=""
STAGE_NAME=""
ROLE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)  TASK_DIR="$2";   shift 2 ;;
    --stage) STAGE_NAME="$2"; shift 2 ;;
    --role)  ROLE="$2";       shift 2 ;;
    *) log_warn "Unknown argument: $1"; shift ;;
  esac
done

if [[ -z "$TASK_DIR" || -z "$STAGE_NAME" || -z "$ROLE" ]]; then
  echo "Usage: gate.sh --task <dir> --stage <name> --role <role>" >&2
  exit 2
fi

MANIFEST="${TASK_DIR}/manifest.yaml"
OUTPUTS_DIR="${TASK_DIR}/outputs"

# Derive tool from stage name (format: <tool>_<role> e.g. gemini_brief)
TOOL=$(echo "$STAGE_NAME" | cut -d_ -f1)
OUT_FILE="${OUTPUTS_DIR}/${STAGE_NAME}.${TOOL}.out"
ERR_FILE="${OUTPUTS_DIR}/${STAGE_NAME}.${TOOL}.err"
META_FILE="${OUTPUTS_DIR}/${STAGE_NAME}.${TOOL}.meta.json"

GATE_FAILED=0
FAILURE_REASONS=()

fail() {
  GATE_FAILED=1
  FAILURE_REASONS+=("$1")
  log_warn "GATE FAIL: $1"
}

resolve_repo_root() {
  git -C "$TASK_DIR" rev-parse --show-toplevel 2>/dev/null \
    || git rev-parse --show-toplevel 2>/dev/null || true
}

git_apply_check_diff_file() {
  local diff_file="$1"
  local gate_label="$2"
  local repo_root
  repo_root=$(resolve_repo_root)
  if [[ -n "$repo_root" ]]; then
    if ! git -C "$repo_root" apply --check "$diff_file" 2>/dev/null; then
      fail "${gate_label}: 'git apply --check' failed — diff cannot be applied cleanly"
    fi
  fi
}

scope_check_from_diff_file() {
  local diff_file="$1"
  local gate_label="$2"
  [[ -f "$MANIFEST" ]] || return

  local changed_files
  changed_files=$(grep -E '^(\+\+\+|---) ' "$diff_file" \
    | grep -v '/dev/null' \
    | sed 's|^[+-][+-][+-] [ab]/||' \
    | sort -u || true)

  local allow_list
  allow_list=$(manifest_get "$MANIFEST" "scope.allow" 2>/dev/null || true)

  local deny_list
  deny_list=$(manifest_get "$MANIFEST" "scope.deny" 2>/dev/null || true)

  while IFS= read -r changed_file; do
    [[ -z "$changed_file" ]] && continue
    changed_file="${changed_file#./}"

    if [[ -n "$allow_list" ]]; then
      local allowed=0
      while IFS= read -r allow_path; do
        [[ -z "$allow_path" ]] && continue
        allow_path="${allow_path#./}"
        allow_path="${allow_path%/}"
        if [[ "$changed_file" == "$allow_path" || "$changed_file" == "$allow_path/"* ]]; then
          allowed=1
          break
        fi
      done <<< "$allow_list"
      if [[ $allowed -eq 0 ]]; then
        fail "${gate_label}: Scope violation — file '${changed_file}' is outside scope.allow"
      fi
    fi

    while IFS= read -r deny_path; do
      [[ -z "$deny_path" ]] && continue
      deny_path="${deny_path#./}"
      deny_path="${deny_path%/}"
      if [[ "$changed_file" == "$deny_path" || "$changed_file" == "$deny_path/"* ]]; then
        fail "${gate_label}: Scope violation — file '${changed_file}' matches deny path '${deny_path}'"
      fi
    done <<< "$deny_list"
  done <<< "$changed_files"
}

# ── Common gate: required files must exist ────────────────────────────────────
if [[ ! -f "$OUT_FILE" ]]; then
  fail "Output file missing: ${OUT_FILE}"
fi
if [[ ! -f "$META_FILE" ]]; then
  fail "Meta JSON missing: ${META_FILE}"
fi
# err file is allowed to be empty/absent — don't fail on missing err

# ── Role-specific gates ───────────────────────────────────────────────────────

gate_brief() {
  [[ -f "$OUT_FILE" ]] || return
  local required_sections=(
    "## Summary"
    "## Acceptance"
    "## Scope"
    "## Constraints"
    "## Verify Commands"
    "## Updated Context Pack"
  )
  for section in "${required_sections[@]}"; do
    if ! grep -qF "$section" "$OUT_FILE"; then
      fail "brief: Missing required section: '${section}'"
    fi
  done

  # Updated Context Pack must preserve the canonical section structure.
  local required_context_sections=(
    "## 0. Goal"
    "## 1. Non-goals"
    "## 2. Scope"
    "## 3. Acceptance"
    "## 4. Fixed"
    "## 5. Files to Read"
    "## 6. Prohibited Actions"
    "## 7. Current State"
    "## 8. Open Questions"
    "## 9. Change History"
  )
  for section in "${required_context_sections[@]}"; do
    if ! grep -qiF "$section" "$OUT_FILE"; then
      fail "brief: Updated Context Pack missing required heading fragment: '${section}'"
    fi
  done
}

gate_impl() {
  [[ -f "$OUT_FILE" ]] || return

  # Must contain unified diff markers
  if ! grep -qE '^(---|\+\+\+|@@)' "$OUT_FILE"; then
    fail "impl: Output does not appear to be a unified diff (missing ---, +++, or @@ markers)"
    return
  fi

  git_apply_check_diff_file "$OUT_FILE" "impl"
  scope_check_from_diff_file "$OUT_FILE" "impl"
}

gate_verify() {
  [[ -f "$MANIFEST" ]] || return

  local acceptance_commands
  local override_file="${TASK_DIR}/state/acceptance.commands.override"
  if [[ -f "$override_file" ]]; then
    acceptance_commands=$(cat "$override_file")
    log_info "gate_verify: using acceptance command override from brief stage"
  else
    acceptance_commands=$(manifest_get "$MANIFEST" "acceptance.commands" 2>/dev/null || true)
  fi

  if [[ -z "$acceptance_commands" ]]; then
    log_info "gate_verify: no acceptance.commands defined, skipping command execution"
    return
  fi

  local artifact_file="${OUTPUTS_DIR}/${STAGE_NAME}.artifact.md"
  {
    echo "# Verify Gate Results"
    echo "Stage: ${STAGE_NAME}"
    echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo ""
  } > "$artifact_file"

  while IFS= read -r cmd; do
    [[ -z "$cmd" ]] && continue
    echo "## Command: \`${cmd}\`" >> "$artifact_file"
    local cmd_exit=0
    local cmd_output
    cmd_output=$(eval "$cmd" 2>&1) || cmd_exit=$?
    echo "\`\`\`" >> "$artifact_file"
    echo "$cmd_output" >> "$artifact_file"
    echo "\`\`\`" >> "$artifact_file"
    echo "Exit code: ${cmd_exit}" >> "$artifact_file"
    echo "" >> "$artifact_file"
    if [[ $cmd_exit -ne 0 ]]; then
      fail "verify: Acceptance command failed (exit ${cmd_exit}): ${cmd}"
    fi
  done <<< "$acceptance_commands"
}

gate_review() {
  [[ -f "$OUT_FILE" ]] || return
  local required_sections=(
    "## Findings"
    "## Test gaps"
    "## Breaking changes"
    "## Minimal fix"
  )
  for section in "${required_sections[@]}"; do
    if ! grep -qiF "$section" "$OUT_FILE"; then
      fail "review: Missing required section: '${section}'"
    fi
  done
}

gate_runbook() {
  [[ -f "$OUT_FILE" ]] || return
  local required_sections=(
    "## Problem"
    "## Plan"
    "## Commands"
    "## Risks"
  )
  for section in "${required_sections[@]}"; do
    if ! grep -qiF "$section" "$OUT_FILE"; then
      fail "runbook: Missing required section: '${section}'"
    fi
  done
}

gate_test_design() {
  [[ -f "$OUT_FILE" ]] || return
  # Just check the output is non-trivially long (at least 10 lines)
  local lines
  lines=$(wc -l < "$OUT_FILE" | tr -d ' ')
  if (( lines < 10 )); then
    fail "test_design: Output too short (${lines} lines < 10 minimum)"
  fi
}

gate_static_verify() {
  [[ -f "$OUT_FILE" ]] || return
  local required_sections=(
    "## Pre-execution checks"
    "## Dangerous changes"
    "## Rollback plan"
    "## Go/No-Go"
  )
  for section in "${required_sections[@]}"; do
    if ! grep -qiF "$section" "$OUT_FILE"; then
      fail "static_verify: Missing required section: '${section}'"
    fi
  done
}

gate_test_impl() {
  [[ -f "$OUT_FILE" ]] || return

  local required_sections=(
    "## Added or Updated Tests"
    "## Unified Diff"
    "## Rationale"
  )
  for section in "${required_sections[@]}"; do
    if ! grep -qiF "$section" "$OUT_FILE"; then
      fail "test_impl: Missing required section: '${section}'"
    fi
  done

  if grep -qiF "No changes required." "$OUT_FILE" || grep -qiF "No diff required." "$OUT_FILE"; then
    return
  fi

  local diff_tmp
  diff_tmp=$(mktemp)
  awk '
    BEGIN { in_diff=0 }
    /^```diff[[:space:]]*$/ { in_diff=1; next }
    /^```[[:space:]]*$/ {
      if (in_diff == 1) { exit }
    }
    {
      if (in_diff == 1) { print }
    }
  ' "$OUT_FILE" > "$diff_tmp"

  if [[ ! -s "$diff_tmp" ]]; then
    fail "test_impl: Missing diff code block under '## Unified Diff'"
    rm -f "$diff_tmp"
    return
  fi

  if ! grep -qE '^(---|\+\+\+|@@)' "$diff_tmp"; then
    fail "test_impl: Unified Diff block does not contain diff markers"
    rm -f "$diff_tmp"
    return
  fi

  git_apply_check_diff_file "$diff_tmp" "test_impl"
  scope_check_from_diff_file "$diff_tmp" "test_impl"
  rm -f "$diff_tmp"
}

# Dispatch to role-specific gate
case "$ROLE" in
  brief)       gate_brief ;;
  impl)        gate_impl ;;
  verify)      gate_verify ;;
  review)      gate_review ;;
  review_consolidate) gate_review ;;
  runbook)     gate_runbook ;;
  test_design) gate_test_design ;;
  static_verify) gate_static_verify ;;
  test_impl)   gate_test_impl ;;
  *)
    log_warn "gate: Unknown role '${ROLE}', running common checks only"
    ;;
esac

# ── Result ────────────────────────────────────────────────────────────────────
if [[ $GATE_FAILED -eq 0 ]]; then
  log_ok "Gate PASSED: ${STAGE_NAME} (${ROLE})"
  exit 0
else
  echo "GATE FAILED for stage '${STAGE_NAME}' (role: ${ROLE}):"
  for reason in "${FAILURE_REASONS[@]}"; do
    echo "  - ${reason}"
  done
  exit 1
fi
