#!/usr/bin/env bash
# review_parallel.sh — Parallel review lens orchestration helpers
# Usage: source this file

set -euo pipefail

REVIEW_PARALLEL_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${REVIEW_PARALLEL_LIB_DIR}/log.sh"

review_lens_focus_prompt() {
	local lens="$1"
	case "$lens" in
	correctness)
		cat <<'EOF'
Focus strictly on correctness and behavioral defects.
Prioritize logic errors, incorrect edge-case handling, state transitions, and regressions.
EOF
		;;
	security)
		local _sec_tmpl="${REVIEW_PARALLEL_LIB_DIR}/../../../prompts-src/security/security_review.md"
		if [[ -f $_sec_tmpl ]]; then
			cat "$_sec_tmpl"
		else
			cat <<'EOF'
Focus strictly on security risks and unsafe patterns.
Prioritize injection vectors, authz/authn gaps, secret exposure, data leaks, and unsafe shell usage.
EOF
		fi
		;;
	maintainability)
		cat <<'EOF'
Focus strictly on maintainability and long-term code health.
Prioritize clarity, cohesion, duplication, fragile coupling, and testability gaps.
EOF
		;;
	*)
		cat <<'EOF'
Focus on actionable code review findings for this specific lens.
EOF
		;;
	esac
}

review_prepare_lens_context_pack() {
	local lens="$1"
	local src_context_pack="$2"
	local out_context_pack="$3"

	cp "$src_context_pack" "$out_context_pack"
	{
		printf '\n\n## Parallel Review Lens\n'
		printf 'Lens: %s\n\n' "$lens"
		review_lens_focus_prompt "$lens"
		printf '\nAdditional constraints:\n'
		printf '%s\n' '- Analysis only. Do not apply fixes.'
		printf '%s\n' '- Produce concrete, file-targeted findings.'
		printf '%s\n' '- Include severity and confidence in findings.'
	} >>"$out_context_pack"
}

review_run_single_lens() {
	local task_root="$1"
	local phase="$2"
	local lens="$3"

	local context_pack="${REVIEW_PARALLEL_CONTEXT_PACK:-${task_root}/impl/inputs/context_pack.md}"
	local impl_report="${REVIEW_PARALLEL_IMPL_REPORT:-${task_root}/impl/outputs/_summary.md}"
	local review_profile="${REVIEW_PARALLEL_REVIEW_PROFILE:-review_only}"
	local post_impl_script="${REVIEW_PARALLEL_POST_IMPL_REVIEW_SCRIPT:-${REVIEW_PARALLEL_LIB_DIR}/../post_impl_review.sh}"

	local review_dir="${task_root}/review"
	local findings_dir="${review_dir}/findings"
	local pid_dir="${findings_dir}/.pids"
	local status_dir="${findings_dir}/.status"
	local logs_dir="${findings_dir}/.logs"
	local runs_dir="${findings_dir}/.runs"
	local inputs_dir="${findings_dir}/.inputs"

	mkdir -p "$findings_dir" "$pid_dir" "$status_dir" "$logs_dir" "$runs_dir" "$inputs_dir"

	local lens_context="${inputs_dir}/context_pack.${lens}.md"
	local lens_output_dir="${runs_dir}/${lens}"
	local lens_log="${logs_dir}/${lens}.log"
	local lens_findings="${findings_dir}/${lens}.md"
	local lens_exit="${status_dir}/${lens}.exit"
	local lens_timeout_sec="${REVIEW_PARALLEL_LENS_TIMEOUT_SEC:-900}"

	review_prepare_lens_context_pack "$lens" "$context_pack" "$lens_context"
	rm -rf "$lens_output_dir"
	mkdir -p "$lens_output_dir"

	local run_exit=0
	if [[ $lens_timeout_sec =~ ^[0-9]+$ ]] && ((lens_timeout_sec > 0)); then
		perl -e "alarm(${lens_timeout_sec}); \$SIG{ALRM}=sub{exit(124)}; exec(@ARGV) or exit(125);" -- \
			"$post_impl_script" "$lens_context" "$impl_report" "$lens_output_dir" "$review_profile" >"$lens_log" 2>&1 || run_exit=$?
	else
		"$post_impl_script" "$lens_context" "$impl_report" "$lens_output_dir" "$review_profile" >"$lens_log" 2>&1 || run_exit=$?
	fi
	if [[ $run_exit -ne 0 ]]; then
		{
			printf '# Lens: %s\n\n' "$lens"
			printf 'Status: DEGRADED (exit=%s)\n\n' "$run_exit"
			printf 'Log: %s\n' "$lens_log"
		} >"$lens_findings"
		printf '%s\n' "$run_exit" >"$lens_exit"
		log_warn "review_parallel: lens=${lens} degraded (exit=${run_exit}); continuing with placeholder findings"
		return 0
	fi

	if [[ -s "${lens_output_dir}/summary.md" ]]; then
		cp "${lens_output_dir}/summary.md" "$lens_findings"
	elif [[ -s "${lens_output_dir}/gemini_review.md" ]]; then
		cp "${lens_output_dir}/gemini_review.md" "$lens_findings"
	else
		{
			printf '# Lens: %s\n\n' "$lens"
			printf 'No summary artifact found for this lens.\n'
		} >"$lens_findings"
	fi

	printf '0\n' >"$lens_exit"
	return 0
}

