#!/usr/bin/env bash
# dispatch.sh — Central entry point for single-stage and pipeline execution
#
# Usage:
#   dispatch.sh single   --task <task-dir> --stage <stage-name>
#   dispatch.sh pipeline --task <task-dir> --plan auto|<plan-name>
#
# Stage name format: <tool>_<role>  (e.g., gemini_brief, codex_impl, copilot_runbook)
#
# Exit codes:
#   0   Success (all stages completed and passed gates)
#   1   Stage failure (gate failed, wrapper error, budget exceeded, etc.)
#   2   Bad arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

source "${SCRIPT_DIR}/lib/log.sh"
source "${SCRIPT_DIR}/lib/manifest.sh"
source "${SCRIPT_DIR}/lib/atomic.sh"
source "${SCRIPT_DIR}/lib/config.sh"

# ── Argument parsing ──────────────────────────────────────────────────────────

SUBCOMMAND="${1-}"
if [[ -z $SUBCOMMAND || ($SUBCOMMAND != "single" && $SUBCOMMAND != "pipeline") ]]; then
	echo "Usage: dispatch.sh <single|pipeline> --task <dir> [--stage <name>] [--plan auto]" >&2
	exit 2
fi
shift

TASK_DIR=""
STAGE_NAME=""
PLAN_NAME="auto"
DISPATCH_TASK_ROOT=""
DISPATCH_PHASE=""
DISPATCH_PHASE_SESSION_MODE=""

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
	--plan)
		PLAN_NAME="$2"
		shift 2
		;;
	--task-root)
		DISPATCH_TASK_ROOT="$2"
		shift 2
		;;
	--phase)
		DISPATCH_PHASE="$2"
		shift 2
		;;
	--phase-session-mode)
		DISPATCH_PHASE_SESSION_MODE="$2"
		shift 2
		;;
	*)
		log_warn "Unknown argument: $1"
		shift
		;;
	esac
done

if [[ -z $TASK_DIR ]]; then
	log_error "Missing --task argument"
	exit 2
fi

if [[ $SUBCOMMAND == "single" && -z $STAGE_NAME ]]; then
	log_error "single mode requires --stage"
	exit 2
fi

MANIFEST="${TASK_DIR}/manifest.yaml"
if [[ ! -f $MANIFEST ]]; then
	log_error "manifest.yaml not found: ${MANIFEST}"
	exit 2
fi

if [[ -n $DISPATCH_TASK_ROOT ]]; then
	source "${SCRIPT_DIR}/lib/dispatch_core.sh"
	if [[ -z $DISPATCH_PHASE_SESSION_MODE ]]; then
		DISPATCH_PHASE_SESSION_MODE="${DISPATCH_CORE_DEFAULT_PHASE_SESSION_MODE}"
	fi
fi

# ── Manifest readers ──────────────────────────────────────────────────────────

get_manifest() { manifest_get "$MANIFEST" "$1" 2>/dev/null; }
require_manifest() { manifest_require "$MANIFEST" "$1" "$2"; }

TASK_ID=$(require_manifest "task_id" "task_id")
RETRY_BUDGET=$(get_manifest "budgets.retry_budget" || echo "2")
PAID_CALL_BUDGET=$(get_manifest "budgets.paid_call_budget" || echo "10")
ROUTING_INTENT=$(get_manifest "routing.intent" || echo "safe_impl")

STATE_DIR="${TASK_DIR}/state"
STATS_FILE="${STATE_DIR}/stats.json"
OUTPUTS_DIR="${TASK_DIR}/outputs"
INPUTS_DIR="${TASK_DIR}/inputs"
DONE_DIR="${TASK_DIR}/done"
PROMPTS_SRC="${REPO_ROOT}/prompts-src"

mkdir -p "$OUTPUTS_DIR" "$DONE_DIR" "$STATE_DIR"

DISPATCH_RESOLVED_FILE="${STATE_DIR}/config.dispatch.resolved.json"
if ! resolve_dispatch_config "$MANIFEST" "$PLAN_NAME" "$ROUTING_INTENT" "$DISPATCH_RESOLVED_FILE"; then
	log_error "Failed to resolve dispatch config from split files under: $(config_root_dir)"
	exit 1
fi

