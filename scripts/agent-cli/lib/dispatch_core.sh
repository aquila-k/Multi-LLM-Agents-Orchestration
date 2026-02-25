#!/usr/bin/env bash
# dispatch_core.sh — Shared session lifecycle management for dispatch phases
# Usage: source this file
#
# This module owns:
# - Session probe management
# - RESUME_SESSION determination (pre-stage)
# - Session ID recording (post-stage)
# - Mismatch validation and fail-fast
# - Session event audit log
#
# Rules:
# - ONLY this module makes session resume decisions
# - Wrappers receive --resume-session as a directive; they do not decide
# - All session events are appended to state/session-events.jsonl

set -euo pipefail

DISPATCH_CORE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${DISPATCH_CORE_LIB_DIR}/log.sh"
source "${DISPATCH_CORE_LIB_DIR}/session_state.sh"
source "${DISPATCH_CORE_LIB_DIR}/session_probe.sh"
source "${DISPATCH_CORE_LIB_DIR}/session_extractor.sh"
source "${DISPATCH_CORE_LIB_DIR}/task_paths.sh"

# ── Phase session policy defaults ─────────────────────────────────────────────

DISPATCH_CORE_DEFAULT_PHASE_SESSION_MODE="${DISPATCH_CORE_DEFAULT_PHASE_SESSION_MODE:-forced_within_phase}"
DISPATCH_CORE_DEFAULT_CROSS_PHASE_RESUME="${DISPATCH_CORE_DEFAULT_CROSS_PHASE_RESUME:-false}"

# ── Initialization ────────────────────────────────────────────────────────────

# dispatch_core_init <task-root> <task-name> <run-id> <run-mode> [phase-session-mode] [cross-phase-resume]
dispatch_core_init() {
	local task_root="$1"
	local task_name="$2"
	local run_id="$3"
	local run_mode="$4"
	local phase_session_mode="${5:-${DISPATCH_CORE_DEFAULT_PHASE_SESSION_MODE}}"
	local cross_phase_resume="${6:-${DISPATCH_CORE_DEFAULT_CROSS_PHASE_RESUME}}"

	session_state_init_task_index \
		"$task_root" "$task_name" "$run_id" "$run_mode" \
		"$phase_session_mode" "$cross_phase_resume"

	session_state_record_event "$task_root" "phase_init" "$run_mode" "none" "none" "started" \
		"run_id=${run_id},mode=${phase_session_mode}"
	log_info "dispatch_core: initialized task=${task_name} run=${run_id} mode=${phase_session_mode}"
}

# ── Pre-stage session management ──────────────────────────────────────────────

# dispatch_core_pre_stage <task-root> <phase> <tool> <stage> [phase-session-mode]
# Sets DISPATCH_CORE_RESUME_ARG and DISPATCH_CORE_SNAPSHOT_FILE in the caller's scope.
# DISPATCH_CORE_RESUME_ARG: non-empty = pass as --resume-session to wrapper
# DISPATCH_CORE_SNAPSHOT_FILE: non-empty = pass as --snapshot-file to wrapper
dispatch_core_pre_stage() {
	local task_root="$1"
	local phase="$2"
	local tool="$3"
	local stage="$4"
	local phase_session_mode="${5:-${DISPATCH_CORE_DEFAULT_PHASE_SESSION_MODE}}"

	DISPATCH_CORE_RESUME_ARG=""
	DISPATCH_CORE_SNAPSHOT_FILE=""

	# Run probe if not yet done for this phase
	local probe_json="${task_root}/state/session-probe/${tool}.json"
	if [[ ! -f $probe_json ]]; then
		log_info "dispatch_core: running session probe for tool=${tool}"
		case "$tool" in
		codex) session_probe_codex "$task_root" ;;
		copilot) session_probe_copilot "$task_root" ;;
		gemini) session_probe_gemini "$task_root" ;;
		esac
	fi

	local resume_supported
	resume_supported=$(session_probe_resume_supported "$task_root" "$tool")

	# Take snapshot (needed for session_id extraction after execution)
	local state_dir="${task_root}/state"
	mkdir -p "$state_dir"
	case "$tool" in
	codex)
		DISPATCH_CORE_SNAPSHOT_FILE="${state_dir}/snapshot-codex-${stage}.txt"
		session_snapshot_codex "$DISPATCH_CORE_SNAPSHOT_FILE"
		;;
	copilot)
		DISPATCH_CORE_SNAPSHOT_FILE="${state_dir}/snapshot-copilot-${stage}.txt"
		session_snapshot_copilot "$DISPATCH_CORE_SNAPSHOT_FILE"
		;;
	gemini)
		# Gemini uses stream-json init event, no snapshot needed
		DISPATCH_CORE_SNAPSHOT_FILE=""
		;;
	esac

	# Determine if we should resume
	if [[ $phase_session_mode != "forced_within_phase" ]]; then
		# Not in session mode — fresh execution only
		return 0
	fi

	if [[ $resume_supported != "true" ]]; then
		log_warn "dispatch_core: resume not supported for tool=${tool}; starting fresh"
		return 0
	fi

	# Check for existing baseline session
	local existing_sid=""
	existing_sid=$(session_state_get_phase_tool_session "$task_root" "$phase" "$tool" "session_id" 2>/dev/null || true)
	if [[ -z $existing_sid || $existing_sid == "null" ]]; then
		# No baseline yet — fresh start (not a fallback, baseline hasn't been established)
		log_info "dispatch_core: no baseline session for phase=${phase} tool=${tool}; fresh start"
		return 0
	fi

	# Baseline exists — resume
	DISPATCH_CORE_RESUME_ARG="$existing_sid"
	log_info "dispatch_core: resuming session=${existing_sid} for phase=${phase} tool=${tool} stage=${stage}"
	session_state_record_event "$task_root" "stage_resume" "$phase" "$tool" "$stage" "starting" \
		"session_id=${existing_sid}"
}

