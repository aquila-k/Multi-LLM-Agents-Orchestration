#!/usr/bin/env bash
# run_plan_pipeline.sh — Execute cross-review planning pipeline (Stage 0-4)
#
# Usage:
#   run_plan_pipeline.sh --task-dir .tmp/plan-pipeline [options]
#
# Required input:
#   <task-dir>/preflight.md
#
# Outputs:
#   <task-dir>/draft.md
#   <task-dir>/codex-enrich.md
#   <task-dir>/gemini-enrich.md
#   <task-dir>/gemini-review-of-codex.md
#   <task-dir>/codex-review-of-gemini.md
#   <task-dir>/final.md
#
# Exit codes:
#   0  Success
#   1  Failure (missing input, wrapper failure, timeout, or quality gate failure)
#   2  Bad arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WRAPPER_DIR="${SCRIPT_DIR}/wrappers"
SKILL_DIR="${REPO_ROOT}/.claude/skills/agent-collab"

source "${SCRIPT_DIR}/lib/log.sh"
source "${SCRIPT_DIR}/lib/atomic.sh"
source "${SCRIPT_DIR}/lib/config.sh"

TASK_DIR=".tmp/plan-pipeline"
TIMEOUT_MS_OVERRIDE=""
COPILOT_MODEL=""
GEMINI_MODEL=""
CODEX_MODEL=""
COPILOT_MODEL_OVERRIDE=""
GEMINI_MODEL_OVERRIDE=""
CODEX_MODEL_OVERRIDE=""
PLAN_PROFILE=""
SKIP_PREFLIGHT=false

MIN_DRAFT_LINES=30
MIN_ENRICH_LINES=30
MIN_REVIEW_LINES=12
MIN_FINAL_LINES=60
STAGE4_ARTIFACT_CAP_LINES=300

usage() {
	cat <<'EOF'
Usage: run_plan_pipeline.sh --task-dir <dir> [options]

Options:
  --task-dir <dir>           Task working directory (default: .tmp/plan-pipeline)
  --timeout-ms <ms>          Override timeout (ms) for all stages. 0 means no hard timeout.
  --profile <name>           Plan pipeline profile name in configs/pipeline/plan-pipeline.yaml
  --copilot-model <model>    Copilot model override (validated against config)
  --gemini-model <model>     Gemini model override (validated against config)
  --codex-model <model>      Codex model override (validated against config)
  --skip-preflight           Skip CLI dependency checks
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--task-dir)
		TASK_DIR="$2"
		shift 2
		;;
	--timeout-ms)
		TIMEOUT_MS_OVERRIDE="$2"
		shift 2
		;;
	--profile)
		PLAN_PROFILE="$2"
		shift 2
		;;
	--copilot-model)
		COPILOT_MODEL_OVERRIDE="$2"
		shift 2
		;;
	--gemini-model)
		GEMINI_MODEL_OVERRIDE="$2"
		shift 2
		;;
	--codex-model)
		CODEX_MODEL_OVERRIDE="$2"
		shift 2
		;;
	--skip-preflight)
		SKIP_PREFLIGHT=true
		shift
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		log_error "Unknown argument: $1"
		usage
		exit 2
		;;
	esac
done

if [[ -n $TIMEOUT_MS_OVERRIDE && ! $TIMEOUT_MS_OVERRIDE =~ ^[0-9]+$ ]]; then
	log_error "--timeout-ms must be a non-negative integer (got: ${TIMEOUT_MS_OVERRIDE})"
	exit 2
fi

mkdir -p "$TASK_DIR"

PREFLIGHT_FILE="${TASK_DIR}/preflight.md"
DRAFT_FILE="${TASK_DIR}/draft.md"
CODEX_ENRICH_FILE="${TASK_DIR}/codex-enrich.md"
GEMINI_ENRICH_FILE="${TASK_DIR}/gemini-enrich.md"
GEMINI_REVIEW_FILE="${TASK_DIR}/gemini-review-of-codex.md"
CODEX_REVIEW_FILE="${TASK_DIR}/codex-review-of-gemini.md"
STAGE4_INPUT_FILE="${TASK_DIR}/stage4-input.md"
FINAL_FILE="${TASK_DIR}/final.md"

PLAN_RESOLVED_FILE="${TASK_DIR}/config.plan.resolved.json"
if ! resolve_plan_pipeline_config \
	"$PLAN_RESOLVED_FILE" \
	"$PLAN_PROFILE" \
	"$COPILOT_MODEL_OVERRIDE" \
	"$GEMINI_MODEL_OVERRIDE" \
	"$CODEX_MODEL_OVERRIDE"; then
	log_error "Failed to resolve plan pipeline config from split files under: $(config_root_dir)"
	exit 1