RESOLVED_INTENT=$(config_json_get "$DISPATCH_RESOLVED_FILE" "intent" 2>/dev/null || echo "$ROUTING_INTENT")
RESOLVED_PROFILE=$(config_json_get "$DISPATCH_RESOLVED_FILE" "profile" 2>/dev/null || echo "unknown")
RESOLVED_PIPELINE_GROUP=$(config_json_get "$DISPATCH_RESOLVED_FILE" "pipeline_group" 2>/dev/null || echo "unknown")

resolved_stage_plan() {
	config_json_get_lines "$DISPATCH_RESOLVED_FILE" "stage_plan"
}

# ── Tool/Role extraction from stage name ─────────────────────────────────────

stage_tool() { echo "$1" | cut -d_ -f1; }
stage_role() { echo "$1" | cut -d_ -f2-; }

# ── Wrapper selector ──────────────────────────────────────────────────────────

wrapper_for_tool() {
	local tool="$1"
	case "$tool" in
	gemini) echo "${SCRIPT_DIR}/wrappers/gemini_headless.sh" ;;
	codex) echo "${SCRIPT_DIR}/wrappers/run_codex.sh" ;;
	copilot) echo "${SCRIPT_DIR}/wrappers/copilot_tool.sh" ;;
	*)
		log_error "Unknown tool: ${tool}"
		exit 1
		;;
	esac
}

resolve_prompt_template() {
	local tool="$1"
	local role="$2"
	local default_template="${PROMPTS_SRC}/${tool}/${role}.md"
	local phase_key="${DISPATCH_PHASE:-${RESOLVED_PIPELINE_GROUP-}}"
	local task_root=""
	local candidate=""

	if [[ -n ${DISPATCH_TASK_ROOT-} ]]; then
		task_root="$DISPATCH_TASK_ROOT"
	elif [[ $(basename "$TASK_DIR") =~ ^(plan|impl|review)$ ]]; then
		task_root="$(cd "${TASK_DIR}/.." && pwd)"
	fi

	# 1) Task override
	if [[ -n $task_root && -n $phase_key && $phase_key != "unknown" ]]; then
		candidate="${task_root}/prompts/${phase_key}/${tool}/${role}.md"
		if [[ -f $candidate ]]; then
			echo "$candidate"
			return 0
		fi
	fi

	# 2) Profile override
	if [[ -n $phase_key && $phase_key != "unknown" && -n ${RESOLVED_PROFILE-} && $RESOLVED_PROFILE != "unknown" ]]; then
		candidate="${PROMPTS_SRC}/profiles/${phase_key}/${RESOLVED_PROFILE}/${tool}/${role}.md"
		if [[ -f $candidate ]]; then
			echo "$candidate"
			return 0
		fi
	fi

	# 3) Default template
	echo "$default_template"
	return 0
}

resolve_model_for_stage() {
	local stage="$1"
	local tool="$2"

	local stage_model=""
	stage_model=$(config_json_get "$DISPATCH_RESOLVED_FILE" "stage_models.${stage}" 2>/dev/null || true)
	if [[ -n $stage_model ]]; then
		echo "$stage_model"
		return 0
	fi

	local tool_model=""
	tool_model=$(config_json_get "$DISPATCH_RESOLVED_FILE" "tool_models.${tool}" 2>/dev/null || true)
	if [[ -n $tool_model ]]; then
		echo "$tool_model"
		return 0
	fi

	log_error "Resolved config missing model for stage='${stage}' tool='${tool}'"
	exit 1
}

resolve_effort_for_stage() {
	local stage="$1"
	local effort=""
	effort=$(config_json_get "$DISPATCH_RESOLVED_FILE" "stage_efforts.${stage}" 2>/dev/null || true)
	if [[ -n $effort ]]; then
		echo "$effort"
		return 0
	fi
	log_error "Resolved config missing codex effort for stage='${stage}'"
	exit 1
}

manifest_timeout_ms() {
	local sec=""
	sec=$(get_manifest "budgets.max_wallclock_sec" 2>/dev/null || true)
	if [[ -n $sec && $sec =~ ^[0-9]+$ ]]; then
		echo $((sec * 1000))
		return 0
	fi
	echo ""
}

resolve_timeout_ms_for_stage() {
	local stage="$1"

	# Environment override from dispatch_impl.sh / dispatch_plan.sh
	if [[ -n ${DISPATCH_TIMEOUT_MS_OVERRIDE-} ]]; then
		echo "$DISPATCH_TIMEOUT_MS_OVERRIDE"
		return 0
	fi

	local manifest_ms=""
	manifest_ms=$(manifest_timeout_ms)
	if [[ -n $manifest_ms ]]; then
		echo "$manifest_ms"
		return 0
	fi

	local stage_timeout_ms=""
	stage_timeout_ms=$(config_json_get "$DISPATCH_RESOLVED_FILE" "stage_timeout_ms.${stage}" 2>/dev/null || true)
	if [[ -n $stage_timeout_ms ]]; then
		echo "$stage_timeout_ms"
		return 0
	fi

	log_error "Resolved config missing timeout_ms for stage='${stage}'"
	exit 1
}

