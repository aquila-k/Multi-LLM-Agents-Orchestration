#!/usr/bin/env bash
# dispatch_plan.sh — Plan phase dispatcher
#
# Usage:
#   dispatch_plan.sh --task-root <dir> --task-name <name> --preflight <file> [options]
#   dispatch_plan.sh --task-root <dir> --task-name <name> --preflight <file> \
#     [--profile <name>] [--timeout-ms <ms>] [--skip-preflight] \
#     [--run-id <id>] [--phase-session-mode <mode>]
#
# Canonical output:
#   <task-root>/plan/final-plan.md  (+ final.md alias for backward compat)
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

TASK_ROOT=""
TASK_NAME=""
PREFLIGHT_FILE=""
PLAN_PROFILE=""
TIMEOUT_MS=""
SKIP_PREFLIGHT=false
RUN_ID="$(date -u +"%Y%m%d-%H%M%S")-plan"
PHASE_SESSION_MODE="${DISPATCH_CORE_DEFAULT_PHASE_SESSION_MODE}"

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
	--preflight)
		PREFLIGHT_FILE="$2"
		shift 2
		;;
	--profile)
		PLAN_PROFILE="$2"
		shift 2
		;;
	--timeout-ms)
		TIMEOUT_MS="$2"
		shift 2
		;;
	--skip-preflight)
		SKIP_PREFLIGHT=true
		shift
		;;
	--run-id)
		RUN_ID="$2"
		shift 2
		;;
	--phase-session-mode)
		PHASE_SESSION_MODE="$2"
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
if [[ -z $PREFLIGHT_FILE || ! -f $PREFLIGHT_FILE ]]; then
	log_error "--preflight file not found: ${PREFLIGHT_FILE:-<unset>}"
	exit 2
fi

# Initialize canonical directory structure
task_path_ensure "$TASK_NAME" "$(dirname "$TASK_ROOT")" >/dev/null
PLAN_DIR="${TASK_ROOT}/plan"

# Initialize session state
dispatch_core_init "$TASK_ROOT" "$TASK_NAME" "$RUN_ID" "plan" \
	"$PHASE_SESSION_MODE" "false"

# Copy preflight to canonical plan dir
cp "$PREFLIGHT_FILE" "${PLAN_DIR}/preflight.md"

# Build run_plan_pipeline.sh command
PIPELINE_CMD=("${SCRIPT_DIR}/run_plan_pipeline.sh" --task-dir "$PLAN_DIR")
if [[ -n $PLAN_PROFILE ]]; then
	PIPELINE_CMD+=(--profile "$PLAN_PROFILE")
fi
if [[ -n $TIMEOUT_MS ]]; then
	export DISPATCH_TIMEOUT_MS_OVERRIDE="$TIMEOUT_MS"
fi
if [[ $SKIP_PREFLIGHT == "true" ]]; then
	PIPELINE_CMD+=(--skip-preflight)
fi

# Record V2 routing decision before pipeline execution
ROUTING_RESULT_FILE="${PLAN_DIR}/routing_result.json"
ROUTING_MODE="${ROUTING_MODE:-local-auto}"
PLAN_INTENT="design_only"

if [[ ${ROUTING_MODE} == "delegated-auto" ]]; then
	"${SCRIPT_DIR}/resolve_routing.sh" \
		--phase "plan" \
		--task-root "${TASK_ROOT}" \
		--out "${ROUTING_RESULT_FILE}"
else
	# local-auto / fixed: write V2 schema routing_result.json
	python3 - "${PLAN_DIR}" "${PLAN_INTENT}" "${RUN_ID}" "${PLAN_PROFILE:-default}" <<'PYEOF'
import datetime, json, os, sys

plan_dir, intent, run_id, profile = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
os.makedirs(plan_dir, exist_ok=True)

payload = {
  "phase": "plan",
  "selected_method_ids": [intent],
  "step_agent_model_map": {},
  "alternatives": {
    "accepted": [intent],
    "rejected": [],
  },
  "signals": {
    "impact_surface": "low",
    "change_shape": "plan",
    "scope_spread": "local",
    "requirement_clarity": "medium",
    "verification_load": "low",
  },
  "reasoning": ["local-auto default for plan phase"],
  "confidence": "high",
  "requires_human_confirm": False,
  "web_research_policy": {"mode": "off"},
  "reason_codes": ["LOCAL_AUTO"],
  "stop_action": "CONTINUE",
  "plan_profile": profile,
  "routing_mode": "local-auto",
  "run_id": run_id,
  "recorded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

path    = os.path.join(plan_dir, "routing_result.json")
partial = path + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, path)
PYEOF
fi

log_info "dispatch_plan: task=${TASK_NAME} run=${RUN_ID} plan_dir=${PLAN_DIR}"

PLAN_EXIT=0
"${PIPELINE_CMD[@]}" || PLAN_EXIT=$?

if [[ $PLAN_EXIT -ne 0 ]]; then
	dispatch_core_record_phase_done "$TASK_ROOT" "$RUN_ID" "plan" "failed"
	log_error "dispatch_plan: plan pipeline failed (exit=${PLAN_EXIT})"
	exit 1
fi

# Create canonical alias: final-plan.md → final.md
PLAN_FINAL="${PLAN_DIR}/final.md"
PLAN_CANONICAL="${PLAN_DIR}/final-plan.md"

if [[ -f $PLAN_FINAL && ! -f $PLAN_CANONICAL ]]; then
	cp "$PLAN_FINAL" "$PLAN_CANONICAL"
elif [[ -f $PLAN_FINAL ]]; then
	cp "$PLAN_FINAL" "$PLAN_CANONICAL"
fi

dispatch_core_record_phase_done "$TASK_ROOT" "$RUN_ID" "plan" "success"
log_ok "dispatch_plan: complete — ${PLAN_CANONICAL}"
exit 0