fi

plan_cfg_get() {
	local key="$1"
	config_json_get "$PLAN_RESOLVED_FILE" "$key" 2>/dev/null || true
}

require_plan_cfg() {
	local key="$1"
	local label="$2"
	local value=""
	value="$(plan_cfg_get "$key")"
	if [[ -z $value ]]; then
		log_error "Resolved plan config missing ${label} (${key})"
		exit 1
	fi
	echo "$value"
}

require_plan_cfg_bool() {
	local key="$1"
	local label="$2"
	local value=""
	value="$(require_plan_cfg "$key" "$label")"
	if [[ $value != "true" && $value != "false" ]]; then
		log_error "Resolved plan config has invalid boolean ${label}=${value} (${key})"
		exit 1
	fi
	echo "$value"
}

COPILOT_MODEL="$(require_plan_cfg "tool_models.copilot" "copilot model")"
GEMINI_MODEL="$(require_plan_cfg "tool_models.gemini" "gemini model")"
CODEX_MODEL="$(require_plan_cfg "tool_models.codex" "codex model")"

COPILOT_DRAFT_MODEL="$(require_plan_cfg "stage_models.copilot_draft" "copilot_draft model")"
CODEX_ENRICH_MODEL="$(require_plan_cfg "stage_models.codex_enrich" "codex_enrich model")"
GEMINI_ENRICH_MODEL="$(require_plan_cfg "stage_models.gemini_enrich" "gemini_enrich model")"
CODEX_CROSS_REVIEW_MODEL="$(require_plan_cfg "stage_models.codex_cross_review" "codex_cross_review model")"
GEMINI_CROSS_REVIEW_MODEL="$(require_plan_cfg "stage_models.gemini_cross_review" "gemini_cross_review model")"
COPILOT_CONSOLIDATE_MODEL="$(require_plan_cfg "stage_models.copilot_consolidate" "copilot_consolidate model")"
CODEX_ENRICH_EFFORT="$(require_plan_cfg "stage_efforts.codex_enrich" "codex_enrich effort")"
CODEX_CROSS_REVIEW_EFFORT="$(require_plan_cfg "stage_efforts.codex_cross_review" "codex_cross_review effort")"

COPILOT_DRAFT_TIMEOUT_MS="$(require_plan_cfg "stage_timeout_ms.copilot_draft" "copilot_draft timeout_ms")"
CODEX_ENRICH_TIMEOUT_MS="$(require_plan_cfg "stage_timeout_ms.codex_enrich" "codex_enrich timeout_ms")"
GEMINI_ENRICH_TIMEOUT_MS="$(require_plan_cfg "stage_timeout_ms.gemini_enrich" "gemini_enrich timeout_ms")"
CODEX_CROSS_REVIEW_TIMEOUT_MS="$(require_plan_cfg "stage_timeout_ms.codex_cross_review" "codex_cross_review timeout_ms")"
GEMINI_CROSS_REVIEW_TIMEOUT_MS="$(require_plan_cfg "stage_timeout_ms.gemini_cross_review" "gemini_cross_review timeout_ms")"
COPILOT_CONSOLIDATE_TIMEOUT_MS="$(require_plan_cfg "stage_timeout_ms.copilot_consolidate" "copilot_consolidate timeout_ms")"

COPILOT_DRAFT_TIMEOUT_MODE="$(require_plan_cfg "stage_timeout_modes.copilot_draft" "copilot_draft timeout_mode")"
CODEX_ENRICH_TIMEOUT_MODE="$(require_plan_cfg "stage_timeout_modes.codex_enrich" "codex_enrich timeout_mode")"
GEMINI_ENRICH_TIMEOUT_MODE="$(require_plan_cfg "stage_timeout_modes.gemini_enrich" "gemini_enrich timeout_mode")"
CODEX_CROSS_REVIEW_TIMEOUT_MODE="$(require_plan_cfg "stage_timeout_modes.codex_cross_review" "codex_cross_review timeout_mode")"
GEMINI_CROSS_REVIEW_TIMEOUT_MODE="$(require_plan_cfg "stage_timeout_modes.gemini_cross_review" "gemini_cross_review timeout_mode")"
COPILOT_CONSOLIDATE_TIMEOUT_MODE="$(require_plan_cfg "stage_timeout_modes.copilot_consolidate" "copilot_consolidate timeout_mode")"

