#!/usr/bin/env bash
# dispatch_review.sh — Review phase dispatcher
#
# Usage:
#   dispatch_review.sh --task-root <dir> --task-name <name> [options]
#   dispatch_review.sh --task-root <dir> --task-name <name> \
#     [--context-pack <file>] [--impl-report <file>] \
#     [--run-id <id>] [--phase-session-mode <mode>] \
#     [--review-rounds <N>] [--review-max-rounds <N>] \
#     [--parallel-review]
#
# Canonical output:
#   <task-root>/review/summary.md
#
# Input resolution (when not provided explicitly):
#   context-pack : <task-root>/impl/inputs/context_pack.md
#   impl-report  : <task-root>/impl/outputs/ (first non-empty of known candidates)
#
# Exit codes:
#   0  Success
#   1  Failure
#   2  Bad arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/log.sh"
source "${SCRIPT_DIR}/lib/task_paths.sh"
source "${SCRIPT_DIR}/lib/dispatch_core.sh"
source "${SCRIPT_DIR}/lib/review_parallel.sh"

TASK_ROOT=""
TASK_NAME=""
CONTEXT_PACK=""
IMPL_REPORT=""
RUN_ID="$(date -u +"%Y%m%d-%H%M%S")-review"
PHASE_SESSION_MODE="${DISPATCH_CORE_DEFAULT_PHASE_SESSION_MODE}"
REVIEW_START_ROUND=1
REVIEW_MAX_ROUNDS="${REVIEW_MAX_ROUNDS:-3}"
REVIEW_PROFILE="review_cross"
PARALLEL_REVIEW=false
SECURITY_REVIEW_MODE="${SECURITY_REVIEW_MODE-}"
SECURITY_FIX_MAX_ROUNDS="${SECURITY_FIX_MAX_ROUNDS:-3}"
PARALLEL_REVIEW_TIMEOUT_SEC="${REVIEW_PARALLEL_TIMEOUT_SEC:-900}"

while [[ $# -gt 0 ]]; do
	case "$1" in
	--task-root)
		TASK_ROOT="$2"
		shift 2
		;;
	--task-name)
		TASK_NAME="$2"
		shift 2
		;;
	--context-pack)
		CONTEXT_PACK="$2"
		shift 2
		;;
	--impl-report)
		IMPL_REPORT="$2"
		shift 2
		;;
	--run-id)
		RUN_ID="$2"
		shift 2
		;;
	--phase-session-mode)
		PHASE_SESSION_MODE="$2"
		shift 2
		;;
	--review-rounds)
		REVIEW_START_ROUND="$2"
		shift 2
		;;
	--review-max-rounds)
		REVIEW_MAX_ROUNDS="$2"
		shift 2
		;;
	--review-profile)
		REVIEW_PROFILE="$2"
		shift 2
		;;
	--parallel-review)
		PARALLEL_REVIEW=true
		shift
		;;
	--security-mode)
		SECURITY_REVIEW_MODE="$2"
		shift 2
		;;
	*)
		log_warn "Unknown argument: $1"
		shift
		;;
	esac
done

if [[ -z $TASK_ROOT || -z $TASK_NAME ]]; then
	log_error "--task-root and --task-name are required"
	exit 2
fi

is_positive_int() {
	local v="$1"
	[[ $v =~ ^[0-9]+$ ]] && ((v >= 1))
}

if ! is_positive_int "$REVIEW_START_ROUND"; then
	log_error "--review-rounds must be a positive integer (got: ${REVIEW_START_ROUND})"
	exit 2
fi
if ! is_positive_int "$REVIEW_MAX_ROUNDS"; then
	log_error "--review-max-rounds must be a positive integer (got: ${REVIEW_MAX_ROUNDS})"
	exit 2
fi
if ((REVIEW_START_ROUND > REVIEW_MAX_ROUNDS)); then
	log_error "--review-rounds (${REVIEW_START_ROUND}) cannot be greater than --review-max-rounds (${REVIEW_MAX_ROUNDS})"
	exit 2
fi
if [[ ! $PARALLEL_REVIEW_TIMEOUT_SEC =~ ^[0-9]+$ ]]; then
	log_error "REVIEW_PARALLEL_TIMEOUT_SEC must be a non-negative integer (got: ${PARALLEL_REVIEW_TIMEOUT_SEC})"
	exit 2
