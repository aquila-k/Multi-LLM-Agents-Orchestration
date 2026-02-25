#!/usr/bin/env bash
# dispatch_impl.sh — Impl phase dispatcher
#
# Usage:
#   dispatch_impl.sh --task-root <dir> --task-name <name> [options]
#   dispatch_impl.sh --task-root <dir> --task-name <name> \
#     [--plan-file <file>] [--goal <text>] [--intent <intent>] \
#     [--run-id <id>] [--phase-session-mode <mode>] [--skip-preflight]
#
# Canonical output:
#   <task-root>/impl/outputs/_summary.md
#
# Behavior:
#   - If <task-root>/impl/manifest.yaml does not exist, bootstraps Task Packet
#     from <task-root>/plan/final-plan.md (requires --goal)
#   - Otherwise, uses existing Task Packet directly
#   - Delegates to dispatch.sh pipeline --task <impl-dir>
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
PLAN_FILE=""
GOAL=""
INTENT="safe_impl"
TIMEOUT_MS=""
SKIP_PREFLIGHT=false
RUN_ID="$(date -u +"%Y%m%d-%H%M%S")-impl"
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
	--plan-file)
		PLAN_FILE="$2"
		shift 2
		;;
	--goal)
		GOAL="$2"
		shift 2
		;;
	--intent)
		INTENT="$2"
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

# Initialize canonical directory structure
task_path_ensure "$TASK_NAME" "$(dirname "$TASK_ROOT")" >/dev/null
IMPL_DIR="${TASK_ROOT}/impl"

# Initialize session state
dispatch_core_init "$TASK_ROOT" "$TASK_NAME" "$RUN_ID" "impl" \
	"$PHASE_SESSION_MODE" "false"

# Bootstrap Task Packet from plan if manifest doesn't exist
if [[ ! -f "${IMPL_DIR}/manifest.yaml" ]]; then
	# Resolve plan file: prefer explicit arg, then canonical alias, then fallback
	if [[ -z $PLAN_FILE ]]; then
		PLAN_FILE="${TASK_ROOT}/plan/final-plan.md"
		if [[ ! -f $PLAN_FILE ]]; then
			PLAN_FILE="${TASK_ROOT}/plan/final.md"
		fi
	fi

	if [[ -z $PLAN_FILE || ! -f $PLAN_FILE ]]; then
		log_error "No plan file found. Provide --plan-file or run plan phase first."
		log_error "  Tried: ${TASK_ROOT}/plan/final-plan.md"
		log_error "  Tried: ${TASK_ROOT}/plan/final.md"
		exit 2
	fi

	if [[ -z $GOAL ]]; then
		log_error "--goal is required when bootstrapping Task Packet from plan"
		exit 2
	fi

	log_info "dispatch_impl: bootstrapping Task Packet from plan=${PLAN_FILE}"
	"${SCRIPT_DIR}/plan_to_task_packet.sh" \
		--plan-file "$PLAN_FILE" \
		--task-dir "$IMPL_DIR" \
		--goal "$GOAL" \
		--intent "$INTENT"
else
	log_info "dispatch_impl: using existing Task Packet: ${IMPL_DIR}"
fi

# Build dispatch.sh pipeline command
PIPELINE_CMD=("${SCRIPT_DIR}/dispatch.sh" pipeline --task "$IMPL_DIR")
PIPELINE_CMD+=(
	--task-root "$TASK_ROOT"
	--phase "impl"
	--phase-session-mode "$PHASE_SESSION_MODE"
)

# Pass timeout override via environment variable if specified.
# dispatch.sh reads DISPATCH_TIMEOUT_MS_OVERRIDE to override per-stage defaults.
if [[ -n $TIMEOUT_MS ]]; then
	export DISPATCH_TIMEOUT_MS_OVERRIDE="$TIMEOUT_MS"
fi

log_info "dispatch_impl: task=${TASK_NAME} run=${RUN_ID} impl_dir=${IMPL_DIR} intent=${INTENT}"

# Record routing result before execution
# delegated-auto: call resolve_routing.sh (LLM-based, ~120s)
# local-auto / fixed: write V2-schema record from intent inline (fast)
ROUTING_RESULT_FILE="${IMPL_DIR}/routing_result.json"
ROUTING_MODE="${ROUTING_MODE:-local-auto}"

if [[ ${ROUTING_MODE} == "delegated-auto" ]]; then
	"${SCRIPT_DIR}/resolve_routing.sh" \
		--phase "impl" \
		--task-root "${TASK_ROOT}" \
		--out "${ROUTING_RESULT_FILE}"
else
	# local-auto / fixed: write V2 schema routing_result.json from intent
	python3 - "${IMPL_DIR}" "${INTENT}" "${RUN_ID}" <<'PYEOF'
import datetime, json, os, sys

impl_dir, intent, run_id = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(impl_dir, exist_ok=True)

payload = {
  "phase": "impl",
  "selected_method_ids": [intent],
  "step_agent_model_map": {},
  "alternatives": {
    "accepted": [intent],
    "rejected": [],
  },
  "signals": {
    "impact_surface": "medium",
    "change_shape": "edit",
    "scope_spread": "local",
    "requirement_clarity": "medium",
    "verification_load": "medium",
  },
  "reasoning": ["local-auto default"],
  "confidence": "medium",
  "requires_human_confirm": False,
  "web_research_policy": {"mode": "off"},
  "reason_codes": ["LOCAL_AUTO"],
  "stop_action": "CONTINUE",
  "impl_profile": intent,
  "routing_mode": "local-auto",
  "run_id": run_id,
  "recorded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

for fname in ("routing_result.json", "impl_profile.json"):
    path    = os.path.join(impl_dir, fname)
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(partial, path)
PYEOF
fi

IMPL_EXIT=0
"${PIPELINE_CMD[@]}" || IMPL_EXIT=$?

if [[ $IMPL_EXIT -ne 0 ]]; then
	dispatch_core_record_phase_done "$TASK_ROOT" "$RUN_ID" "impl" "failed"
	log_error "dispatch_impl: impl pipeline failed (exit=${IMPL_EXIT})"
	exit 1
fi

dispatch_core_record_phase_done "$TASK_ROOT" "$RUN_ID" "impl" "success"
log_ok "dispatch_impl: complete — ${IMPL_DIR}/outputs/_summary.md"
exit 0