review_run_lenses_parallel() {
	local task_root="$1"
	local phase="$2"
	shift 2
	local lenses=("$@")

	if [[ ${#lenses[@]} -eq 0 ]]; then
		log_error "review_parallel: no lenses provided"
		return 1
	fi

	local findings_dir="${task_root}/review/findings"
	local pid_dir="${findings_dir}/.pids"
	local status_dir="${findings_dir}/.status"

	mkdir -p "$findings_dir" "$pid_dir" "$status_dir"
	rm -f "${pid_dir}"/*.pid "${status_dir}"/*.exit "${status_dir}/join-timeout.flag" 2>/dev/null || true

	log_info "review_parallel: phase=${phase} launching ${#lenses[@]} lenses"
	for lens in "${lenses[@]}"; do
		review_run_single_lens "$task_root" "$phase" "$lens" &
		local pid="$!"
		printf '%s\n' "$pid" >"${pid_dir}/${lens}.pid"
		log_info "review_parallel: started lens=${lens} pid=${pid}"
	done

	return 0
}

review_join_barrier_add_failed() {
	local lens="$1"
	shift || true
	local existing
	for existing in "$@"; do
		if [[ $existing == "$lens" ]]; then
			return 1
		fi
	done
	return 0
}

review_join_barrier() {
	local task_root="$1"
	shift
	local argc="$#"
	if ((argc < 2)); then
		log_error "review_parallel: join barrier requires lenses and timeout"
		return 1
	fi

	local timeout_sec="${!argc}"
	local lenses=()
	local i=1
	while ((i < argc)); do
		lenses+=("${!i}")
		i=$((i + 1))
	done

	if [[ ! $timeout_sec =~ ^[0-9]+$ ]]; then
		log_error "review_parallel: timeout must be a non-negative integer (got: ${timeout_sec})"
		return 1
	fi

	local findings_dir="${task_root}/review/findings"
	local pid_dir="${findings_dir}/.pids"
	local status_dir="${findings_dir}/.status"
	local timeout_flag="${status_dir}/join-timeout.flag"
	rm -f "$timeout_flag"

	local watchdog_pid=""
	if ((timeout_sec > 0)); then
		(
			sleep "$timeout_sec"
			: >"$timeout_flag"
			for lens in "${lenses[@]}"; do
				local pid_file="${pid_dir}/${lens}.pid"
				if [[ -f $pid_file ]]; then
					local pid
					pid="$(cat "$pid_file" 2>/dev/null || true)"
					if [[ $pid =~ ^[0-9]+$ ]]; then
						kill "$pid" 2>/dev/null || true
					fi
				fi
			done
		) &
		watchdog_pid="$!"
	fi

	local failed_lenses=()
	local lens
	for lens in "${lenses[@]}"; do
		local pid_file="${pid_dir}/${lens}.pid"
		if [[ ! -f $pid_file ]]; then
			log_error "review_parallel: missing pid file for lens=${lens}"
			if review_join_barrier_add_failed "$lens" "${failed_lenses[@]}"; then
				failed_lenses+=("$lens")
			fi
			continue
		fi

		local pid
		pid="$(cat "$pid_file" 2>/dev/null || true)"
		if [[ ! $pid =~ ^[0-9]+$ ]]; then
			log_error "review_parallel: invalid pid for lens=${lens}: ${pid}"
			if review_join_barrier_add_failed "$lens" "${failed_lenses[@]}"; then
				failed_lenses+=("$lens")
			fi
			continue
		fi

		local wait_exit=0
		wait "$pid" || wait_exit=$?
		if [[ $wait_exit -ne 0 ]]; then
			log_error "review_parallel: lens=${lens} failed in join barrier (exit=${wait_exit})"
			if review_join_barrier_add_failed "$lens" "${failed_lenses[@]}"; then
				failed_lenses+=("$lens")
			fi
			continue
		fi

		if [[ ! -s "${findings_dir}/${lens}.md" ]]; then
			log_error "review_parallel: lens output missing: ${findings_dir}/${lens}.md"
			if review_join_barrier_add_failed "$lens" "${failed_lenses[@]}"; then
				failed_lenses+=("$lens")
			fi
		fi
	done

	if [[ -n $watchdog_pid ]]; then
		kill "$watchdog_pid" 2>/dev/null || true
		wait "$watchdog_pid" 2>/dev/null || true
	fi

	if [[ -f $timeout_flag ]]; then
		log_error "review_parallel: join barrier timeout after ${timeout_sec}s"
		for lens in "${lenses[@]}"; do
			if review_join_barrier_add_failed "$lens" "${failed_lenses[@]}"; then
				failed_lenses+=("$lens")
			fi
		done
	fi

	if [[ ${#failed_lenses[@]} -gt 0 ]]; then
		log_error "review_parallel: join barrier failed lenses: ${failed_lenses[*]}"
		return 1
	fi

	log_ok "review_parallel: join barrier passed for lenses: ${lenses[*]}"
	return 0
}

review_merge_findings() {
	local task_root="$1"
	shift
	local lenses=("$@")
	if [[ ${#lenses[@]} -eq 0 ]]; then
		log_error "review_parallel: cannot merge findings without lenses"
		return 1
	fi

	local review_dir="${task_root}/review"
	local merged_file="${review_dir}/review_merged_findings.json"
	local merge_log_file="${review_dir}/review_merge_log.json"

	python3 - "$task_root" "$merged_file" "$merge_log_file" "${lenses[@]}" <<'PYEOF'
import datetime
import json
import os
import re
import sys

task_root = os.path.abspath(sys.argv[1])
merged_file = os.path.abspath(sys.argv[2])
merge_log_file = os.path.abspath(sys.argv[3])
lenses = list(sys.argv[4:])
task_name = os.path.basename(task_root.rstrip(os.sep))
findings_dir = os.path.join(task_root, "review", "findings")
os.makedirs(os.path.dirname(merged_file), exist_ok=True)

severity_rank = {
    "critical": 5,
    "major": 4,
    "medium": 3,
    "minor": 2,
    "low": 1,
}

def detect_severity(text: str) -> str:
    t = text.lower()
    if "critical" in t:
        return "critical"
    if "high" in t or "major" in t:
        return "major"
    if "medium" in t or "warning" in t:
        return "medium"
    if "low" in t or "info" in t:
        return "low"
    return "minor"

def detect_confidence(text: str, has_file: bool, has_location: bool) -> str:
    t = text.lower()
    if "confidence: high" in t or (has_file and has_location):
        return "high"
    if "confidence: low" in t:
        return "low"
    return "medium"

def normalize_issue(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def find_target_file(text: str) -> str:
    m = re.search(r"([A-Za-z0-9_./-]+\.(?:sh|py|md|json|ya?ml|ts|js|tsx|jsx|go|rs|java|kt|rb|php|c|cpp|h))", text)
    return m.group(1) if m else ""

def find_target_location(text: str) -> str:
    m = re.search(r"((?:L|line)\s*\d+|:\d+(?::\d+)?)", text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else ""

def extract_evidence_ids(text: str):
    ids = re.findall(r"\b(?:CVE-\d{4}-\d+|RFC\s*\d+|EVID-\d+)\b", text, flags=re.IGNORECASE)
    normalized = []
    for eid in ids:
        eid = re.sub(r"\s+", "", eid.upper())
        if eid not in normalized:
            normalized.append(eid)
    return normalized

raw_finding_counts = {}
raw_findings = []
for lens in lenses:
    path = os.path.join(findings_dir, f"{lens}.md")
    raw_finding_counts[lens] = 0
    if not os.path.isfile(path):
        continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped or stripped.startswith("#"):
            continue

        candidate = None
        if stripped.startswith("- ") or stripped.startswith("* "):
            candidate = stripped[2:].strip()
        elif re.match(r"^\d+\.\s+", stripped):
            candidate = re.sub(r"^\d+\.\s+", "", stripped).strip()
        elif re.search(r"\b(critical|high|major|medium|warning|minor|low|info)\b", stripped, flags=re.IGNORECASE):
            candidate = stripped

        if not candidate:
            continue
        if len(candidate) < 8:
            continue

        target_file = find_target_file(candidate)
        target_location = find_target_location(candidate)
        evidence_ids = extract_evidence_ids(candidate)
        uses_external_evidence = bool(evidence_ids or "http://" in candidate.lower() or "https://" in candidate.lower())
        finding = {
            "lens": lens,
            "target_file": target_file,
            "target_location": target_location,
            "issue": normalize_issue(candidate),
            "reason": "",
            "proposed_improvement": "",
            "impact_scope": "local",
            "severity": detect_severity(candidate),
            "confidence": detect_confidence(candidate, bool(target_file), bool(target_location)),
            "uses_external_evidence": uses_external_evidence,
            "evidence_ids": evidence_ids,
        }
        raw_findings.append(finding)
        raw_finding_counts[lens] += 1

dedup_removed = 0
conflict_resolved = 0
evidence_rejected = 0

dedup_map = {}
ordered = []
for finding in raw_findings:
    key = (
        finding["target_file"].lower(),
        re.sub(r"[^a-z0-9]+", " ", finding["issue"].lower()).strip(),
    )
    if key not in dedup_map:
        dedup_map[key] = finding
        ordered.append(key)
        continue
    dedup_removed += 1
    existing = dedup_map[key]
    if severity_rank.get(finding["severity"], 0) > severity_rank.get(existing["severity"], 0):
        dedup_map[key] = finding
        conflict_resolved += 1

findings = []
for idx, key in enumerate(ordered, start=1):
    finding = dict(dedup_map[key])
    finding["finding_id"] = f"F{idx:03d}"
    findings.append(finding)

timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

merged_payload = {
    "task_name": task_name,
    "lens_count": len(lenses),
    "finding_count": len(findings),
    "findings": findings,
    "generated_at": timestamp,
}
merge_log = {
    "lenses": lenses,
    "raw_finding_counts": raw_finding_counts,
    "dedup_removed": dedup_removed,
    "conflict_resolved": conflict_resolved,
    "evidence_rejected": evidence_rejected,
    "final_count": len(findings),
    "generated_at": timestamp,
}

for path, payload in ((merged_file, merged_payload), (merge_log_file, merge_log)):
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(partial, path)
PYEOF

	log_ok "review_parallel: merged findings written: ${merged_file}"
	return 0
}

review_build_fix_queue() {
	local task_root="$1"
	local review_dir="${task_root}/review"
	local merged_file="${review_dir}/review_merged_findings.json"
	local queue_file="${review_dir}/review_fix_queue.json"

	if [[ ! -s $merged_file ]]; then
		log_error "review_parallel: merged findings file missing: ${merged_file}"
		return 1
	fi

	python3 - "$merged_file" "$queue_file" <<'PYEOF'
import datetime
import json
import os
import sys

merged_file = os.path.abspath(sys.argv[1])
queue_file = os.path.abspath(sys.argv[2])

with open(merged_file, "r", encoding="utf-8") as f:
    merged = json.load(f)

severity_priority = {
    "critical": 1,
    "major": 2,
    "medium": 3,
    "minor": 4,
    "low": 5,
}

def normalize_action(finding):
    proposed = (finding.get("proposed_improvement") or "").strip()
    if proposed:
        return proposed
    issue = (finding.get("issue") or "").strip()
    if issue:
        return issue
    return "Address finding"

sorted_findings = sorted(
    merged.get("findings", []),
    key=lambda f: (severity_priority.get((f.get("severity") or "").lower(), 9), f.get("finding_id", "")),
)

queue = []
for idx, finding in enumerate(sorted_findings, start=1):
    queue.append(
        {
            "queue_id": f"Q{idx:03d}",
            "finding_id": finding.get("finding_id", ""),
            "target_file": finding.get("target_file", ""),
            "target_location": finding.get("target_location", ""),
            "action": normalize_action(finding),
            "priority": severity_priority.get((finding.get("severity") or "").lower(), 9),
            "status": "pending",
        }
    )

payload = {
    "task_name": merged.get("task_name", ""),
    "queue": queue,
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

os.makedirs(os.path.dirname(queue_file), exist_ok=True)
partial = queue_file + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, queue_file)
PYEOF

	log_ok "review_parallel: fix queue written: ${queue_file}"
	return 0
}

review_update_queue_status() {
	local queue_file="$1"
	local queue_id="$2"
	local status="$3"

	python3 - "$queue_file" "$queue_id" "$status" <<'PYEOF'
import json
import os
import sys

queue_file = os.path.abspath(sys.argv[1])
queue_id = sys.argv[2]
status = sys.argv[3]

with open(queue_file, "r", encoding="utf-8") as f:
    payload = json.load(f)

for item in payload.get("queue", []):
    if item.get("queue_id") == queue_id:
        item["status"] = status
        break

partial = queue_file + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, queue_file)
PYEOF
}

review_execute_fix_queue() {
	local task_root="$1"
	local impl_dir="$2"

	local review_dir="${task_root}/review"
	local queue_file="${review_dir}/review_fix_queue.json"
	local merged_file="${review_dir}/review_merged_findings.json"
	local dispatch_script="${REVIEW_PARALLEL_DISPATCH_SCRIPT:-${REVIEW_PARALLEL_LIB_DIR}/../dispatch.sh}"
	local fix_prompt_file="${REVIEW_PARALLEL_FIX_PROMPT_FILE-}"
	local impl_manifest="${impl_dir}/manifest.yaml"
	local attachments_dir="${impl_dir}/inputs/attachments"

	if [[ ! -s $queue_file ]]; then
		log_warn "review_parallel: queue file missing, skipping execution: ${queue_file}"
		return 0
	fi

	mkdir -p "$attachments_dir"
	cp "$queue_file" "${attachments_dir}/review_fix_queue.json"
	if [[ -f $merged_file ]]; then
		cp "$merged_file" "${attachments_dir}/review_merged_findings.json"
	fi

	local queue_count
	queue_count="$(
		python3 - "$queue_file" <<'PYEOF'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
print(len(data.get("queue", [])))
PYEOF
	)"

	if [[ $queue_count == "0" ]]; then
		log_info "review_parallel: no findings in queue"
		return 0
	fi

	log_info "review_parallel: executing fix queue sequentially (items=${queue_count})"

	while IFS=$'\t' read -r queue_id finding_id action; do
		[[ -z $queue_id ]] && continue
		log_info "review_parallel: queue=${queue_id} finding=${finding_id} action=${action}"

		if [[ ! -f $impl_manifest ]]; then
			log_warn "review_parallel: impl manifest missing; marking ${queue_id} as skipped"
			review_update_queue_status "$queue_file" "$queue_id" "skipped"
			continue
		fi
		if [[ -n $fix_prompt_file && ! -f $fix_prompt_file ]]; then
			log_warn "review_parallel: fix prompt missing; marking ${queue_id} as skipped"
			review_update_queue_status "$queue_file" "$queue_id" "skipped"
			continue
		fi
		if [[ ! -f $dispatch_script ]]; then
			log_warn "review_parallel: dispatch script missing; marking ${queue_id} as failed"
			review_update_queue_status "$queue_file" "$queue_id" "failed"
			continue
		fi

		local fix_exit=0
		"$dispatch_script" single --task "$impl_dir" --stage codex_fix || fix_exit=$?
		if [[ $fix_exit -eq 0 ]]; then
			review_update_queue_status "$queue_file" "$queue_id" "applied"
		else
			log_warn "review_parallel: codex_fix failed for ${queue_id} (exit=${fix_exit})"
			review_update_queue_status "$queue_file" "$queue_id" "failed"
		fi
	done < <(
		python3 - "$queue_file" <<'PYEOF'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    payload = json.load(f)

for item in payload.get("queue", []):
    if item.get("status") != "pending":
        continue
    queue_id = (item.get("queue_id") or "").replace("\t", " ").replace("\n", " ")
    finding_id = (item.get("finding_id") or "").replace("\t", " ").replace("\n", " ")
    action = (item.get("action") or "").replace("\t", " ").replace("\n", " ")
    print(f"{queue_id}\t{finding_id}\t{action}")
PYEOF
	)

	log_ok "review_parallel: fix queue execution complete"
	return 0
}

review_write_security_gate_result() {
	local task_root="$1"
	local final_severity="$2" # none | high | critical
	local stop_action="$3"    # null | STOP_AND_CONFIRM
	local rounds_run="$4"
	local security_mode="$5"

	local gate_result_file="${task_root}/review/security_gate_result.json"

	# Serialize arguments safely (bash 3.2 compatible)
	local critical_json="[]"
	local high_json="[]"
	if [[ ${#SECURITY_CRITICAL_FINDINGS[@]} -gt 0 ]]; then
		critical_json=$(printf '%s\n' "${SECURITY_CRITICAL_FINDINGS[@]}" |
			python3 -c 'import json,sys; print(json.dumps([l.rstrip("\n") for l in sys.stdin]))')
	fi
	if [[ ${#SECURITY_HIGH_FINDINGS[@]} -gt 0 ]]; then
		high_json=$(printf '%s\n' "${SECURITY_HIGH_FINDINGS[@]}" |
			python3 -c 'import json,sys; print(json.dumps([l.rstrip("\n") for l in sys.stdin]))')
	fi

	local stop_action_json="null"
	if [[ $stop_action == "STOP_AND_CONFIRM" ]]; then
		stop_action_json='"STOP_AND_CONFIRM"'
	fi

	mkdir -p "$(dirname "$gate_result_file")"
	python3 - "$gate_result_file" "$final_severity" "$stop_action_json" \
		"$rounds_run" "$security_mode" "$critical_json" "$high_json" <<'PYEOF'
import json, sys, os
from datetime import datetime, timezone

out_path = sys.argv[1]
final_severity = sys.argv[2]
stop_action_raw = sys.argv[3]
rounds_run = int(sys.argv[4])
security_mode = sys.argv[5]
critical_json = sys.argv[6]
high_json = sys.argv[7]

try:
    stop_action = json.loads(stop_action_raw)
except Exception:
    stop_action = None

try:
    critical_findings = json.loads(critical_json)
except Exception:
    critical_findings = []

try:
    high_findings = json.loads(high_json)
except Exception:
    high_findings = []

payload = {
    "enabled": True,
    "mode": security_mode,
    "final_severity": final_severity,
    "stop_action": stop_action,
    "rounds_run": rounds_run,
    "critical_findings": critical_findings,
    "high_findings_remaining": high_findings,
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

partial = out_path + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, out_path)
PYEOF
	log_ok "review_parallel: security gate result written: ${gate_result_file}"
}

# review_check_and_handle_security <task_root> <impl_dir> <max_rounds> <security_mode>
# Returns:
#   0 = clean (no critical/high)
#   1 = high findings remain after max rounds (warn)
#   2 = critical found -> STOP_AND_CONFIRM
review_check_and_handle_security() {
	local task_root="$1"
	local impl_dir="$2"
	local max_rounds="${3:-3}"
	local security_mode="${4:-auto}"

	local merged_file="${task_root}/review/review_merged_findings.json"
	local fix_rounds_dir="${task_root}/review/security_fix_rounds"
	local dispatch_script="${REVIEW_PARALLEL_DISPATCH_SCRIPT:-${REVIEW_PARALLEL_LIB_DIR}/../dispatch.sh}"

	SECURITY_CRITICAL_FINDINGS=()
	SECURITY_HIGH_FINDINGS=()
	if [[ ! -s $merged_file ]]; then
		log_warn "review_parallel: security check skipped — merged findings missing"
		review_write_security_gate_result "$task_root" "none" "null" 0 "$security_mode"
		return 0
	fi

	# Extract security lens findings and determine max severity
	_review_extract_security_severity() {
		local f="$1"
		python3 - "$f" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    print("none")
    sys.exit(0)

rank = {"critical": 5, "major": 4, "medium": 3, "minor": 2, "low": 1}
max_sev = "none"
max_rank = 0
for f in data.get("findings", []):
    if f.get("lens") != "security":
        continue
    sev = (f.get("severity") or "").lower()
    r = rank.get(sev, 0)
    if r > max_rank:
        max_rank = r
        max_sev = sev
# Normalize: major → high
if max_sev == "major":
    max_sev = "high"
print(max_sev)
PYEOF
	}

	_review_extract_security_issues() {
		local f="$1"
		local level="$2" # critical or high/major
		python3 - "$f" "$level" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)

level = sys.argv[2].lower()
equiv = {level, "major" if level == "high" else level}
for f in data.get("findings", []):
    if f.get("lens") != "security":
        continue
    sev = (f.get("severity") or "").lower()
    if sev in equiv:
        issue = (f.get("issue") or "").replace("\n", " ").strip()
        if issue:
            print(issue)
PYEOF
	}

	# --- bash 3.2 safe array capture ---
	local _line
	while IFS= read -r _line; do
		if [[ -n $_line ]]; then
			SECURITY_CRITICAL_FINDINGS+=("$_line")
		fi
	done < <(_review_extract_security_issues "$merged_file" "critical")
	while IFS= read -r _line; do
		if [[ -n $_line ]]; then
			SECURITY_HIGH_FINDINGS+=("$_line")
		fi
	done < <(_review_extract_security_issues "$merged_file" "high")

	local max_sev
	max_sev="$(_review_extract_security_severity "$merged_file")"
	log_info "review_parallel: security gate initial max_severity=${max_sev}"

	case "$max_sev" in
	critical)
		log_warn "review_parallel: STOP_AND_CONFIRM — critical security finding requires human review"
		review_write_security_gate_result "$task_root" "critical" "STOP_AND_CONFIRM" 0 "$security_mode"
		return 2
		;;
	none | low | minor | medium)
		review_write_security_gate_result "$task_root" "$max_sev" "null" 0 "$security_mode"
		return 0
		;;
	esac

	# max_sev == high → run fix loop
	log_info "review_parallel: HIGH security findings — starting fix loop (max_rounds=${max_rounds})"
	mkdir -p "$fix_rounds_dir"

	local round=1
	while ((round <= max_rounds)); do
		log_info "review_parallel: security fix round ${round}/${max_rounds}"

		# Attach security findings to impl
		local attachments_dir="${impl_dir}/inputs/attachments"
		mkdir -p "$attachments_dir"
		python3 - "$merged_file" "${attachments_dir}/security_findings_round_${round}.json" "$round" <<'PYEOF'
import json, sys, os
from datetime import datetime, timezone
try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    data = {}
round_num = int(sys.argv[3])
sec_findings = [f for f in data.get("findings", []) if f.get("lens") == "security"]
payload = {
    "round": round_num,
    "security_findings": sec_findings,
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
out_path = sys.argv[2]
partial = out_path + ".partial"
with open(partial, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.replace(partial, out_path)
PYEOF

		# Run codex_fix
		local fix_exit=0
		"$dispatch_script" single --task "$impl_dir" --stage codex_fix || fix_exit=$?
		if [[ $fix_exit -ne 0 ]]; then
			log_warn "review_parallel: codex_fix failed in security round ${round} (exit=${fix_exit})"
		fi

		# Run codex_verify (regression check)
		local verify_exit=0
		"$dispatch_script" single --task "$impl_dir" --stage codex_verify || verify_exit=$?
		if [[ $verify_exit -ne 0 ]]; then
			log_warn "review_parallel: codex_verify failed in security round ${round} (exit=${verify_exit})"
		fi

		# Re-run security lens only
		local recheck_phase="security-recheck-${round}"
		local recheck_findings_dir="${fix_rounds_dir}/round-${round}"
		mkdir -p "$recheck_findings_dir"

		# Temporarily override findings dir for this lens run
		local _orig_context_pack="${REVIEW_PARALLEL_CONTEXT_PACK:-${task_root}/impl/inputs/context_pack.md}"
		local _orig_impl_report="${REVIEW_PARALLEL_IMPL_REPORT:-${task_root}/impl/outputs/_summary.md}"
		local _saved_findings_root="${task_root}/review"

		# Run security lens in isolated dir
		local _tmp_task_root="${fix_rounds_dir}/task-${round}"
		mkdir -p "${_tmp_task_root}/review/findings"
		REVIEW_PARALLEL_CONTEXT_PACK="$_orig_context_pack" \
			REVIEW_PARALLEL_IMPL_REPORT="$_orig_impl_report" \
			review_run_single_lens "$_tmp_task_root" "$recheck_phase" "security"
		# Wait for the background process (review_run_single_lens runs synchronously when called directly)

		local recheck_findings_file="${_tmp_task_root}/review/findings/security.md"

		# Re-extract severity from new findings (create temp merged json)
		local _tmp_merged="${fix_rounds_dir}/round-${round}-merged.json"
		if [[ -s $recheck_findings_file ]]; then
			# Build a minimal merged JSON from the security lens output
			python3 - "$recheck_findings_file" "$_tmp_merged" "$round" <<'PYEOF'
import json, os, re, sys
from datetime import datetime, timezone

findings_path = sys.argv[1]
out_path = sys.argv[2]
round_num = int(sys.argv[3])

severity_rank = {"critical": 5, "major": 4, "medium": 3, "minor": 2, "low": 1}

def detect_severity(text):
    t = text.lower()
    if "critical" in t: return "critical"
    if "high" in t or "major" in t: return "major"
    if "medium" in t or "warning" in t: return "medium"
    if "low" in t or "info" in t: return "low"
    return "minor"

with open(findings_path, "r", encoding="utf-8") as f:
    lines = f.read().splitlines()

findings = []
for i, line in enumerate(lines):
    s = line.strip()
    if re.search(r"\b(critical|high|major|medium|warning|minor|low|info)\b", s, re.IGNORECASE):
        if len(s) >= 8:
            findings.append({
                "finding_id": f"RS{round_num}-{i:03d}",
                "lens": "security",
                "issue": re.sub(r"\s+", " ", s).strip(),
                "severity": detect_severity(s),
                "target_file": "",
                "target_location": "",
            })

payload = {
    "task_name": "security-recheck",
    "finding_count": len(findings),
    "findings": findings,
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
partial = out_path + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, out_path)
PYEOF
		else
			log_warn "review_parallel: security recheck produced no findings file in round ${round}"
			local _tmp_merged_partial="${_tmp_merged}.partial"
			printf '%s\n' '{"findings":[]}' >"$_tmp_merged_partial"
			mv "$_tmp_merged_partial" "$_tmp_merged"
		fi

		# Reset finding arrays for this round
		SECURITY_CRITICAL_FINDINGS=()
		SECURITY_HIGH_FINDINGS=()
		while IFS= read -r _line; do
			[[ -n $_line ]] && SECURITY_CRITICAL_FINDINGS+=("$_line")
		done < <(_review_extract_security_issues "$_tmp_merged" "critical")
		while IFS= read -r _line; do
			[[ -n $_line ]] && SECURITY_HIGH_FINDINGS+=("$_line")
		done < <(_review_extract_security_issues "$_tmp_merged" "high")

		max_sev="$(_review_extract_security_severity "$_tmp_merged")"
		log_info "review_parallel: security recheck round=${round} max_severity=${max_sev}"

		case "$max_sev" in
		critical)
			log_warn "review_parallel: STOP_AND_CONFIRM — critical finding in security fix round ${round}"
			review_write_security_gate_result "$task_root" "critical" "STOP_AND_CONFIRM" "$round" "$security_mode"
			return 2
			;;
		none | low | minor | medium)
			log_ok "review_parallel: security fix loop clean after round ${round}"
			review_write_security_gate_result "$task_root" "none" "null" "$round" "$security_mode"
			return 0
			;;
		esac
		# Still high — continue loop
		round=$((round + 1))
	done

	log_warn "review_parallel: security fix loop reached max_rounds=${max_rounds} with HIGH findings remaining"
	review_write_security_gate_result "$task_root" "high" "null" "$max_rounds" "$security_mode"
	return 1
}