resolve_timeout_mode_for_stage() {
	local stage="$1"
	local mode=""
	mode=$(config_json_get "$DISPATCH_RESOLVED_FILE" "stage_timeout_modes.${stage}" 2>/dev/null || true)
	if [[ $mode == "enforce" || $mode == "wait_done" ]]; then
		echo "$mode"
		return 0
	fi
	log_error "Resolved config missing/invalid timeout_mode for stage='${stage}'"
	exit 1
}

# ── Budget check ──────────────────────────────────────────────────────────────

check_paid_budget() {
	local used=0
	if [[ -f $STATS_FILE ]]; then
		used=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('paid_calls_used',0))" 2>/dev/null || echo "0")
	fi
	if ((used >= PAID_CALL_BUDGET)); then
		log_error "paid_call_budget exhausted (${used}/${PAID_CALL_BUDGET}). Stop."
		exit 1
	fi
}

increment_paid_calls() {
	python3 - "$STATS_FILE" <<'PYEOF'
import json, os, sys
f = sys.argv[1]
os.makedirs(os.path.dirname(os.path.abspath(f)), exist_ok=True)
data = {}
if os.path.isfile(f):
    with open(f) as fp:
        try: data = json.load(fp)
        except: pass
data.setdefault('paid_calls_used', 0)
data['paid_calls_used'] += 1
p = f + '.partial'
with open(p,'w') as fp: json.dump(data, fp, indent=2)
os.replace(p, f)
PYEOF
}

mark_stage_completed() {
	local stage="$1"
	python3 - "$STATS_FILE" "$stage" <<'PYEOF'
import json, os, sys
f, stage = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(os.path.abspath(f)), exist_ok=True)
data = {}
if os.path.isfile(f):
    with open(f) as fp:
        try: data = json.load(fp)
        except: pass
data.setdefault('stages_completed', [])
if stage not in data['stages_completed']:
    data['stages_completed'].append(stage)
p = f + '.partial'
with open(p,'w') as fp: json.dump(data, fp, indent=2)
os.replace(p, f)
PYEOF
}

get_signature_count() {
	local signature="$1"
	python3 - "$STATS_FILE" "$signature" <<'PYEOF' 2>/dev/null || echo "0"
import json, sys
f, sig = sys.argv[1], sys.argv[2]
if not __import__('os').path.isfile(f): print(0); exit()
with open(f) as fp:
    try: d = json.load(fp)
    except: print(0); exit()
print(d.get('signatures', {}).get(sig, {}).get('count', 0))
PYEOF
}

# ── Summary generator (writes _summary.md) ───────────────────────────────────