if [[ -n $TIMEOUT_MS_OVERRIDE ]]; then
	COPILOT_DRAFT_TIMEOUT_MS="$TIMEOUT_MS_OVERRIDE"
	CODEX_ENRICH_TIMEOUT_MS="$TIMEOUT_MS_OVERRIDE"
	GEMINI_ENRICH_TIMEOUT_MS="$TIMEOUT_MS_OVERRIDE"
	CODEX_CROSS_REVIEW_TIMEOUT_MS="$TIMEOUT_MS_OVERRIDE"
	GEMINI_CROSS_REVIEW_TIMEOUT_MS="$TIMEOUT_MS_OVERRIDE"
	COPILOT_CONSOLIDATE_TIMEOUT_MS="$TIMEOUT_MS_OVERRIDE"
fi

ENABLE_CODEX_ENRICH="$(require_plan_cfg_bool "flags.enable_codex_enrich" "enable_codex_enrich")"
ENABLE_GEMINI_ENRICH="$(require_plan_cfg_bool "flags.enable_gemini_enrich" "enable_gemini_enrich")"
ENABLE_CROSS_REVIEW="$(require_plan_cfg_bool "flags.enable_cross_review" "enable_cross_review")"

if [[ $ENABLE_CODEX_ENRICH != "true" && $ENABLE_GEMINI_ENRICH != "true" ]]; then
	log_error "Invalid plan profile: both enable_codex_enrich and enable_gemini_enrich are false"
	exit 1
fi

if [[ $ENABLE_CROSS_REVIEW == "true" && ($ENABLE_CODEX_ENRICH != "true" || $ENABLE_GEMINI_ENRICH != "true") ]]; then
	log_error "Invalid plan profile: enable_cross_review=true requires both enrich paths enabled"
	exit 1
fi

log_info "Plan profile: $(plan_cfg_get "profile")"
log_info "Plan flags: codex_enrich=${ENABLE_CODEX_ENRICH} gemini_enrich=${ENABLE_GEMINI_ENRICH} cross_review=${ENABLE_CROSS_REVIEW}"
log_info "Timeout policy: codex_enrich=${CODEX_ENRICH_TIMEOUT_MODE}/${CODEX_ENRICH_TIMEOUT_MS}ms gemini_enrich=${GEMINI_ENRICH_TIMEOUT_MODE}/${GEMINI_ENRICH_TIMEOUT_MS}ms codex_cross_review=${CODEX_CROSS_REVIEW_TIMEOUT_MODE}/${CODEX_CROSS_REVIEW_TIMEOUT_MS}ms gemini_cross_review=${GEMINI_CROSS_REVIEW_TIMEOUT_MODE}/${GEMINI_CROSS_REVIEW_TIMEOUT_MS}ms"

RESOLVED_PLAN_PROFILE="$(plan_cfg_get "profile")"

resolve_plan_task_root() {
	local abs_task_dir
	abs_task_dir="$(cd "$TASK_DIR" && pwd)"
	if [[ $(basename "$abs_task_dir") == "plan" ]]; then
		echo "$(dirname "$abs_task_dir")"
		return 0
	fi
	echo ""
}

resolve_plan_prompt_template() {
	local tool="$1"
	local role="$2"
	local legacy_path="$3"
	local task_root
	local candidate
	local default_template
	task_root="$(resolve_plan_task_root)"

	# 1) Task override
	if [[ -n $task_root ]]; then
		candidate="${task_root}/prompts/plan/${tool}/${role}.md"
		if [[ -f $candidate ]]; then
			echo "$candidate"
			return 0
		fi
	fi

	# 2) Profile override
	if [[ -n $RESOLVED_PLAN_PROFILE ]]; then
		candidate="${REPO_ROOT}/prompts-src/profiles/plan/${RESOLVED_PLAN_PROFILE}/${tool}/${role}.md"
		if [[ -f $candidate ]]; then
			echo "$candidate"
			return 0
		fi
	fi

	# 3) Default
	# "shared/*" is a virtual tool namespace used by plan stages.
	# Keep its defaults under prompts-src/plan/ to avoid conflicting with shared.md.
	if [[ $tool == "shared" ]]; then
		default_template="${REPO_ROOT}/prompts-src/plan/${role}.md"
	else
		default_template="${REPO_ROOT}/prompts-src/${tool}/${role}.md"
	fi
	if [[ -f $default_template ]]; then
		echo "$default_template"
		return 0
	fi

	# 4) Legacy fallback
	echo "$legacy_path"
	return 0
}