# ── Post-stage session management ─────────────────────────────────────────────

# dispatch_core_post_stage <task-root> <phase> <tool> <stage> <sid-out-file> [phase-session-mode]
# Reads session_id from sid-out-file (written by wrapper with --session-id-out).
# Validates against baseline (if forced_within_phase), records event.
dispatch_core_post_stage() {
	local task_root="$1"
	local phase="$2"
	local tool="$3"
	local stage="$4"
	local sid_out_file="$5"
	local phase_session_mode="${6:-${DISPATCH_CORE_DEFAULT_PHASE_SESSION_MODE}}"

	if [[ ! -f $sid_out_file ]]; then
		log_warn "dispatch_core: session_id_out file missing: ${sid_out_file}"
		return 0
	fi

	local new_sid
	new_sid=$(cat "$sid_out_file" 2>/dev/null || echo "")
	if [[ -z $new_sid || $new_sid == "none" ]]; then
		log_warn "dispatch_core: no session_id extracted for phase=${phase} tool=${tool} stage=${stage}"
		if [[ $phase_session_mode == "forced_within_phase" ]]; then
			local existing_sid=""
			existing_sid=$(session_state_get_phase_tool_session "$task_root" "$phase" "$tool" "session_id" 2>/dev/null || true)
			if [[ -n $existing_sid ]]; then
				log_error "dispatch_core: session_id missing after resume (baseline=${existing_sid}); fail-fast"
				session_state_write_recovery \
					"${task_root}/state" "$phase" "$tool" "$stage" \
					"session_id not extracted after forced resume" "$existing_sid" "" ""
				session_state_record_event "$task_root" "stage_failed" "$phase" "$tool" "$stage" "fail_fast" \
					"reason=sid_missing_after_resume"
				return 1
			fi
		fi
		return 0
	fi

	# Determine confidence from probe
	local id_source
	id_source=$(session_state_probe_field "$task_root" "$tool" "id_source" 2>/dev/null || echo "unknown")
	local confidence="medium"
	if [[ $id_source == "stream_json_init" || $id_source == "thread_started" ]]; then
		confidence="high"
	fi

	# Check if baseline already exists
	local existing_sid=""
	existing_sid=$(session_state_get_phase_tool_session "$task_root" "$phase" "$tool" "session_id" 2>/dev/null || true)

	if [[ -n $existing_sid && $phase_session_mode == "forced_within_phase" ]]; then
		# Validate: new session must match baseline
		if [[ $new_sid != "$existing_sid" ]]; then
			log_error "dispatch_core: session mismatch (expected=${existing_sid}, got=${new_sid}); fail-fast"
			session_state_write_recovery \
				"${task_root}/state" "$phase" "$tool" "$stage" \
				"session_id mismatch — context continuity broken" "$existing_sid" "$new_sid" "$existing_sid"
			session_state_record_event "$task_root" "session_mismatch" "$phase" "$tool" "$stage" "fail_fast" \
				"expected=${existing_sid},got=${new_sid}"
			session_state_record_validation_result "$task_root" "$phase" "$tool" "session_mismatch" "false" \
				"expected=${existing_sid},got=${new_sid}"
			return 1
		fi
		# Match: update last_used
		session_state_set_phase_tool_session \
			"$task_root" "$phase" "$tool" "$new_sid" "$id_source" "$confidence" "active"
		session_state_record_event "$task_root" "session_validated" "$phase" "$tool" "$stage" "ok" \
			"session_id=${new_sid}"
	else
		# New baseline
		session_state_set_phase_tool_session \
			"$task_root" "$phase" "$tool" "$new_sid" "$id_source" "$confidence" "baseline"
		session_state_record_event "$task_root" "session_baseline" "$phase" "$tool" "$stage" "ok" \
			"session_id=${new_sid},confidence=${confidence}"
		log_info "dispatch_core: session baseline established for phase=${phase} tool=${tool}: ${new_sid}"
	fi

	return 0
}