fi

# Initialize canonical directory structure
task_path_ensure "$TASK_NAME" "$(dirname "$TASK_ROOT")" >/dev/null
REVIEW_DIR="${TASK_ROOT}/review"
IMPL_DIR="${TASK_ROOT}/impl"

# Initialize session state
dispatch_core_init "$TASK_ROOT" "$TASK_NAME" "$RUN_ID" "review" \
	"$PHASE_SESSION_MODE" "false"

log_info "dispatch_review: review_profile=${REVIEW_PROFILE}"
log_info "dispatch_review: parallel_review=${PARALLEL_REVIEW}"

# Record review_profile.json
python3 - "${REVIEW_DIR}" "$REVIEW_PROFILE" "$RUN_ID" <<'PYEOF'
import datetime, json, os, sys
review_dir, profile, run_id = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(review_dir, exist_ok=True)
payload = {
  "review_profile": profile,
  "run_id":         run_id,
  "recorded_at":    datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
for fname in ("review_profile.json",):
    path    = os.path.join(review_dir, fname)
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(partial, path)
PYEOF

# Resolve context_pack
if [[ -z $CONTEXT_PACK ]]; then
	CONTEXT_PACK="${IMPL_DIR}/inputs/context_pack.md"
fi

# Resolve impl-report from known candidates
if [[ -z $IMPL_REPORT ]]; then
	local_candidates=(
		"${IMPL_DIR}/outputs/codex_impl.codex.out"
		"${IMPL_DIR}/outputs/copilot_runbook.copilot.out"
		"${IMPL_DIR}/outputs/codex_test_impl.codex.out"
		"${IMPL_DIR}/outputs/_summary.md"
	)
	for c in "${local_candidates[@]}"; do
		if [[ -s $c ]]; then
			IMPL_REPORT="$c"
			break
		fi
	done
fi

# Validate inputs
if [[ -z $CONTEXT_PACK || ! -s $CONTEXT_PACK ]]; then
	log_error "Context pack missing or empty: ${CONTEXT_PACK:-<unset>}"
	log_error "  Expected: ${IMPL_DIR}/inputs/context_pack.md"
	log_error "  Or provide: --context-pack <file>"
	exit 2
fi

if [[ -z $IMPL_REPORT || ! -s $IMPL_REPORT ]]; then
	log_error "Implementation report missing or empty: ${IMPL_REPORT:-<unset>}"
	log_error "  Expected one of:"
	log_error "    ${IMPL_DIR}/outputs/codex_impl.codex.out"
	log_error "    ${IMPL_DIR}/outputs/copilot_runbook.copilot.out"
	log_error "    ${IMPL_DIR}/outputs/_summary.md"
	log_error "  Or provide: --impl-report <file>"
	exit 2
fi

log_info "dispatch_review: task=${TASK_NAME} run=${RUN_ID}"
log_info "  context_pack: ${CONTEXT_PACK}"
log_info "  impl_report:  ${IMPL_REPORT}"
log_info "  review_dir:   ${REVIEW_DIR}"
log_info "  rounds:       start=${REVIEW_START_ROUND} max=${REVIEW_MAX_ROUNDS}"

fail_phase() {
	local message="$1"
	dispatch_core_record_phase_done "$TASK_ROOT" "$RUN_ID" "review" "failed"
	log_error "$message"
	exit 1
}

resolve_review_web_research_mode() {
	local candidates=(
		"${REVIEW_DIR}/routing_result.json"
		"${TASK_ROOT}/state/routing-decision.review.json"
		"${TASK_ROOT}/review/routing_result.json"
		"${TASK_ROOT}/impl/routing_result.json"
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

ensure_review_web_artifact_stubs() {
	local mode="$1"
	if [[ $mode == "off" ]]; then
		return 0
	fi

	mkdir -p "$REVIEW_DIR"

	local evidence_file="${REVIEW_DIR}/web-evidence.json"
	local state_evidence_file="${TASK_ROOT}/state/web-evidence.json"
	if [[ ! -f $evidence_file && ! -f $state_evidence_file ]]; then
		python3 - "$evidence_file" "$TASK_NAME" "$RUN_ID" <<'PYEOF'
import datetime
import json
import os
import sys

evidence_file, task_name, run_id = sys.argv[1], sys.argv[2], sys.argv[3]
payload = {
    "meta": {
        "task_name": task_name,
        "task_id": task_name,
        "run_id": run_id,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strictness": "strict",
        "scope": "plan_review_only",
    },
    "evidence": [],
}

os.makedirs(os.path.dirname(os.path.abspath(evidence_file)), exist_ok=True)
partial = evidence_file + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, evidence_file)
PYEOF
		log_info "dispatch_review: created stub ${evidence_file}"
	fi

	local research_file="${REVIEW_DIR}/web-research.md"
	if [[ ! -f $research_file ]]; then
		cat >"$research_file" <<'EOF'
# Web Research

## Scope

## Queries

## Findings

## Conflicts

## Adoption Decisions

## Open Risks
EOF
		log_info "dispatch_review: created stub ${research_file}"
	fi
}

resolve_security_review_mode() {
	# 1. Already set by CLI or env
	if [[ -n ${SECURITY_REVIEW_MODE-} ]]; then
		echo "$SECURITY_REVIEW_MODE"
		return 0
	fi

	# 2. Check routing_result.json
	local routing_candidates=(
		"${REVIEW_DIR}/routing_result.json"
		"${TASK_ROOT}/state/routing-decision.review.json"
		"${TASK_ROOT}/review/routing_result.json"
		"${TASK_ROOT}/impl/routing_result.json"
	)
	local _file _mode
	for _file in "${routing_candidates[@]}"; do
		[[ -s $_file ]] || continue
		_mode="$(
			python3 - "$_file" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        payload = json.load(f)
    mode = payload.get("security_review_mode")
    if isinstance(mode, str) and mode.strip():
        print(mode.strip())
except Exception:
    pass
PYEOF
		)" || _mode=""
		if [[ -n $_mode ]]; then
			echo "$_mode"
			return 0
		fi
	done

	# 2.5. Check resolved dispatch config options (set by pipeline profile e.g. strict_review)
	# ISSUE-010-related: security_mode flows from profile options → resolved JSON → here
	local dispatch_resolved="${TASK_ROOT}/state/config.dispatch.resolved.json"
	if [[ -s $dispatch_resolved ]]; then
		_mode="$(
			python3 - "$dispatch_resolved" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        d = json.load(f)
    mode = (d.get("options") or {}).get("security_mode", "")
    if isinstance(mode, str) and mode.strip():
        print(mode.strip())
except Exception:
    pass
PYEOF
		)" || _mode=""
		if [[ -n $_mode ]]; then
			echo "$_mode"
			return 0
		fi
	fi

	# 3. Check manifest
	local impl_manifest="${IMPL_DIR}/manifest.yaml"
	if [[ -f $impl_manifest ]]; then
		_mode="$(
			python3 - "$impl_manifest" <<'PYEOF'
import sys
try:
    import yaml
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    mode = (data or {}).get("security_review_mode", "")
    if mode:
        print(str(mode).strip())
except Exception:
    pass
PYEOF
		)" || _mode=""
		if [[ -n $_mode ]]; then
			echo "$_mode"
			return 0
		fi
	fi

	# 4. Default: auto
	echo "auto"
}