STAGE1_PROMPT="$(resolve_plan_prompt_template "copilot" "draft" "${SKILL_DIR}/stage1_draft.prompt.md")"
STAGE2_PROMPT="$(resolve_plan_prompt_template "shared" "enrich" "${SKILL_DIR}/stage2_enrich.prompt.md")"
STAGE3_PROMPT="$(resolve_plan_prompt_template "shared" "cross_review" "${SKILL_DIR}/stage3_crossreview.prompt.md")"
STAGE4_PROMPT="$(resolve_plan_prompt_template "copilot" "consolidate" "${SKILL_DIR}/stage4_consolidate.prompt.md")"

log_info "Plan prompts: stage1=$(basename "$STAGE1_PROMPT") stage2=$(basename "$STAGE2_PROMPT") stage3=$(basename "$STAGE3_PROMPT") stage4=$(basename "$STAGE4_PROMPT")"

if [[ $ENABLE_CODEX_ENRICH != "true" ]]; then
	rm -f "$CODEX_ENRICH_FILE" "${TASK_DIR}/codex-enrich.done" "${TASK_DIR}/codex-enrich.pid"
fi
if [[ $ENABLE_GEMINI_ENRICH != "true" ]]; then
	rm -f "$GEMINI_ENRICH_FILE" "${TASK_DIR}/gemini-enrich.done" "${TASK_DIR}/gemini-enrich.pid"
fi
if [[ $ENABLE_CROSS_REVIEW != "true" ]]; then
	rm -f "$GEMINI_REVIEW_FILE" "$CODEX_REVIEW_FILE" \
		"${TASK_DIR}/gemini-cross-review.done" "${TASK_DIR}/codex-cross-review.done" \
		"${TASK_DIR}/gemini-cross-review.pid" "${TASK_DIR}/codex-cross-review.pid"
fi

require_file() {
	local file="$1"
	local label="$2"
	if [[ ! -s $file ]]; then
		log_error "${label} missing or empty: ${file}"
		exit 1
	fi
}

check_min_lines() {
	local file="$1"
	local min_lines="$2"
	local label="$3"
	local lines
	lines=$(wc -l <"$file" | tr -d ' ')
	if ((lines < min_lines)); then
		log_error "${label} output too short (${lines} < ${min_lines} lines): ${file}"
		exit 1
	fi
}

normalize_timeout_mode() {
	local mode="$1"
	if [[ $mode == "enforce" || $mode == "wait_done" ]]; then
		echo "$mode"
		return 0
	fi
	log_error "Invalid timeout_mode in resolved plan config: ${mode}"
	exit 1
}

parallel_wait_timeout_seconds() {
	local timeout_ms_a="$1"
	local mode_a="$2"
	local timeout_ms_b="$3"
	local mode_b="$4"

	if [[ $mode_a == "wait_done" || $mode_b == "wait_done" ]]; then
		echo "0"
		return 0
	fi
	if ((timeout_ms_a <= 0 || timeout_ms_b <= 0)); then
		echo "0"
		return 0
	fi
	local max_timeout_ms="$timeout_ms_a"
	if ((timeout_ms_b > max_timeout_ms)); then
		max_timeout_ms="$timeout_ms_b"
	fi
	echo $((max_timeout_ms / 1000 + 60))
}

append_block() {
	local title="$1"
	local file="$2"
	local out="$3"
	{
		echo ""
		echo "--- BEGIN ${title} ---"
		cat "$file"
		echo ""
		echo "--- END ${title} ---"
		echo ""
	} >>"$out"
}

append_capped_block() {
	local title="$1"
	local file="$2"
	local max_lines="$3"
	local out="$4"
	local total
	total=$(wc -l <"$file" | tr -d ' ')
	{
		echo ""
		echo "--- BEGIN ${title} ---"
		if ((total <= max_lines)); then
			cat "$file"
		else
			head -n "$max_lines" "$file"
			echo ""
			echo "... [${title}: truncated $((total - max_lines)) lines] ..."
		fi
		echo ""
		echo "--- END ${title} ---"
		echo ""
	} >>"$out"
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
		tail -n 40 "$log_file" >&2 || true
	fi

	return $exit_code
}

run_wrapper_sync() {
	local label="$1"
	local wrapper="$2"
	local prompt_file="$3"
	local out_file="$4"
	local err_file="$5"
	local model="$6"
	local timeout_ms="$7"
	local timeout_mode="$8"
	local done_file="$9"
	local min_lines="${10}"
	local exec_log="${11}"
	local codex_effort="${12-}"

	local wrapper_cmd=(
		"$wrapper"
		--prompt-file "$prompt_file"
		--out "$out_file"
		--err "$err_file"
		--model "$model"
		--timeout-ms "$timeout_ms"
		--timeout-mode "$timeout_mode"
		--done-marker "$done_file"
	)
	if [[ $wrapper == *"/run_codex.sh" ]]; then
		wrapper_cmd+=(--effort "$codex_effort")
	fi

	run_silent_with_progress "$label" "$exec_log" \
		"${wrapper_cmd[@]}"

	require_file "$out_file" "${label} output"
	check_min_lines "$out_file" "$min_lines" "$label"
}

