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
GATE_RESULT_FILE=""

while [[ $# -gt 0 ]]; do
	case "$1" in
	--task)
		TASK_DIR="$2"
		shift 2
		;;
	--stage)
		STAGE_NAME="$2"
		shift 2
		;;
	--role)
		ROLE="$2"
		shift 2
		;;
	--gate-result-out)
		GATE_RESULT_FILE="$2"
		shift 2
		;;
	*)
		log_warn "Unknown argument: $1"
		shift
		;;
	esac
done

if [[ -z $TASK_DIR || -z $STAGE_NAME || -z $ROLE ]]; then
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

write_gate_result() {
	[[ -n ${GATE_RESULT_FILE-} ]] || return 0

	local passed_json
	passed_json="false"
	if [[ $GATE_FAILED -eq 0 ]]; then
		passed_json="true"
	fi

	local gate_result_partial="${GATE_RESULT_FILE}.partial"
	# Serialize FAILURE_REASONS to JSON before passing to python3 (bash 3.2 safe)
	local reasons_json="[]"
	if [[ ${#FAILURE_REASONS[@]} -gt 0 ]]; then
		reasons_json=$(printf '%s\n' "${FAILURE_REASONS[@]}" | python3 -c 'import json,sys; print(json.dumps([l.rstrip("\n") for l in sys.stdin]))')
	fi
	python3 - "$STAGE_NAME" "$ROLE" "$passed_json" "$gate_result_partial" "$reasons_json" <<'PYEOF'
import json
import sys
from datetime import datetime, timezone

stage = sys.argv[1]
role = sys.argv[2]
passed = sys.argv[3].strip().lower() == "true"
out_path = sys.argv[4]
try:
    reasons = json.loads(sys.argv[5])
except Exception:
    reasons = []

payload = {
    "stage": stage,
    "role": role,
    "passed": passed,
    "reasons": reasons,
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
PYEOF
	mv "$gate_result_partial" "$GATE_RESULT_FILE"
}

resolve_repo_root() {
	git -C "$TASK_DIR" rev-parse --show-toplevel 2>/dev/null ||
		git rev-parse --show-toplevel 2>/dev/null || true
}

git_apply_check_diff_file() {
	local diff_file="$1"
	local gate_label="$2"
	local repo_root
	repo_root=$(resolve_repo_root)
	if [[ -z $repo_root ]]; then return; fi

	local apply_err
	apply_err=$(LC_ALL=C git -C "$repo_root" apply --check "$diff_file" 2>&1) && return 0

	# Soft-pass: Codex sometimes writes files directly and outputs a diff
	# that cannot be re-applied because files already exist (or corrupt patch
	# due to missing newlines between hunks).  If every error line is one of
	# those two known benign classes AND every +++ file exists on disk, pass.
	local all_soft=1
	while IFS= read -r errline; do
		[[ -z $errline ]] && continue
		[[ $errline == *"already exists in working directory"* ]] && continue
		[[ $errline == *"corrupt patch"* ]] && continue
		all_soft=0
		break
	done <<<"$apply_err"

	if [[ $all_soft -eq 1 ]]; then
		local any_missing=0
		while IFS= read -r diffline; do
			# Match "+++ b/<path>" lines (avoid regex for bash 3.x compat)
			# Unified diff may append a tab + timestamp: "+++ b/path\t2026-..."
			case "$diffline" in
			"+++ b/"*)
				local fpath="${diffline#+++ b/}"
				# Strip trailing tab and anything after it (timestamp suffix)
				fpath="${fpath%%	*}"
				[[ $fpath == "/dev/null" ]] && continue
				[[ -f "${repo_root}/${fpath}" ]] || {
					any_missing=1
					break
				}
				;;
			esac
		done <"$diff_file"
		if [[ $any_missing -eq 0 ]]; then
			log_warn "${gate_label}: git apply --check soft-passed (Codex wrote files directly)"
			return 0
		fi
	fi

	fail "${gate_label}: 'git apply --check' failed — diff cannot be applied cleanly"
}

scope_check_from_diff_file() {
	local diff_file="$1"
	local gate_label="$2"
	[[ -f $MANIFEST ]] || return

	local changed_files
	changed_files=$(grep -E '^(\+\+\+|---) ' "$diff_file" |
		grep -v '/dev/null' |
		sed 's|^[+-][+-][+-] [ab]/||' |
		sort -u || true)

	local allow_list
	allow_list=$(manifest_get "$MANIFEST" "scope.allow" 2>/dev/null || true)

	local deny_list
	deny_list=$(manifest_get "$MANIFEST" "scope.deny" 2>/dev/null || true)

	while IFS= read -r changed_file; do
		[[ -z $changed_file ]] && continue
		changed_file="${changed_file#./}"

		if [[ -n $allow_list ]]; then
			local allowed=0
			while IFS= read -r allow_path; do
				[[ -z $allow_path ]] && continue
				allow_path="${allow_path#./}"
				allow_path="${allow_path%/}"
				if [[ $changed_file == "$allow_path" || $changed_file == "$allow_path/"* ]]; then
					allowed=1
					break
				fi
			done <<<"$allow_list"
			if [[ $allowed -eq 0 ]]; then
				fail "${gate_label}: Scope violation — file '${changed_file}' is outside scope.allow"
			fi
		fi

		while IFS= read -r deny_path; do
			[[ -z $deny_path ]] && continue
			deny_path="${deny_path#./}"
			deny_path="${deny_path%/}"
			if [[ $changed_file == "$deny_path" || $changed_file == "$deny_path/"* ]]; then
				fail "${gate_label}: Scope violation — file '${changed_file}' matches deny path '${deny_path}'"
			fi
		done <<<"$deny_list"
	done <<<"$changed_files"
}

task_root_dir() {
	local parent
	parent="$(cd "${TASK_DIR}/.." 2>/dev/null && pwd || true)"
	if [[ -n $parent && -d "${parent}/state" ]]; then
		echo "$parent"
	else
		echo "$TASK_DIR"
	fi
}

web_research_mode() {
	local root_dir
	root_dir="$(task_root_dir)"

	local candidates=(
		"${TASK_DIR}/routing_result.json"
		"${TASK_DIR}/state/routing-decision.review.json"
		"${TASK_DIR}/state/routing-decision.impl.json"
		"${TASK_DIR}/state/routing-decision.plan.json"
		"${root_dir}/state/routing-decision.review.json"
		"${root_dir}/state/routing-decision.impl.json"
		"${root_dir}/state/routing-decision.plan.json"
		"${root_dir}/review/routing_result.json"
		"${root_dir}/impl/routing_result.json"
	)

	local file mode
	for file in "${candidates[@]}"; do
		[[ -s $file ]] || continue
		mode="$(
			python3 - "$file" <<'PYEOF'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    policy = payload.get("web_research_policy")
    if isinstance(policy, dict):
        mode = policy.get("mode")
        if isinstance(mode, str) and mode.strip():
            print(mode.strip())
except Exception:
    pass
PYEOF
		)" || mode=""
		if [[ -n $mode ]]; then
			echo "$mode"
			return 0
		fi
	done

	echo "off"
}

find_web_evidence_file() {
	local root_dir
	root_dir="$(task_root_dir)"
	local candidates=(
		"${root_dir}/state/web-evidence.json"
		"${root_dir}/review/web-evidence.json"
	)

	local file
	for file in "${candidates[@]}"; do
		if [[ -f $file ]]; then
			echo "$file"
			return 0
		fi
	done
	return 1
}

gate_web_evidence() {
	local phase="$1"
	local step="$2"

	local web_evidence_file=""
	web_evidence_file="$(find_web_evidence_file || true)"
	[[ -n $web_evidence_file ]] || return 0

	local mode
	mode="$(web_research_mode)"
	if [[ $mode == "off" ]]; then
		return 0
	fi

	source "${SCRIPT_DIR}/lib/web_evidence.sh"

	local rc=0
	web_evidence_validate "$web_evidence_file" "$phase" "$step" || rc=$?
	local reason_codes
	reason_codes="$(web_evidence_reason_codes "$web_evidence_file" "$phase" "$step" 2>/dev/null || echo '[]')"
	local web_evidence_result_file="${OUTPUTS_DIR}/${STAGE_NAME}.web_evidence_result.json"
	local web_evidence_result_partial="${web_evidence_result_file}.partial"
	python3 - "$STAGE_NAME" "$web_evidence_file" "$mode" "$rc" "$reason_codes" "$web_evidence_result_partial" <<'PYEOF'
import json
import sys
from datetime import datetime, timezone

stage = sys.argv[1]
evidence_file = sys.argv[2]
mode = sys.argv[3]
result_code = int(sys.argv[4])
reason_codes_json = sys.argv[5]
out_path = sys.argv[6]

try:
    reason_codes = json.loads(reason_codes_json)
except Exception:
    reason_codes = []

if not isinstance(reason_codes, list):
    reason_codes = []

result_map = {
    0: "pass",
    1: "STOP_AND_CONFIRM",
    2: "reject",
}

payload = {
    "stage": stage,
    "evidence_file": evidence_file,
    "mode": mode,
    "result_code": result_code,
    "result": result_map.get(result_code, "reject"),
    "reason_codes": [str(code) for code in reason_codes],
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
PYEOF
	mv "$web_evidence_result_partial" "$web_evidence_result_file"

	if [[ $rc -eq 1 ]]; then
		fail "web_evidence: STOP_AND_CONFIRM — high-risk claim with insufficient evidence"
		return
	fi
	if [[ $rc -eq 2 ]]; then
		log_warn "web_evidence: rejected web claims (${reason_codes})"
	fi
}

# ── Common gate: required files must exist ────────────────────────────────────
if [[ ! -f $OUT_FILE ]]; then
	fail "Output file missing: ${OUT_FILE}"
fi
if [[ ! -f $META_FILE ]]; then
	fail "Meta JSON missing: ${META_FILE}"
fi
# err file is allowed to be empty/absent — don't fail on missing err

# ── Role-specific gates ───────────────────────────────────────────────────────

gate_brief() {
	[[ -f $OUT_FILE ]] || return
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
	# Gemini sometimes wraps '## N. Title' across two lines: '## N.\n Title'.
	# Normalize line-wrapped headings before checking.
	local normalized_out
	normalized_out=$(python3 -c "
import re, sys
text = open(sys.argv[1]).read()
# Collapse: '## N.\n  Continuation' -> '## N. Continuation'
text = re.sub(r'(##\s+\d+\.)\s*\n\s+', r'\1 ', text)
print(text)
" "${OUT_FILE}" 2>/dev/null || cat "${OUT_FILE}")

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
		if ! echo "${normalized_out}" | grep -qiF "${section}"; then
			fail "brief: Updated Context Pack missing required heading fragment: '${section}'"
		fi
	done

	gate_web_evidence "brief" "$STAGE_NAME"
}

gate_impl() {
	[[ -f $OUT_FILE ]] || return

	# Must contain unified diff markers
	if ! grep -qE '^(---|\+\+\+|@@)' "$OUT_FILE"; then
		fail "impl: Output does not appear to be a unified diff (missing ---, +++, or @@ markers)"
		return
	fi

	git_apply_check_diff_file "$OUT_FILE" "impl"
	scope_check_from_diff_file "$OUT_FILE" "impl"
}

# _validate_acceptance_cmd <cmd>
# Defense-in-depth blocklist for acceptance commands.
# Rejects the highest-risk patterns that should never appear in test/verify commands.
# The primary risk surface is acceptance.commands.override, which is extracted from
# LLM brief output and could contain adversarially-injected commands via a crafted goal.
# Note: this is not a complete security sandbox; it blocks known-dangerous patterns only.
_validate_acceptance_cmd() {
	local cmd="$1"

	# Reject privilege escalation (sudo / su)
	if echo "$cmd" | grep -qE '(^|[[:space:];|&])(sudo|su)[[:space:]]'; then
		log_warn "gate_verify: blocked privilege escalation in command: ${cmd}"
		return 1
	fi

	# Reject rm with the -r flag (recursive deletion).
	# Single-file rm -f is allowed; recursive rm has no legitimate role in
	# acceptance/verify commands and is the primary vector for mass-delete attacks.
	if echo "$cmd" | grep -qE '\brm\b[[:space:]].*-[[:alpha:]]*r'; then
		log_warn "gate_verify: blocked recursive rm command: ${cmd}"
		return 1
	fi

	# Reject dd writing directly to a device file (disk wipe / device overwrite)
	if echo "$cmd" | grep -qE '\bdd\b.*[[:space:]]of=/dev/'; then
		log_warn "gate_verify: blocked dd device-write command: ${cmd}"
		return 1
	fi

	# Reject filesystem formatting commands
	if echo "$cmd" | grep -qE '(^|[[:space:];|&])mkfs[[:space:].]'; then
		log_warn "gate_verify: blocked mkfs command: ${cmd}"
		return 1
	fi

	# Reject writes to system directories (/etc, /boot, /usr, /bin, /sbin)
	if echo "$cmd" | grep -qE '>[[:space:]]*(\/etc\/|\/boot\/|\/usr\/|\/bin\/|\/sbin\/)'; then
		log_warn "gate_verify: blocked write to system directory: ${cmd}"
		return 1
	fi

	# Reject download-and-execute patterns (curl/wget piped to sh/bash)
	if echo "$cmd" | grep -qE '\b(curl|wget)\b[^|]*\|[[:space:]]*(sudo[[:space:]]+)?(ba)?sh\b'; then
		log_warn "gate_verify: blocked download-and-execute pattern: ${cmd}"
		return 1
	fi

	return 0
}

gate_verify() {
	[[ -f $MANIFEST ]] || return

	local acceptance_commands
	local override_file="${TASK_DIR}/state/acceptance.commands.override"
	if [[ -f $override_file ]]; then
		acceptance_commands=$(cat "$override_file")
		log_info "gate_verify: using acceptance command override from brief stage"
	else
		acceptance_commands=$(manifest_get "$MANIFEST" "acceptance.commands" 2>/dev/null || true)
	fi

	if [[ -z $acceptance_commands ]]; then
		log_info "gate_verify: no acceptance.commands defined, skipping command execution"
		return
	fi

	local artifact_file="${OUTPUTS_DIR}/${STAGE_NAME}.artifact.md"
	{
		echo "# Verify Gate Results"
		echo "Stage: ${STAGE_NAME}"
		echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
		echo ""
	} >"$artifact_file"

	while IFS= read -r cmd; do
		[[ -z $cmd ]] && continue
		if ! _validate_acceptance_cmd "$cmd"; then
			fail "verify: Acceptance command rejected by safety validator: ${cmd}"
			continue
		fi
		echo "## Command: \`${cmd}\`" >>"$artifact_file"
		local cmd_exit=0
		local cmd_output
		cmd_output=$(bash -c -- "$cmd" 2>&1) || cmd_exit=$?
		echo '```' >>"$artifact_file"
		echo "$cmd_output" >>"$artifact_file"
		echo '```' >>"$artifact_file"
		echo "Exit code: ${cmd_exit}" >>"$artifact_file"
		echo "" >>"$artifact_file"
		if [[ $cmd_exit -ne 0 ]]; then
			fail "verify: Acceptance command failed (exit ${cmd_exit}): ${cmd}"
		fi
	done <<<"$acceptance_commands"
}

gate_review() {
	[[ -f $OUT_FILE ]] || return
	local required_sections=(
		"## Findings"
		"## Test gaps"
		"## Breaking changes"
		"## Minimal fix"
	)
	# Gemini sometimes wraps headings across two lines in two ways:
	#   '##\n Findings'    -> '## Findings'
	#   '## Test\n gaps'   -> '## Test gaps'
	# Normalize both patterns before checking.
	local normalized_review
	normalized_review=$(python3 -c "
import re, sys
text = open(sys.argv[1]).read()
# Pattern 1: '## \n Word' -> '## Word'
text = re.sub(r'(##\s*)\n[ \t]+', r'\1 ', text)
# Pattern 2: '## Word\n continuation' -> '## Word continuation'
text = re.sub(r'(##[^\n]+)\n[ \t]+([a-z][^\n]*)', r'\1 \2', text)
print(text)
" "${OUT_FILE}" 2>/dev/null || cat "${OUT_FILE}")
	for section in "${required_sections[@]}"; do
		if ! echo "${normalized_review}" | grep -qiF "$section"; then
			fail "review: Missing required section: '${section}'"
		fi
	done

	gate_web_evidence "review" "$STAGE_NAME"
}

gate_runbook() {
	[[ -f $OUT_FILE ]] || return
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
	[[ -f $OUT_FILE ]] || return
	# Just check the output is non-trivially long (at least 10 lines)
	local lines
	lines=$(wc -l <"$OUT_FILE" | tr -d ' ')
	if ((lines < 10)); then
		fail "test_design: Output too short (${lines} lines < 10 minimum)"
	fi
}

gate_static_verify() {
	[[ -f $OUT_FILE ]] || return
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
	[[ -f $OUT_FILE ]] || return

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
  ' "$OUT_FILE" >"$diff_tmp"

	if [[ ! -s $diff_tmp ]]; then
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
brief) gate_brief ;;
impl) gate_impl ;;
verify) gate_verify ;;
review) gate_review ;;
review_consolidate) gate_review ;;
runbook) gate_runbook ;;
test_design) gate_test_design ;;
static_verify) gate_static_verify ;;
test_impl) gate_test_impl ;;
*)
	log_warn "gate: Unknown role '${ROLE}', running common checks only"
	;;
esac

# ── Result ────────────────────────────────────────────────────────────────────
if [[ $GATE_FAILED -eq 0 ]]; then
	log_ok "Gate PASSED: ${STAGE_NAME} (${ROLE})"
	write_gate_result
	exit 0
else
	echo "GATE FAILED for stage '${STAGE_NAME}' (role: ${ROLE}):"
	for reason in "${FAILURE_REASONS[@]}"; do
		echo "  - ${reason}"
	done
	write_gate_result
	exit 1
fi
