#!/usr/bin/env bash
# run_agent_collab.sh — Unified entry point for plan/impl/review workflows
#
# Modes:
#   plan       : run planning pipeline only
#   impl       : run implementation pipeline only
#   review     : run post-implementation review only
#   all | full : run plan -> impl -> review
#
# Canonical usage (recommended):
#   run_agent_collab.sh --mode <mode> --task-name <name> [options]
#
# Legacy alias:
#   --task-id is kept as alias for --task-name (backward compat)
#
# Artifacts are written under: .tmp/task/<task-name>/
#   plan:   .tmp/task/<name>/plan/final-plan.md
#   impl:   .tmp/task/<name>/impl/outputs/_summary.md
#   review: .tmp/task/<name>/review/summary.md

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
source "${SCRIPT_DIR}/lib/log.sh"
source "${SCRIPT_DIR}/lib/task_paths.sh"

MODE=""
TASK_NAME=""
TASK_ID=""

PREFLIGHT_FILE=""
PLAN_FILE=""
GOAL=""
INTENT="safe_impl"
PLAN_PROFILE=""
TIMEOUT_MS=""
SKIP_PREFLIGHT=false
PHASE_SESSION_MODE=""
CROSS_PHASE_RESUME="false"
ROUTING_MODE="local-auto"
ROUTING_DECISION_FILE=""
CONTEXT_PACK=""
IMPL_REPORT=""
PARALLEL_REVIEW=false

# Deprecated dir-based args (accepted for backward compat, emit warnings)
_LEGACY_PLAN_DIR=""
_LEGACY_TASK_DIR=""
_LEGACY_REVIEW_DIR=""

usage() {
	cat <<'EOF'
Usage:
  run_agent_collab.sh --mode <plan|impl|review|all|full> [options]

Canonical options:
  --task-name <name>            Task name (canonical; artifacts at .tmp/task/<name>/)
  --task-id <id>                Alias for --task-name (backward compat)

Plan options:
  --preflight <file>            Input preflight markdown
  --profile <name>              Plan pipeline profile
  --timeout-ms <ms>             Timeout override
  --skip-preflight              Skip CLI dependency checks

Impl options:
  --plan-file <file>            Final plan markdown (default: task-root/plan/final-plan.md)
  --goal <text>                 Goal text for task bootstrap
  --intent <intent>             routing.intent (default: safe_impl)

Session options:
  --phase-session-mode <mode>   Session policy (default: forced_within_phase)
  --cross-phase-resume          Enable cross-phase session resume

Routing options:
  --routing-mode <mode>         local-auto|delegated-auto|fixed (default: local-auto)
  --routing-decision-file <f>   Path to routing_decision.json (for delegated-auto)

Review options:
  --context-pack <file>         Context pack for review (default: task-root/impl/inputs/context_pack.md)
  --impl-report <file>          Implementation report for review (default: auto-resolved)
  --parallel-review             Enable parallel review lens flow

Deprecated (use --task-name instead):
  --plan-dir <dir>              Legacy plan dir (ignored)
  --task-dir <dir>              Legacy task packet dir (ignored)
  --review-dir <dir>            Legacy review dir (ignored)

Examples:
  # Plan only (canonical)
  run_agent_collab.sh --mode plan --task-name my-feature-20260224 --preflight preflight.md

  # Implementation only from approved plan
  run_agent_collab.sh --mode impl --task-name my-feature-20260224 --goal "Implement approved plan"

  # Review only
  run_agent_collab.sh --mode review --task-name my-feature-20260224

  # Full flow
  run_agent_collab.sh --mode all --task-name my-feature-20260224 \
    --preflight preflight.md --goal "Implement approved plan"
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--mode)
		MODE="$2"
		shift 2
		;;
	--task-name)
		TASK_NAME="$2"
		shift 2
		;;
	--task-id)
		TASK_ID="$2"
		shift 2
		;;
	--preflight)
		PREFLIGHT_FILE="$2"
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
	--phase-session-mode)
		PHASE_SESSION_MODE="$2"
		shift 2
		;;
	--cross-phase-resume)
		CROSS_PHASE_RESUME="true"
		shift
		;;
	--routing-mode)
		ROUTING_MODE="$2"
		shift 2
		;;
	--routing-decision-file)
		ROUTING_DECISION_FILE="$2"
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
	--parallel-review)
		PARALLEL_REVIEW=true
		shift
		;;
	# Deprecated dir-based args
	--plan-dir)
		_LEGACY_PLAN_DIR="$2"
		shift 2
		;;
	--task-dir)
		_LEGACY_TASK_DIR="$2"
		shift 2
		;;
	--review-dir)
		_LEGACY_REVIEW_DIR="$2"
		shift 2
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