COPILOT_DRAFT_TIMEOUT_MODE="$(normalize_timeout_mode "$COPILOT_DRAFT_TIMEOUT_MODE")"
CODEX_ENRICH_TIMEOUT_MODE="$(normalize_timeout_mode "$CODEX_ENRICH_TIMEOUT_MODE")"
GEMINI_ENRICH_TIMEOUT_MODE="$(normalize_timeout_mode "$GEMINI_ENRICH_TIMEOUT_MODE")"
CODEX_CROSS_REVIEW_TIMEOUT_MODE="$(normalize_timeout_mode "$CODEX_CROSS_REVIEW_TIMEOUT_MODE")"
GEMINI_CROSS_REVIEW_TIMEOUT_MODE="$(normalize_timeout_mode "$GEMINI_CROSS_REVIEW_TIMEOUT_MODE")"
COPILOT_CONSOLIDATE_TIMEOUT_MODE="$(normalize_timeout_mode "$COPILOT_CONSOLIDATE_TIMEOUT_MODE")"

if [[ $SKIP_PREFLIGHT == "false" ]]; then
	REQUIRED_TOOLS="copilot"
	if [[ $ENABLE_GEMINI_ENRICH == "true" || $ENABLE_CROSS_REVIEW == "true" ]]; then
		REQUIRED_TOOLS="${REQUIRED_TOOLS},gemini"
	fi
	if [[ $ENABLE_CODEX_ENRICH == "true" || $ENABLE_CROSS_REVIEW == "true" ]]; then
		REQUIRED_TOOLS="${REQUIRED_TOOLS},codex"
	fi
	run_silent_with_progress "Preflight (${REQUIRED_TOOLS})" "${TASK_DIR}/preflight.log" \
		"${SCRIPT_DIR}/preflight.sh" --quick --tools "$REQUIRED_TOOLS"
fi

require_file "$PREFLIGHT_FILE" "Preflight file"
require_file "$STAGE1_PROMPT" "Stage1 prompt"
if [[ $ENABLE_CODEX_ENRICH == "true" || $ENABLE_GEMINI_ENRICH == "true" ]]; then
	require_file "$STAGE2_PROMPT" "Stage2 prompt"
fi
if [[ $ENABLE_CROSS_REVIEW == "true" ]]; then
	require_file "$STAGE3_PROMPT" "Stage3 prompt"
fi
require_file "$STAGE4_PROMPT" "Stage4 prompt"

log_info "Plan pipeline task dir: ${TASK_DIR}"

# ── Stage 1: Copilot draft ────────────────────────────────────────────────────
STAGE1_INPUT="${TASK_DIR}/stage1-input.md"
cat "$STAGE1_PROMPT" >"$STAGE1_INPUT"
append_block "PREFLIGHT" "$PREFLIGHT_FILE" "$STAGE1_INPUT"

run_wrapper_sync \
	"Stage 1 (Copilot draft)" \
	"${WRAPPER_DIR}/copilot_tool.sh" \
	"$STAGE1_INPUT" \
	"$DRAFT_FILE" \
	"${TASK_DIR}/stage1.err" \
	"$COPILOT_DRAFT_MODEL" \
	"$COPILOT_DRAFT_TIMEOUT_MS" \
	"$COPILOT_DRAFT_TIMEOUT_MODE" \
	"${TASK_DIR}/stage1.done" \
	"$MIN_DRAFT_LINES" \
	"${TASK_DIR}/stage1.exec.log"

# ── Stage 2: Parallel enrich (Codex + Gemini) ────────────────────────────────
STAGE2_CODEX_INPUT="${TASK_DIR}/stage2-codex-input.md"
STAGE2_GEMINI_INPUT="${TASK_DIR}/stage2-gemini-input.md"