# Resolve auto mode: check for security-sensitive keywords in context
_resolve_security_auto_trigger() {
	# Check manifest security_sensitive flag
	local impl_manifest="${IMPL_DIR}/manifest.yaml"
	if [[ -f $impl_manifest ]]; then
		local _flag
		_flag="$(
			python3 - "$impl_manifest" <<'PYEOF'
import sys
try:
    import yaml
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    print("true" if data.get("security_sensitive") is True else "false")
except Exception:
    print("false")
PYEOF
		)" || _flag="false"
		if [[ $_flag == "true" ]]; then
			log_info "dispatch_review: security auto-trigger: security_sensitive=true in manifest"
			return 0
		fi
	fi

	# Scan context_pack and impl_report for security keywords
	local _keywords="auth crypto secret token apikey api_key permission rbac acl session password passwd hash hmac sign eval exec cors csrf csp infra firewall certificate tls ssl private_key ssh_key"
	local _scan_file _kw
	for _scan_file in "$CONTEXT_PACK" "$IMPL_REPORT"; do
		[[ -s $_scan_file ]] || continue
		for _kw in $_keywords; do
			if grep -qi "$_kw" "$_scan_file"; then
				log_info "dispatch_review: security auto-trigger: keyword='${_kw}' in $(basename "$_scan_file")"
				return 0
			fi
		done
	done

	log_info "dispatch_review: security auto: no trigger conditions found — security lens skipped"
	return 1
}