if [[ -z $MODE ]]; then
	log_error "--mode is required"
	usage
	exit 2
fi

# Normalize --mode full → all
if [[ $MODE == "full" ]]; then
	MODE="all"
fi

# Resolve TASK_NAME: explicit takes priority, then --task-id alias, then generate
if [[ -z $TASK_NAME && -n $TASK_ID ]]; then
	TASK_NAME="$TASK_ID"
fi
if [[ -z $TASK_NAME ]]; then
	TASK_NAME="$(task_name_generate)"
fi

# Warn if legacy dir args are provided (they are ignored in canonical mode)
if [[ -n $_LEGACY_PLAN_DIR || -n $_LEGACY_TASK_DIR || -n $_LEGACY_REVIEW_DIR ]]; then
	log_warn "Deprecated: --plan-dir / --task-dir / --review-dir are ignored."
	log_warn "  Use --task-name; artifacts will be under: .tmp/task/${TASK_NAME}/"
fi

TASK_ROOT="$(task_path_root "$TASK_NAME" "$REPO_ROOT")"

if [[ -n $TIMEOUT_MS && ! $TIMEOUT_MS =~ ^[0-9]+$ ]]; then
	log_error "--timeout-ms must be a non-negative integer (got: ${TIMEOUT_MS})"
	exit 2
fi

# ── Phase runners ──────────────────────────────────────────────────────────────

# ── Routing resolver (delegated-auto) ──────────────────────────────────────────

# resolve_routing_for_phase <phase> <profile_key>
#   Calls resolve_routing.sh and returns the resolved profile value.
#   On failure, echoes the default and returns 0 (fail-safe).
resolve_routing_for_phase() {
	local phase="$1"
	local profile_key="$2"

	local decision_file="${TASK_ROOT}/state/routing-decision.${phase}.json"
	local resolve_args=(
		"${SCRIPT_DIR}/resolve_routing.sh"
		--phase "$phase"
		--task-root "$TASK_ROOT"
		--out "$decision_file"
	)
	if [[ -n $ROUTING_DECISION_FILE ]]; then
		# Caller already provided a pre-computed decision file; use it directly
		decision_file="$ROUTING_DECISION_FILE"
	else
		"${resolve_args[@]}" || true
	fi

	if [[ -f $decision_file ]]; then
		python3 -c \
			"import json,sys; d=json.load(open('${decision_file}')); print(d.get('${profile_key}',''))" \
			2>/dev/null || true
	fi
}

run_plan_phase() {
	if [[ -z $PREFLIGHT_FILE ]]; then
		log_error "--preflight is required for mode=${MODE}"
		exit 2
	fi
	if [[ ! -s $PREFLIGHT_FILE ]]; then
		log_error "Preflight file missing or empty: ${PREFLIGHT_FILE}"
		exit 1
	fi

	# Delegated routing: resolve plan profile
	if [[ $ROUTING_MODE == "delegated-auto" ]]; then
		local resolved_profile
		resolved_profile="$(resolve_routing_for_phase plan plan_profile)"
		if [[ -n $resolved_profile && $resolved_profile != "standard" ]]; then
			log_info "run_agent_collab: delegated plan_profile → ${resolved_profile}"
			PLAN_PROFILE="$resolved_profile"
		fi
	fi

	local cmd=("${SCRIPT_DIR}/dispatch_plan.sh"
		--task-root "$TASK_ROOT"
		--task-name "$TASK_NAME"
		--preflight "$PREFLIGHT_FILE")

	if [[ -n $PLAN_PROFILE ]]; then
		cmd+=(--profile "$PLAN_PROFILE")
	fi
	if [[ -n $TIMEOUT_MS ]]; then
		cmd+=(--timeout-ms "$TIMEOUT_MS")
	fi
	if [[ $SKIP_PREFLIGHT == "true" ]]; then
		cmd+=(--skip-preflight)
	fi
	if [[ -n $PHASE_SESSION_MODE ]]; then
		cmd+=(--phase-session-mode "$PHASE_SESSION_MODE")
	fi

	log_info "run_agent_collab: plan phase → task=${TASK_NAME}"
	"${cmd[@]}"
}