cat "$STAGE2_PROMPT" >"$STAGE2_CODEX_INPUT"
append_block "PREFLIGHT" "$PREFLIGHT_FILE" "$STAGE2_CODEX_INPUT"
append_block "DRAFT PLAN" "$DRAFT_FILE" "$STAGE2_CODEX_INPUT"
cp "$STAGE2_CODEX_INPUT" "$STAGE2_GEMINI_INPUT"
if [[ $ENABLE_CODEX_ENRICH == "true" && $ENABLE_GEMINI_ENRICH == "true" ]]; then
	log_info "Stage 2 (parallel enrich): started"
	STAGE2_WAIT_TIMEOUT_SEC=$(
		parallel_wait_timeout_seconds \
			"$CODEX_ENRICH_TIMEOUT_MS" "$CODEX_ENRICH_TIMEOUT_MODE" \
			"$GEMINI_ENRICH_TIMEOUT_MS" "$GEMINI_ENRICH_TIMEOUT_MODE"
	)
	"${WRAPPER_DIR}/run_codex.sh" \
		--prompt-file "$STAGE2_CODEX_INPUT" \
		--out "$CODEX_ENRICH_FILE" \
		--err "${TASK_DIR}/codex-enrich.err" \
		--model "$CODEX_ENRICH_MODEL" \
		--effort "$CODEX_ENRICH_EFFORT" \
		--timeout-ms "$CODEX_ENRICH_TIMEOUT_MS" \
		--timeout-mode "$CODEX_ENRICH_TIMEOUT_MODE" \
		--done-marker "${TASK_DIR}/codex-enrich.done" \
		--pid-file "${TASK_DIR}/codex-enrich.pid" \
		>"${TASK_DIR}/codex-enrich.exec.log" 2>&1 &
	CODEX_PID=$!
	echo "$CODEX_PID" >"${TASK_DIR}/codex-enrich.pid"

	"${WRAPPER_DIR}/gemini_headless.sh" \
		--prompt-file "$STAGE2_GEMINI_INPUT" \
		--out "$GEMINI_ENRICH_FILE" \
		--err "${TASK_DIR}/gemini-enrich.err" \
		--model "$GEMINI_ENRICH_MODEL" \
		--timeout-ms "$GEMINI_ENRICH_TIMEOUT_MS" \
		--timeout-mode "$GEMINI_ENRICH_TIMEOUT_MODE" \
		--done-marker "${TASK_DIR}/gemini-enrich.done" \
		--pid-file "${TASK_DIR}/gemini-enrich.pid" \
		>"${TASK_DIR}/gemini-enrich.exec.log" 2>&1 &
	GEMINI_PID=$!
	echo "$GEMINI_PID" >"${TASK_DIR}/gemini-enrich.pid"

	"${WRAPPER_DIR}/wait_parallel_tasks.sh" \
		--label "stage2-enrich" \
		--timeout "$STAGE2_WAIT_TIMEOUT_SEC" \
		--task-1-done "${TASK_DIR}/codex-enrich.done" \
		--task-1-pid "${TASK_DIR}/codex-enrich.pid" \
		--task-1-out "$CODEX_ENRICH_FILE" \
		--task-2-done "${TASK_DIR}/gemini-enrich.done" \
		--task-2-pid "${TASK_DIR}/gemini-enrich.pid" \
		--task-2-out "$GEMINI_ENRICH_FILE" \
		--min-lines "$MIN_ENRICH_LINES"

	wait "$CODEX_PID"
	wait "$GEMINI_PID"
	check_min_lines "$CODEX_ENRICH_FILE" "$MIN_ENRICH_LINES" "Stage 2 codex enrich"
	check_min_lines "$GEMINI_ENRICH_FILE" "$MIN_ENRICH_LINES" "Stage 2 gemini enrich"
	log_ok "Stage 2 (parallel enrich): done"
elif [[ $ENABLE_CODEX_ENRICH == "true" ]]; then
	run_wrapper_sync \
		"Stage 2 (Codex enrich)" \
		"${WRAPPER_DIR}/run_codex.sh" \
		"$STAGE2_CODEX_INPUT" \
		"$CODEX_ENRICH_FILE" \
		"${TASK_DIR}/codex-enrich.err" \
		"$CODEX_ENRICH_MODEL" \
		"$CODEX_ENRICH_TIMEOUT_MS" \
		"$CODEX_ENRICH_TIMEOUT_MODE" \
		"${TASK_DIR}/codex-enrich.done" \
		"$MIN_ENRICH_LINES" \
		"${TASK_DIR}/codex-enrich.exec.log" \
		"$CODEX_ENRICH_EFFORT"
elif [[ $ENABLE_GEMINI_ENRICH == "true" ]]; then
	run_wrapper_sync \
		"Stage 2 (Gemini enrich)" \
		"${WRAPPER_DIR}/gemini_headless.sh" \
		"$STAGE2_GEMINI_INPUT" \
		"$GEMINI_ENRICH_FILE" \
		"${TASK_DIR}/gemini-enrich.err" \
		"$GEMINI_ENRICH_MODEL" \
		"$GEMINI_ENRICH_TIMEOUT_MS" \
		"$GEMINI_ENRICH_TIMEOUT_MODE" \
		"${TASK_DIR}/gemini-enrich.done" \
		"$MIN_ENRICH_LINES" \
		"${TASK_DIR}/gemini-enrich.exec.log"