generate_consolidated_findings_json() {
	local summary_file="$1"
	local round="$2"
	local out_json="$3"

	python3 - "$summary_file" "$round" "$out_json" <<'PYEOF'
import datetime
import json
import os
import re
import sys

summary_file = sys.argv[1]
round_number = int(sys.argv[2])
out_json = sys.argv[3]

with open(summary_file, "r", encoding="utf-8", errors="replace") as f:
    lines = f.read().splitlines()

high_re = re.compile(r"\b(?:HIGH|CRITICAL)\b", re.IGNORECASE)
medium_re = re.compile(r"\b(?:MEDIUM|WARNING)\b", re.IGNORECASE)
low_re = re.compile(r"\b(?:LOW|INFO)\b", re.IGNORECASE)

high_count = 0
medium_count = 0
low_count = 0
high_findings = []
seen_high = set()

for line in lines:
    text = line.strip()
    if high_re.search(line):
        high_count += 1
        if text and text not in seen_high and len(high_findings) < 10:
            seen_high.add(text)
            high_findings.append(text)
    if medium_re.search(line):
        medium_count += 1
    if low_re.search(line):
        low_count += 1

payload = {
    "round": round_number,
    "high_count": high_count,
    "medium_count": medium_count,
    "low_count": low_count,
    "high_findings": high_findings,
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
partial = out_json + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, out_json)

print(high_count)
PYEOF
}

attach_findings_for_fix() {
	local round="$1"
	local summary_file="$2"
	local consolidated_file="$3"
	local attachments_dir="${IMPL_DIR}/inputs/attachments"

	mkdir -p "$attachments_dir"
	cp "$summary_file" "${attachments_dir}/review-round-${round}-summary.md"
	cp "$consolidated_file" "${attachments_dir}/review-round-${round}-consolidated-findings.json"
}