generate_summary() {
	local completed_stages=("$@")
	local summary_file="${OUTPUTS_DIR}/_summary.md"
	local summary_partial="${summary_file}.partial"

	{
		echo "# Task Summary"
		echo "Task: ${TASK_ID}"
		echo "Updated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
		echo ""
		echo "## Stages"
		echo ""

		for stage in "${completed_stages[@]}"; do
			local tool role done_file meta_file out_file err_file
			tool=$(stage_tool "$stage")
			role=$(stage_role "$stage")
			done_file="${DONE_DIR}/${stage}.done"
			meta_file="${OUTPUTS_DIR}/${stage}.${tool}.meta.json"
			out_file="${OUTPUTS_DIR}/${stage}.${tool}.out"
			err_file="${OUTPUTS_DIR}/${stage}.${tool}.err"

			local status="pending"
			[[ -f $done_file ]] && status="done"

			echo "### ${stage} (${tool}/${role}) — ${status}"

			if [[ -f $meta_file ]]; then
				local exit_code duration
				exit_code=$(python3 -c "import json; print(json.load(open('$meta_file')).get('exit_code','?'))" 2>/dev/null || echo "?")
				duration=$(python3 -c "import json; print(json.load(open('$meta_file')).get('duration_sec','?'))" 2>/dev/null || echo "?")
				echo "- exit_code: ${exit_code} | duration: ${duration}s"
			fi

			if [[ -f $err_file && -s $err_file ]]; then
				echo ""
				echo "**stderr (head 20 + tail 20):**"
				echo '```'
				trim_log "$err_file" 20 20
				echo '```'
			fi

			if [[ -f $out_file && -s $out_file ]]; then
				local out_lines
				out_lines=$(wc -l <"$out_file" | tr -d ' ')
				echo "- output: ${out_lines} lines"
			fi
			echo ""
		done

		# Last failure
		local last_failure="${TASK_DIR}/state/last_failure.json"
		if [[ -f $last_failure ]]; then
			echo "## Last Failure"
			echo '```json'
			cat "$last_failure"
			echo '```'
			echo ""
		fi

		# Stats
		if [[ -f $STATS_FILE ]]; then
			local paid_calls
			paid_calls=$(python3 -c "import json; print(json.load(open('$STATS_FILE')).get('paid_calls_used',0))" 2>/dev/null || echo "?")
			echo "## Budgets"
			echo "- paid_calls_used: ${paid_calls} / ${PAID_CALL_BUDGET}"
			echo ""
		fi

	} >"$summary_partial"

	# Truncate to 80 lines
	local total_lines
	total_lines=$(wc -l <"$summary_partial" | tr -d ' ')
	if ((total_lines > 80)); then
		head -n 80 "$summary_partial" >"${summary_partial}.trunc"
		echo "... [$((total_lines - 80)) lines truncated] ..." >>"${summary_partial}.trunc"
		mv "${summary_partial}.trunc" "$summary_partial"
	fi

	atomic_write "$summary_partial" "$summary_file"
}

# ── Write last_failure.json ───────────────────────────────────────────────────

write_last_failure() {
	local triage_json="$1"
	local last_failure="${TASK_DIR}/state/last_failure.json"
	echo "$triage_json" >"${last_failure}.partial"
	atomic_write "${last_failure}.partial" "$last_failure"
}

print_log_excerpt() {
	local file="$1"
	local lines="${2:-20}"
	[[ -s $file ]] || return 0
	log_warn "Log excerpt ($(basename "$file"), last ${lines} lines):"
	tail -n "$lines" "$file" >&2 || true
}

run_silent_with_progress() {
	local label="$1"
	local log_file="$2"
	shift 2

	local progress_interval="${AGENT_CLI_PROGRESS_INTERVAL_SEC:-10}"
	ensure_dir "$log_file"
	: >"$log_file"

	"$@" >"$log_file" 2>&1 &
	local pid=$!
	local elapsed=0

	log_info "${label}: started"
	while kill -0 "$pid" 2>/dev/null; do
		sleep 1
		elapsed=$((elapsed + 1))
		if ((progress_interval > 0)) && ((elapsed % progress_interval == 0)); then
			log_info "${label}: running (${elapsed}s)"
		fi
	done

	local exit_code=0
	wait "$pid" || exit_code=$?

	if [[ $exit_code -eq 0 ]]; then
		log_ok "${label}: completed (${elapsed}s)"
	else
		log_error "${label}: failed (exit=${exit_code})"
	fi

	return $exit_code
}

tools_csv_from_stages() {
	local csv=""
	local stage tool
	for stage in "$@"; do
		tool=$(stage_tool "$stage")
		if [[ ",${csv}," != *",${tool},"* ]]; then
			csv="${csv:+${csv},}${tool}"
		fi
	done
	echo "$csv"
}

preflight_for_tools() {
	local tools_csv="$1"
	local preflight_log="${STATE_DIR}/preflight.log"
	run_silent_with_progress "Preflight (${tools_csv})" "$preflight_log" \
		"${SCRIPT_DIR}/preflight.sh" --quick --tools "$tools_csv" || {
		log_error "Preflight failed for tools: ${tools_csv}"
		print_log_excerpt "$preflight_log" 40
		return 1
	}
}