fi

# ── Stage 3: Parallel cross-review ────────────────────────────────────────────
if [[ $ENABLE_CROSS_REVIEW == "true" ]]; then
	STAGE3_GEMINI_INPUT="${TASK_DIR}/stage3-gemini-review-input.md"
	STAGE3_CODEX_INPUT="${TASK_DIR}/stage3-codex-review-input.md"

	cat "$STAGE3_PROMPT" >"$STAGE3_GEMINI_INPUT"
	append_block "PREFLIGHT" "$PREFLIGHT_FILE" "$STAGE3_GEMINI_INPUT"
	append_block "BASE DRAFT" "$DRAFT_FILE" "$STAGE3_GEMINI_INPUT"
	append_block "CANDIDATE PLAN (CODEX)" "$CODEX_ENRICH_FILE" "$STAGE3_GEMINI_INPUT"

	cat "$STAGE3_PROMPT" >"$STAGE3_CODEX_INPUT"
	append_block "PREFLIGHT" "$PREFLIGHT_FILE" "$STAGE3_CODEX_INPUT"
	append_block "BASE DRAFT" "$DRAFT_FILE" "$STAGE3_CODEX_INPUT"
	append_block "CANDIDATE PLAN (GEMINI)" "$GEMINI_ENRICH_FILE" "$STAGE3_CODEX_INPUT"

	log_info "Stage 3 (parallel cross-review): started"
	STAGE3_WAIT_TIMEOUT_SEC=$(
		parallel_wait_timeout_seconds \
			"$GEMINI_CROSS_REVIEW_TIMEOUT_MS" "$GEMINI_CROSS_REVIEW_TIMEOUT_MODE" \
			"$CODEX_CROSS_REVIEW_TIMEOUT_MS" "$CODEX_CROSS_REVIEW_TIMEOUT_MODE"
	)
	"${WRAPPER_DIR}/gemini_headless.sh" \
		--prompt-file "$STAGE3_GEMINI_INPUT" \
		--out "$GEMINI_REVIEW_FILE" \
		--err "${TASK_DIR}/gemini-cross-review.err" \
		--model "$GEMINI_CROSS_REVIEW_MODEL" \
		--timeout-ms "$GEMINI_CROSS_REVIEW_TIMEOUT_MS" \
		--timeout-mode "$GEMINI_CROSS_REVIEW_TIMEOUT_MODE" \
		--done-marker "${TASK_DIR}/gemini-cross-review.done" \
		--pid-file "${TASK_DIR}/gemini-cross-review.pid" \
		>"${TASK_DIR}/gemini-cross-review.exec.log" 2>&1 &
	GEMINI_REVIEW_PID=$!
	echo "$GEMINI_REVIEW_PID" >"${TASK_DIR}/gemini-cross-review.pid"

	"${WRAPPER_DIR}/run_codex.sh" \
		--prompt-file "$STAGE3_CODEX_INPUT" \
		--out "$CODEX_REVIEW_FILE" \
		--err "${TASK_DIR}/codex-cross-review.err" \
		--model "$CODEX_CROSS_REVIEW_MODEL" \
		--effort "$CODEX_CROSS_REVIEW_EFFORT" \
		--timeout-ms "$CODEX_CROSS_REVIEW_TIMEOUT_MS" \
		--timeout-mode "$CODEX_CROSS_REVIEW_TIMEOUT_MODE" \
		--done-marker "${TASK_DIR}/codex-cross-review.done" \
		--pid-file "${TASK_DIR}/codex-cross-review.pid" \
		>"${TASK_DIR}/codex-cross-review.exec.log" 2>&1 &
	CODEX_REVIEW_PID=$!
	echo "$CODEX_REVIEW_PID" >"${TASK_DIR}/codex-cross-review.pid"

	"${WRAPPER_DIR}/wait_parallel_tasks.sh" \
		--label "stage3-crossreview" \
		--timeout "$STAGE3_WAIT_TIMEOUT_SEC" \
		--task-1-done "${TASK_DIR}/gemini-cross-review.done" \
		--task-1-pid "${TASK_DIR}/gemini-cross-review.pid" \
		--task-1-out "$GEMINI_REVIEW_FILE" \
		--task-2-done "${TASK_DIR}/codex-cross-review.done" \
		--task-2-pid "${TASK_DIR}/codex-cross-review.pid" \
		--task-2-out "$CODEX_REVIEW_FILE" \
		--min-lines "$MIN_REVIEW_LINES"

	wait "$GEMINI_REVIEW_PID"
	wait "$CODEX_REVIEW_PID"
	check_min_lines "$GEMINI_REVIEW_FILE" "$MIN_REVIEW_LINES" "Stage 3 gemini cross-review"
	check_min_lines "$CODEX_REVIEW_FILE" "$MIN_REVIEW_LINES" "Stage 3 codex cross-review"
	log_ok "Stage 3 (parallel cross-review): done"