generate_parallel_summary_md() {
	local merged_file="$1"
	local queue_file="$2"
	local out_md="$3"

	python3 - "$merged_file" "$queue_file" "$out_md" <<'PYEOF'
import json
import os
import sys

merged_file, queue_file, out_md = sys.argv[1], sys.argv[2], sys.argv[3]

with open(merged_file, "r", encoding="utf-8") as f:
    merged = json.load(f)
with open(queue_file, "r", encoding="utf-8") as f:
    queue_data = json.load(f)

finding_count = merged.get("finding_count", 0)
queue = queue_data.get("queue", [])
queue_total = len(queue)
status_counts = {}
for item in queue:
    status = item.get("status", "unknown")
    status_counts[status] = status_counts.get(status, 0) + 1

lines = [
    "# Parallel Review Summary",
    "",
    f"Task: {merged.get('task_name', '')}",
    f"Lens count: {merged.get('lens_count', 0)}",
    f"Findings: {finding_count}",
    f"Fix queue items: {queue_total}",
    "",
    "## Queue Status",
]
if status_counts:
    for key in sorted(status_counts.keys()):
        lines.append(f"- {key}: {status_counts[key]}")
else:
    lines.append("- pending: 0")

lines.extend([
    "",
    "## Artifacts",
    "- review/review_merged_findings.json",
    "- review/review_fix_queue.json",
    "- review/review_merge_log.json",
    "- review/findings/<lens>.md",
    "",
])

os.makedirs(os.path.dirname(os.path.abspath(out_md)), exist_ok=True)
with open(out_md, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
PYEOF
}

POST_IMPL_REVIEW_SCRIPT="${SCRIPT_DIR}/post_impl_review.sh"
if [[ ! -f $POST_IMPL_REVIEW_SCRIPT ]]; then
	fail_phase "dispatch_review: post_impl_review.sh not found: ${POST_IMPL_REVIEW_SCRIPT}"
fi

REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FIX_PROMPT_FILE="${REPO_ROOT}/prompts-src/codex/fix.md"
IMPL_MANIFEST="${IMPL_DIR}/manifest.yaml"
FIX_LOOP_ENABLED=true
if [[ ! -f $IMPL_MANIFEST ]]; then
	FIX_LOOP_ENABLED=false
	log_warn "dispatch_review: manifest missing, skipping codex_fix loop: ${IMPL_MANIFEST}"
fi

FINAL_DIR="${REVIEW_DIR}/final"
mkdir -p "$FINAL_DIR"
rm -f "${FINAL_DIR}/summary.md" "${FINAL_DIR}/round-completed"

WEB_RESEARCH_MODE="$(resolve_review_web_research_mode)"
log_info "dispatch_review: web_research_mode=${WEB_RESEARCH_MODE}"
ensure_review_web_artifact_stubs "$WEB_RESEARCH_MODE"

if [[ $PARALLEL_REVIEW == "true" ]]; then
	# Resolve security review mode
	RESOLVED_SECURITY_MODE="$(resolve_security_review_mode)"
	if [[ $RESOLVED_SECURITY_MODE == "auto" ]]; then
		if _resolve_security_auto_trigger; then
			RESOLVED_SECURITY_MODE="always"
		else
			RESOLVED_SECURITY_MODE="off"
		fi
	fi
	log_info "dispatch_review: security_review_mode=${RESOLVED_SECURITY_MODE}"

	LENSES=("correctness" "maintainability")
	if [[ $RESOLVED_SECURITY_MODE != "off" ]]; then
		LENSES+=("security")
	fi

	export REVIEW_PARALLEL_CONTEXT_PACK="$CONTEXT_PACK"
	export REVIEW_PARALLEL_IMPL_REPORT="$IMPL_REPORT"
	export REVIEW_PARALLEL_POST_IMPL_REVIEW_SCRIPT="${REVIEW_PARALLEL_POST_IMPL_REVIEW_SCRIPT:-$POST_IMPL_REVIEW_SCRIPT}"
	export REVIEW_PARALLEL_REVIEW_PROFILE="${REVIEW_PARALLEL_REVIEW_PROFILE:-review_only}"
	export REVIEW_PARALLEL_DISPATCH_SCRIPT="${REVIEW_PARALLEL_DISPATCH_SCRIPT:-${SCRIPT_DIR}/dispatch.sh}"
	export REVIEW_PARALLEL_FIX_PROMPT_FILE="${REVIEW_PARALLEL_FIX_PROMPT_FILE:-$FIX_PROMPT_FILE}"

	log_info "dispatch_review: parallel lenses=${LENSES[*]}"
	review_run_lenses_parallel "$TASK_ROOT" "review" "${LENSES[@]}" ||
		fail_phase "dispatch_review: parallel lens launch failed"
	review_join_barrier "$TASK_ROOT" "${LENSES[@]}" "$PARALLEL_REVIEW_TIMEOUT_SEC" ||
		fail_phase "dispatch_review: join barrier failed"
	review_merge_findings "$TASK_ROOT" "${LENSES[@]}" ||
		fail_phase "dispatch_review: merge findings failed"
	review_build_fix_queue "$TASK_ROOT" ||
		fail_phase "dispatch_review: build fix queue failed"
	review_execute_fix_queue "$TASK_ROOT" "$IMPL_DIR" ||
		fail_phase "dispatch_review: fix queue execution failed"

	# Security gate: check and handle security findings if security lens was active
	if [[ " ${LENSES[*]} " =~ " security " ]]; then
		SEC_GATE_RESULT=0
		review_check_and_handle_security \
			"$TASK_ROOT" "$IMPL_DIR" "${SECURITY_FIX_MAX_ROUNDS:-3}" "$RESOLVED_SECURITY_MODE" || SEC_GATE_RESULT=$?
		if [[ $SEC_GATE_RESULT -eq 2 ]]; then
			generate_parallel_summary_md \
				"${REVIEW_DIR}/review_merged_findings.json" \
				"${REVIEW_DIR}/review_fix_queue.json" \
				"${REVIEW_DIR}/summary.md"
			cp "${REVIEW_DIR}/summary.md" "${FINAL_DIR}/summary.md"
			printf '%s\n' "parallel" >"${FINAL_DIR}/round-completed"
			fail_phase "dispatch_review: STOP_AND_CONFIRM — critical security findings require human review (see review/security_gate_result.json)"
		fi
	fi

	generate_parallel_summary_md \
		"${REVIEW_DIR}/review_merged_findings.json" \
		"${REVIEW_DIR}/review_fix_queue.json" \
		"${REVIEW_DIR}/summary.md"
	cp "${REVIEW_DIR}/summary.md" "${FINAL_DIR}/summary.md"
	printf '%s\n' "parallel" >"${FINAL_DIR}/round-completed"
	dispatch_core_record_phase_done "$TASK_ROOT" "$RUN_ID" "review" "success"
	log_ok "dispatch_review: parallel review complete — ${REVIEW_DIR}/review_merged_findings.json"
	exit 0
fi

ROUND="$REVIEW_START_ROUND"
ROUND_COMPLETED=0

while ((ROUND <= REVIEW_MAX_ROUNDS)); do
	log_info "dispatch_review: round ${ROUND} of ${REVIEW_MAX_ROUNDS}"

	ROUND_DIR="${REVIEW_DIR}/round-${ROUND}"
	mkdir -p "$ROUND_DIR"

	REVIEW_EXIT=0
	"$POST_IMPL_REVIEW_SCRIPT" "$CONTEXT_PACK" "$IMPL_REPORT" "$ROUND_DIR" "$REVIEW_PROFILE" || REVIEW_EXIT=$?
	if [[ $REVIEW_EXIT -ne 0 ]]; then
		fail_phase "dispatch_review: review pipeline failed in round ${ROUND} (exit=${REVIEW_EXIT})"
	fi

	SUMMARY_FILE="${ROUND_DIR}/summary.md"
	if [[ ! -f $SUMMARY_FILE ]]; then
		fail_phase "dispatch_review: summary.md missing after round ${ROUND}: ${SUMMARY_FILE}"
	fi

	CONSOLIDATED_FILE="${ROUND_DIR}/consolidated-findings.json"
	HIGH_COUNT="$(generate_consolidated_findings_json "$SUMMARY_FILE" "$ROUND" "$CONSOLIDATED_FILE")"
	ROUND_COMPLETED="$ROUND"
	log_info "dispatch_review: round ${ROUND} high_count=${HIGH_COUNT}"

	if [[ $HIGH_COUNT == "0" ]]; then
		cp "$SUMMARY_FILE" "${FINAL_DIR}/summary.md"
		printf '%s\n' "$ROUND_COMPLETED" >"${FINAL_DIR}/round-completed"
		dispatch_core_record_phase_done "$TASK_ROOT" "$RUN_ID" "review" "success"
		log_ok "dispatch_review: complete — ${FINAL_DIR}/summary.md"
		exit 0
	fi

	if ((ROUND == REVIEW_MAX_ROUNDS)); then
		log_warn "dispatch_review: max rounds reached (${REVIEW_MAX_ROUNDS}) with remaining HIGH findings"
		break
	fi

	if [[ $FIX_LOOP_ENABLED != "true" ]]; then
		log_warn "dispatch_review: codex_fix skipped because impl manifest is missing"
		break
	fi

	if [[ ! -f $FIX_PROMPT_FILE ]]; then
		log_warn "dispatch_review: codex_fix prompt missing, skipping fix: ${FIX_PROMPT_FILE}"
		ROUND=$((ROUND + 1))
		continue
	fi

	attach_findings_for_fix "$ROUND" "$SUMMARY_FILE" "$CONSOLIDATED_FILE"

	FIX_EXIT=0
	"${SCRIPT_DIR}/dispatch.sh" single \
		--task "${TASK_ROOT}/impl" \
		--stage codex_fix || FIX_EXIT=$?
	if [[ $FIX_EXIT -ne 0 ]]; then
		log_warn "dispatch_review: codex_fix failed in round ${ROUND} (exit=${FIX_EXIT}); continuing"
	fi

	ROUND=$((ROUND + 1))
done

dispatch_core_record_phase_done "$TASK_ROOT" "$RUN_ID" "review" "success"
printf '%s\n' "$ROUND_COMPLETED" >"${FINAL_DIR}/round-completed"
log_ok "dispatch_review: complete — no clean round within max rounds"
exit 0