prepare_review_consolidate_attachments() {
	local stage="$1"
	local attach_dir="${STATE_DIR}/${stage}.attachments"
	rm -rf "$attach_dir"
	mkdir -p "$attach_dir"

	if [[ -d "${INPUTS_DIR}/attachments" ]]; then
		cp -f "${INPUTS_DIR}/attachments/"* "$attach_dir/" 2>/dev/null || true
	fi

	local review_outputs=(
		"${OUTPUTS_DIR}/gemini_review.gemini.out:gemini_review.md"
		"${OUTPUTS_DIR}/gemini_test_design.gemini.out:test_matrix.md"
		"${OUTPUTS_DIR}/gemini_static_verify.gemini.out:verification_checklist.md"
		"${OUTPUTS_DIR}/codex_review.codex.out:codex_review.md"
		"${OUTPUTS_DIR}/codex_test_impl.codex.out:test_implementation_report.md"
		"${OUTPUTS_DIR}/codex_verify.codex.out:verification_report.md"
		"${OUTPUTS_DIR}/codex_verify.artifact.md:verification_gate_artifact.md"
		"${OUTPUTS_DIR}/copilot_review.copilot.out:copilot_review.md"
	)

	local entry src dst
	for entry in "${review_outputs[@]}"; do
		src="${entry%%:*}"
		dst="${entry##*:}"
		if [[ -s $src ]]; then
			cp -f "$src" "${attach_dir}/${dst}"
		fi
	done

	echo "$attach_dir"
}

sync_context_from_brief() {
	local brief_output_file="$1"
	local context_file="${INPUTS_DIR}/context_pack.md"
	local sync_status

	sync_status=$(
		python3 - "$brief_output_file" "$context_file" <<'PYEOF'
import os
import re
import sys

brief_output_file = sys.argv[1]
context_file = sys.argv[2]

with open(brief_output_file, "r", encoding="utf-8", errors="replace") as f:
    text = f.read()

lines = text.splitlines()
start = None

for i, line in enumerate(lines):
    if re.match(r"^##\s+Updated Context Pack\s*$", line, flags=re.IGNORECASE):
        start = i + 1
        break

if start is None:
    print("missing-section")
    sys.exit(0)

tail = lines[start:]
context = []
in_context = False

for line in tail:
    m = re.match(r"^##\s+(.+?)\s*$", line)
    if m:
        heading = m.group(1).strip()
        if re.match(r"^\d+\.\s+", heading):
            in_context = True
            context.append(line)
            continue
        if in_context:
            break
    if in_context:
        context.append(line)

while context and context[0].strip() == "":
    context.pop(0)
while context and context[-1].strip() == "":
    context.pop()

if not context:
    print("empty-section")
    sys.exit(0)

content = "\n".join(context) + "\n"
if not re.search(r"^##\s+\d+\.\s+", content, flags=re.MULTILINE):
    print("invalid-content")
    sys.exit(0)

os.makedirs(os.path.dirname(os.path.abspath(context_file)), exist_ok=True)
partial = context_file + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    f.write(content)
os.replace(partial, context_file)
print("updated")
PYEOF
	)

	case "$sync_status" in
	updated)
		log_ok "Updated inputs/context_pack.md from brief output"
		;;
	missing-section)
		log_warn "brief output has no '## Updated Context Pack' section; context not updated"
		;;
	empty-section | invalid-content)
		log_warn "brief output context section is invalid; context not updated"
		;;
	*)
		log_warn "brief context sync returned unexpected status: ${sync_status}"
		;;
	esac
}

sync_verify_commands_from_brief() {
	local brief_output_file="$1"
	local override_file="${TASK_DIR}/state/acceptance.commands.override"
	local sync_status

	sync_status=$(
		python3 - "$brief_output_file" "$override_file" <<'PYEOF'
import os
import re
import sys

brief_output_file = sys.argv[1]
override_file = sys.argv[2]

with open(brief_output_file, "r", encoding="utf-8", errors="replace") as f:
    lines = f.read().splitlines()

in_verify_section = False
in_code_block = False
commands = []
fence = chr(96) * 3

for line in lines:
    heading = re.match(r"^##\s+(.+?)\s*$", line)
    if heading:
        title = heading.group(1).strip().lower()
        if title == "verify commands":
            in_verify_section = True
            in_code_block = False
            continue
        if in_verify_section and not in_code_block:
            break
    if not in_verify_section:
        continue

    if line.strip().startswith(fence):
        if not in_code_block:
            in_code_block = True
            continue
        break

    if in_code_block and line.strip():
        commands.append(line.strip())

if commands:
    os.makedirs(os.path.dirname(os.path.abspath(override_file)), exist_ok=True)
    partial = override_file + ".partial"
    with open(partial, "w", encoding="utf-8") as f:
        f.write("\n".join(commands) + "\n")
    os.replace(partial, override_file)
    print("updated")
else:
    if os.path.exists(override_file):
        os.remove(override_file)
    print("cleared")
PYEOF
	)

	case "$sync_status" in
	updated)
		log_ok "Updated acceptance command override from brief output"
		;;
	cleared)
		log_info "No Verify Commands block found in brief output; acceptance override cleared"
		;;
	*)
		log_warn "brief verify-command sync returned unexpected status: ${sync_status}"
		;;
	esac
}