else
	log_info "Stage 3 skipped by config (enable_cross_review=false)"
fi

# ── Stage 4: Copilot consolidate ──────────────────────────────────────────────
cat "$STAGE4_PROMPT" >"$STAGE4_INPUT_FILE"
append_block "PREFLIGHT" "$PREFLIGHT_FILE" "$STAGE4_INPUT_FILE"
append_capped_block "DRAFT PLAN" "$DRAFT_FILE" "$STAGE4_ARTIFACT_CAP_LINES" "$STAGE4_INPUT_FILE"

if [[ -s $CODEX_ENRICH_FILE ]]; then
	append_capped_block "CODEX ENRICH PLAN" "$CODEX_ENRICH_FILE" "$STAGE4_ARTIFACT_CAP_LINES" "$STAGE4_INPUT_FILE"
fi
if [[ -s $GEMINI_ENRICH_FILE ]]; then
	append_capped_block "GEMINI ENRICH PLAN" "$GEMINI_ENRICH_FILE" "$STAGE4_ARTIFACT_CAP_LINES" "$STAGE4_INPUT_FILE"
fi
if [[ $ENABLE_CROSS_REVIEW == "true" && -s $GEMINI_REVIEW_FILE ]]; then
	append_capped_block "GEMINI REVIEW OF CODEX" "$GEMINI_REVIEW_FILE" "$STAGE4_ARTIFACT_CAP_LINES" "$STAGE4_INPUT_FILE"
fi
if [[ $ENABLE_CROSS_REVIEW == "true" && -s $CODEX_REVIEW_FILE ]]; then
	append_capped_block "CODEX REVIEW OF GEMINI" "$CODEX_REVIEW_FILE" "$STAGE4_ARTIFACT_CAP_LINES" "$STAGE4_INPUT_FILE"
fi

run_wrapper_sync \
	"Stage 4 (Copilot consolidate)" \
	"${WRAPPER_DIR}/copilot_tool.sh" \
	"$STAGE4_INPUT_FILE" \
	"$FINAL_FILE" \
	"${TASK_DIR}/stage4.err" \
	"$COPILOT_CONSOLIDATE_MODEL" \
	"$COPILOT_CONSOLIDATE_TIMEOUT_MS" \
	"$COPILOT_CONSOLIDATE_TIMEOUT_MODE" \
	"${TASK_DIR}/stage4.done" \
	"$MIN_FINAL_LINES" \
	"${TASK_DIR}/stage4.exec.log"

SUMMARY_FILE="${TASK_DIR}/summary.md"
{
	echo "# Plan Pipeline Summary"
	echo ""
	echo "Task dir: ${TASK_DIR}"
	echo "Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
	echo ""
	echo "## Artifacts"
	echo ""
	[[ -s $DRAFT_FILE ]] && echo "- ${DRAFT_FILE}"
	[[ -s $CODEX_ENRICH_FILE ]] && echo "- ${CODEX_ENRICH_FILE}"
	[[ -s $GEMINI_ENRICH_FILE ]] && echo "- ${GEMINI_ENRICH_FILE}"
	[[ -s $GEMINI_REVIEW_FILE ]] && echo "- ${GEMINI_REVIEW_FILE}"
	[[ -s $CODEX_REVIEW_FILE ]] && echo "- ${CODEX_REVIEW_FILE}"
	[[ -s $FINAL_FILE ]] && echo "- ${FINAL_FILE}"
	echo ""
	echo "## Next Steps"
	echo ""
	echo "1. Human review: Inspect ${FINAL_FILE} and adjust if needed."
	echo "2. Direct handoff: Run scripts/agent-cli/plan_to_task_packet.sh to bootstrap implementation task."
	echo "3. Execute implementation: Run scripts/agent-cli/dispatch.sh pipeline on the new Task Packet."
} >"${SUMMARY_FILE}.partial"
atomic_write "${SUMMARY_FILE}.partial" "$SUMMARY_FILE"

log_ok "Plan pipeline complete: ${FINAL_FILE}"
exit 0