# dispatch_core_record_phase_links <task-root> <completed-phase> <task-name>
# Writes/updates state/phase-links.json with canonical artifact paths for completed phase.
# Called from dispatch_core_record_phase_done (only on success status).
dispatch_core_record_phase_links() {
	local task_root="$1"
	local phase="$2"
	local task_name="$3"
	local state_dir="${task_root}/state"
	local links_path="${state_dir}/phase-links.json"

	mkdir -p "$state_dir"

	python3 - "$task_root" "$phase" "$task_name" "$links_path" <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone

task_root, phase, task_name, links_path = sys.argv[1:]
task_root = os.path.abspath(task_root)
links_path = os.path.abspath(links_path)

def resolve_repo_root(path: str) -> str:
    current = os.path.abspath(path)
    while True:
        if os.path.basename(current) == ".tmp":
            return os.path.dirname(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    # Fallback for unexpected layouts.
    return os.path.dirname(os.path.dirname(task_root))

def rel_to_repo(abs_path: str, repo_root: str) -> str:
    return os.path.relpath(os.path.abspath(abs_path), repo_root)

repo_root = resolve_repo_root(task_root)

data = {}
if os.path.isfile(links_path):
    with open(links_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            data = {}

if not isinstance(data, dict):
    data = {}

links = data.get("links")
if not isinstance(links, dict):
    links = {}
data["links"] = links

phase_links = links.get(phase)
if not isinstance(phase_links, dict):
    phase_links = {}

def maybe_set(key: str, path: str) -> None:
    if os.path.isfile(path):
        phase_links[key] = rel_to_repo(path, repo_root)

if phase == "plan":
    maybe_set("final_plan", os.path.join(task_root, "plan", "final-plan.md"))
    maybe_set("preflight", os.path.join(task_root, "plan", "preflight.md"))
elif phase == "impl":
    maybe_set("summary", os.path.join(task_root, "impl", "outputs", "_summary.md"))
    maybe_set("context_pack", os.path.join(task_root, "impl", "inputs", "context_pack.md"))
elif phase == "review":
    final_summary = os.path.join(task_root, "review", "final", "summary.md")
    fallback_summary = os.path.join(task_root, "review", "summary.md")
    if os.path.isfile(final_summary):
        phase_links["summary"] = rel_to_repo(final_summary, repo_root)
    elif os.path.isfile(fallback_summary):
        phase_links["summary"] = rel_to_repo(fallback_summary, repo_root)

if phase_links:
    links[phase] = phase_links

data["task_name"] = task_name
data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

tmp = links_path + ".partial"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp, links_path)
PYEOF
}

# ── Phase completion recording ─────────────────────────────────────────────────

# dispatch_core_record_phase_done <task-root> <run-id> <phase> <status>
# status: success | failed
dispatch_core_record_phase_done() {
	local task_root="$1"
	local run_id="$2"
	local phase="$3"
	local status="$4"

	session_state_record_event "$task_root" "phase_done" "$phase" "none" "none" "$status" \
		"run_id=${run_id}"
	if [[ $status == "success" ]]; then
		dispatch_core_record_phase_links "$task_root" "$phase" "$(basename "$task_root")"
	fi
	session_state_mark_run_status "$task_root" "$run_id" "$status"
	log_info "dispatch_core: phase=${phase} status=${status} run=${run_id}"
}