# ── Run a single stage ────────────────────────────────────────────────────────

run_stage() {
	local stage="$1"
	local force_digest_policy="${2-}"

	local tool role wrapper template_file prompt_file out_file err_file meta_file done_file
	tool=$(stage_tool "$stage")
	role=$(stage_role "$stage")
	wrapper=$(wrapper_for_tool "$tool")
	template_file="$(resolve_prompt_template "$tool" "$role")"
	prompt_file="${INPUTS_DIR}/prompt/${tool}.${role}.md"
	out_file="${OUTPUTS_DIR}/${stage}.${tool}.out"
	err_file="${OUTPUTS_DIR}/${stage}.${tool}.err"
	meta_file="${OUTPUTS_DIR}/${stage}.${tool}.meta.json"
	done_file="${DONE_DIR}/${stage}.done"

	# Idempotency: skip if already done
	if [[ -f $done_file ]]; then
		log_info "Stage ${stage}: already done, skipping"
		return 0
	fi

	# Budget check before paid call
	check_paid_budget

	# Template existence check
	if [[ ! -f $template_file ]]; then
		log_error "Prompt template not found: ${template_file}"
		log_error "Create one of:"
		log_error "  - prompts-src/${tool}/${role}.md"
		log_error "  - prompts-src/profiles/<phase>/<profile>/${tool}/${role}.md"
		log_error "  - .tmp/task/<task-name>/prompts/<phase>/${tool}/${role}.md"
		exit 1
	fi

	# Ensure context pack exists (allow empty)
	local context_file="${INPUTS_DIR}/context_pack.md"
	if [[ ! -f $context_file ]]; then
		touch "$context_file"
	fi

	# Apply forced digest policy (from retry policy)
	local manifest_digest
	manifest_digest=$(get_manifest "context.digest_policy" || echo "off")
	if [[ -n $force_digest_policy ]]; then
		manifest_digest="$force_digest_policy"
		log_info "Stage ${stage}: digest_policy overridden to '${force_digest_policy}'"
	fi

	# Copilot always uses aggressive digest (arg size limit)
	if [[ $tool == "copilot" && $manifest_digest != "aggressive" ]]; then
		manifest_digest="aggressive"
		log_info "Stage ${stage}: Copilot requires aggressive digest (50KB limit)"
	fi

	# Compose prompt
	mkdir -p "${INPUTS_DIR}/prompt"
	local compose_log="${OUTPUTS_DIR}/${stage}.${tool}.compose.log"
	local prompt_sha_file="${OUTPUTS_DIR}/${stage}.${tool}.prompt_sha256"
	local compose_cmd=(
		"${SCRIPT_DIR}/compose_prompt.sh"
		--template "$template_file"
		--user "${INPUTS_DIR}/user_request.md"
		--context "$context_file"
		--manifest "$MANIFEST"
		--out "$prompt_file"
		--digest-policy "$manifest_digest"
		--sha-out "$prompt_sha_file"
	)
	local compose_args=(
		"${compose_cmd[@]}"
	)
	local compose_attachments_dir="${INPUTS_DIR}/attachments"
	if [[ $role == "review_consolidate" ]]; then
		compose_attachments_dir=$(prepare_review_consolidate_attachments "$stage")
	fi
	if [[ -d $compose_attachments_dir ]]; then
		compose_args+=(--attachments-dir "$compose_attachments_dir")
	fi
	run_silent_with_progress "Stage ${stage}: compose prompt" "$compose_log" "${compose_args[@]}" || {
		log_error "compose_prompt failed for stage ${stage}"
		print_log_excerpt "$compose_log" 40
		exit 1
	}
	local prompt_sha256=""
	if [[ -f $prompt_sha_file ]]; then
		prompt_sha256=$(cat "$prompt_sha_file" 2>/dev/null || echo "")
	fi

	# Record start time
	local start_epoch
	start_epoch=$(epoch_now)

	# Run wrapper
	local wrapper_log="${OUTPUTS_DIR}/${stage}.${tool}.wrapper.log"
	local model
	model=$(resolve_model_for_stage "$stage" "$tool")
	local stage_timeout_ms
	stage_timeout_ms=$(resolve_timeout_ms_for_stage "$stage")
	local stage_timeout_mode
	stage_timeout_mode=$(resolve_timeout_mode_for_stage "$stage")
	local codex_effort=""
	if [[ $tool == "codex" ]]; then
		codex_effort=$(resolve_effort_for_stage "$stage")
	fi
	local sid_out=""
	local dispatch_core_resume_arg=""
	local dispatch_core_snapshot_file=""
	if [[ -n ${DISPATCH_TASK_ROOT-} && -n ${DISPATCH_PHASE-} ]]; then
		sid_out="${OUTPUTS_DIR}/${stage}.${tool}.sid.out"
		rm -f "$sid_out"
		dispatch_core_pre_stage \
			"$DISPATCH_TASK_ROOT" "$DISPATCH_PHASE" "$tool" "$stage" \
			"${DISPATCH_PHASE_SESSION_MODE:-forced_within_phase}"
		dispatch_core_resume_arg="${DISPATCH_CORE_RESUME_ARG-}"
		dispatch_core_snapshot_file="${DISPATCH_CORE_SNAPSHOT_FILE-}"
	fi

	local wrapper_cmd=(
		"$wrapper"
		--prompt-file "$prompt_file"
		--out "$out_file"
		--err "$err_file"
		--model "$model"
		--timeout-ms "$stage_timeout_ms"
		--timeout-mode "$stage_timeout_mode"
	)
	if [[ $tool == "codex" ]]; then
		wrapper_cmd+=(--effort "$codex_effort")
	fi
	if [[ -n $sid_out ]]; then
		wrapper_cmd+=(--session-id-out "$sid_out")
	fi
	if [[ -n $dispatch_core_resume_arg ]]; then
		wrapper_cmd+=(--resume-session "$dispatch_core_resume_arg")
	fi
	if [[ -n $dispatch_core_snapshot_file ]]; then
		wrapper_cmd+=(--snapshot-file "$dispatch_core_snapshot_file")
	fi

	local wrapper_exit=0
	run_silent_with_progress "Stage ${stage}: run ${tool}" "$wrapper_log" "${wrapper_cmd[@]}" || wrapper_exit=$?
	if [[ $wrapper_exit -ne 0 ]]; then
		print_log_excerpt "$wrapper_log" 40
	fi

	local end_epoch
	end_epoch=$(epoch_now)

	# Write meta.json (always — even on failure)
	write_meta_json "$meta_file" "$stage" "$tool" "$wrapper_exit" \
		"$start_epoch" "$end_epoch" "$prompt_sha256"

	# Increment paid call counter (called even on failure — we still spent a call)
	increment_paid_calls

	if [[ $wrapper_exit -eq 0 && -n ${DISPATCH_TASK_ROOT-} && -n ${DISPATCH_PHASE-} && -n $sid_out ]]; then
		dispatch_core_post_stage \
			"$DISPATCH_TASK_ROOT" "$DISPATCH_PHASE" "$tool" "$stage" "$sid_out" \
			"${DISPATCH_PHASE_SESSION_MODE:-forced_within_phase}" || {
			log_error "Session mismatch — fail-fast"
			return 1
		}
	fi

	# Gate check
	local gate_result="pass"
	local gate_exit=0
	local gate_output=""
	local gate_result_file="${OUTPUTS_DIR}/${stage}.gate_result.json"
	if [[ $wrapper_exit -eq 0 ]]; then
		gate_output=$("${SCRIPT_DIR}/gate.sh" \
			--task "$TASK_DIR" \
			--stage "$stage" \
			--role "$role" \
			--gate-result-out "$gate_result_file" 2>/dev/null) || gate_exit=$?

		if [[ $gate_exit -ne 0 ]]; then
			gate_result="contract_violation"
			if echo "$gate_output" | grep -qi "scope violation"; then
				gate_result="scope_violation"
			fi
			log_warn "Stage ${stage}: gate failed"
			log_warn "$gate_output"
		fi
	fi

	# If wrapper or gate failed: triage
	if [[ $wrapper_exit -ne 0 || $gate_exit -ne 0 ]]; then
		log_error "Stage ${stage}: FAILED (wrapper_exit=${wrapper_exit} gate_exit=${gate_exit})"

		local triage_json
		triage_json=$("${SCRIPT_DIR}/triage_error.sh" \
			--exit-code "$wrapper_exit" \
			--stderr "$err_file" \
			--gate-result "$gate_result" \
			--stats "$STATS_FILE" 2>/dev/null || echo '{"class":"unknown","signature":"unknown","exit_code":'"$wrapper_exit"',"suggested_actions":[]}')

		write_last_failure "$triage_json"

		local error_class signature count
		error_class=$(echo "$triage_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('class','unknown'))" 2>/dev/null || echo "unknown")
		signature=$(echo "$triage_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('signature','unknown'))" 2>/dev/null || echo "unknown")

		# Autonomous retry policy
		case "$error_class" in
		auth)
			log_error "Auth failure — no auto-retry. Re-authenticate and try again."
			return 1
			;;
		transient)
			count=$(get_signature_count "$signature")
			local retry_budget_remaining=$((RETRY_BUDGET - count))
			if ((retry_budget_remaining > 0)); then
				log_warn "Transient error (count=${count}) — retrying once"
				sleep 5
				run_stage "$stage" "$force_digest_policy"
				return $?
			else
				log_error "Transient error exceeded retry budget (${RETRY_BUDGET})"
				return 1
			fi
			;;
		prompt_too_large)
			count=$(get_signature_count "$signature")
			if [[ $force_digest_policy != "aggressive" ]]; then
				log_warn "prompt_too_large (count=${count}) — retrying with aggressive digest"
				run_stage "$stage" "aggressive"
				return $?
			fi
			log_error "prompt_too_large persists with aggressive digest (count=${count})"
			return 1
			;;
		contract_violation)
			count=$(get_signature_count "$signature")
			if ((count >= 2)); then
				log_error "contract_violation x${count} — tool rerouting not yet automated, manual intervention needed"
				return 1
			fi
			log_error "contract_violation — check gate requirements vs prompt template"
			return 1
			;;
		tooling)
			log_error "Tooling error — run preflight.sh and check installations"
			return 1
			;;
		*)
			log_error "Error class: ${error_class} — stopping"
			return 1
			;;
		esac
	fi

	# Success: write done-marker and update stats
	if [[ $role == "brief" ]]; then
		sync_context_from_brief "$out_file"
		sync_verify_commands_from_brief "$out_file"
	fi
	write_done_marker "$done_file"
	mark_stage_completed "$stage"
	log_ok "Stage ${stage}: DONE"
	return 0
}