run_impl_phase() {
	# Delegated routing: resolve impl profile
	if [[ $ROUTING_MODE == "delegated-auto" ]]; then
		local resolved_intent
		resolved_intent="$(resolve_routing_for_phase impl impl_profile)"
		if [[ -n $resolved_intent ]]; then
			log_info "run_agent_collab: delegated impl_profile → ${resolved_intent}"
			INTENT="$resolved_intent"
		fi
	fi

	local cmd=("${SCRIPT_DIR}/dispatch_impl.sh"
		--task-root "$TASK_ROOT"
		--task-name "$TASK_NAME"
		--intent "$INTENT")

	if [[ -n $PLAN_FILE ]]; then
		cmd+=(--plan-file "$PLAN_FILE")
	fi
	if [[ -n $GOAL ]]; then
		cmd+=(--goal "$GOAL")
	fi
	if [[ -n $TIMEOUT_MS ]]; then
		cmd+=(--timeout-ms "$TIMEOUT_MS")
	fi
	if [[ $SKIP_PREFLIGHT == "true" ]]; then
		cmd+=(--skip-preflight)
	fi
	if [[ -n $PHASE_SESSION_MODE ]]; then
		cmd+=(--phase-session-mode "$PHASE_SESSION_MODE")
	fi

	log_info "run_agent_collab: impl phase → task=${TASK_NAME}"
	"${cmd[@]}"
}

run_review_phase() {
	# Delegated routing: resolve review profile
	local REVIEW_PROFILE=""
	if [[ $ROUTING_MODE == "delegated-auto" ]]; then
		REVIEW_PROFILE="$(resolve_routing_for_phase review review_profile)"
		if [[ -n $REVIEW_PROFILE ]]; then
			log_info "run_agent_collab: delegated review_profile → ${REVIEW_PROFILE}"
		fi
	fi

	local cmd=("${SCRIPT_DIR}/dispatch_review.sh"
		--task-root "$TASK_ROOT"
		--task-name "$TASK_NAME")

	if [[ -n $CONTEXT_PACK ]]; then
		cmd+=(--context-pack "$CONTEXT_PACK")
	fi
	if [[ -n $IMPL_REPORT ]]; then
		cmd+=(--impl-report "$IMPL_REPORT")
	fi
	if [[ -n $PHASE_SESSION_MODE ]]; then
		cmd+=(--phase-session-mode "$PHASE_SESSION_MODE")
	fi
	if [[ -n $REVIEW_PROFILE ]]; then
		cmd+=(--review-profile "$REVIEW_PROFILE")
	fi
	if [[ $PARALLEL_REVIEW == "true" ]]; then
		cmd+=(--parallel-review)
	fi

	log_info "run_agent_collab: review phase → task=${TASK_NAME}"
	"${cmd[@]}"
}

# ── Mode dispatch ──────────────────────────────────────────────────────────────

log_info "=== run_agent_collab: mode=${MODE} task=${TASK_NAME} ==="
log_info "  task_root: ${TASK_ROOT}"

case "$MODE" in
plan)
	run_plan_phase
	;;
impl)
	run_impl_phase
	;;
review)
	run_review_phase
	;;
all)
	run_plan_phase
	run_impl_phase
	run_review_phase
	;;
*)
	log_error "Invalid mode: ${MODE} (expected: plan|impl|review|all|full)"
	exit 2
	;;
esac

log_info "=== run_agent_collab: done ==="
if [[ -f "${TASK_ROOT}/plan/final-plan.md" ]]; then
	log_info "  plan:   ${TASK_ROOT}/plan/final-plan.md"
fi
if [[ -f "${TASK_ROOT}/impl/outputs/_summary.md" ]]; then
	log_info "  impl:   ${TASK_ROOT}/impl/outputs/_summary.md"
fi
if [[ -f "${TASK_ROOT}/review/summary.md" ]]; then
	log_info "  review: ${TASK_ROOT}/review/summary.md"
fi