# ── Subcommand: single ────────────────────────────────────────────────────────

cmd_single() {
	log_info "dispatch single: task=${TASK_ID} stage=${STAGE_NAME}"
	local tools_csv
	tools_csv=$(tools_csv_from_stages "$STAGE_NAME")
	preflight_for_tools "$tools_csv" || return 1
	local stage_exit=0
	run_stage "$STAGE_NAME" || stage_exit=$?
	generate_summary "$STAGE_NAME"
	return $stage_exit
}

# ── Subcommand: pipeline ──────────────────────────────────────────────────────

cmd_pipeline() {
	log_info "dispatch pipeline: task=${TASK_ID} intent=${RESOLVED_INTENT} profile=${RESOLVED_PROFILE} group=${RESOLVED_PIPELINE_GROUP}"

	local stage_plan_str=""
	STAGE_PLAN=()
	while IFS= read -r _line; do
		STAGE_PLAN+=("$_line")
	done < <(resolved_stage_plan)
	if [[ ${#STAGE_PLAN[@]} -eq 0 ]]; then
		log_error "Resolved stage plan is empty"
		exit 1
	fi
	stage_plan_str="${STAGE_PLAN[*]}"
	log_info "Stage plan: ${stage_plan_str}"
	local tools_csv
	tools_csv=$(tools_csv_from_stages "${STAGE_PLAN[@]}")
	preflight_for_tools "$tools_csv" || exit 1

	local completed_stages=()
	for stage in "${STAGE_PLAN[@]}"; do
		completed_stages+=("$stage")
		local stage_exit=0
		run_stage "$stage" || stage_exit=$?
		generate_summary "${completed_stages[@]}"
		if [[ $stage_exit -ne 0 ]]; then
			log_error "Pipeline stopped at stage: ${stage}"
			exit 1
		fi
	done

	log_ok "Pipeline complete: ${TASK_ID} (${#STAGE_PLAN[@]} stages)"
	exit 0
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

log_info "=== dispatch.sh: ${SUBCOMMAND} | task=$(basename "$TASK_DIR") ==="

case "$SUBCOMMAND" in
single) cmd_single ;;
pipeline) cmd_pipeline ;;
esac
