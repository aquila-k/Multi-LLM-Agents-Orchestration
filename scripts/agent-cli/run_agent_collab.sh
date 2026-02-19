#!/usr/bin/env bash
# run_agent_collab.sh — Unified entry point for plan/impl/review workflows
#
# Modes:
#   plan   : run planning pipeline only
#   impl   : run implementation pipeline only
#   review : run post-implementation review only
#   all    : run plan -> impl -> review

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/log.sh"

MODE=""
TASK_ID="$(date +%Y%m%d-%H%M%S)"
PLAN_DIR=""
TASK_DIR=""
REVIEW_DIR=""

PREFLIGHT_FILE=""
PLAN_FILE=""
GOAL=""
INTENT="safe_impl"
PLAN_PROFILE=""
TIMEOUT_MS=""
SKIP_PREFLIGHT=false

CONTEXT_PACK=""
IMPL_REPORT=""

usage() {
  cat <<'EOF'
Usage:
  run_agent_collab.sh --mode <plan|impl|review|all> [options]

Common options:
  --task-id <id>                Shared run id (default: YYYYMMDD-HHMMSS)
  --plan-dir <dir>              Plan artifact dir (default: .tmp/agent-collab/<id>/plan)
  --task-dir <dir>              Task Packet dir (default: .tmp/agent-collab/<id>/task)
  --review-dir <dir>            Review output dir (default: .tmp/agent-collab/<id>/review)

Plan options:
  --preflight <file>            Input preflight markdown
  --profile <name>              Plan pipeline profile
  --timeout-ms <ms>             Timeout override passed to run_plan_pipeline.sh
  --skip-preflight              Skip CLI dependency checks in plan pipeline

Impl options:
  --plan-file <file>            Final plan markdown for task bootstrap
  --goal <text>                 Goal text for task bootstrap
  --intent <intent>             routing.intent (default: safe_impl)

Review options:
  --context-pack <file>         Context pack markdown for review
  --impl-report <file>          Implementation report markdown for review

Examples:
  # Plan only
  run_agent_collab.sh --mode plan --preflight .tmp/agent-collab/preflight.md

  # Implementation only from approved plan
  run_agent_collab.sh --mode impl --plan-file .tmp/plan/final.md --goal "Implement approved plan"

  # Review only from existing task packet
  run_agent_collab.sh --mode review --task-dir .tmp/task/20260218-001

  # Full flow
  run_agent_collab.sh --mode all --preflight .tmp/agent-collab/preflight.md --goal "Implement approved plan"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --task-id) TASK_ID="$2"; shift 2 ;;
    --plan-dir) PLAN_DIR="$2"; shift 2 ;;
    --task-dir) TASK_DIR="$2"; shift 2 ;;
    --review-dir) REVIEW_DIR="$2"; shift 2 ;;
    --preflight) PREFLIGHT_FILE="$2"; shift 2 ;;
    --plan-file) PLAN_FILE="$2"; shift 2 ;;
    --goal) GOAL="$2"; shift 2 ;;
    --intent) INTENT="$2"; shift 2 ;;
    --profile) PLAN_PROFILE="$2"; shift 2 ;;
    --timeout-ms) TIMEOUT_MS="$2"; shift 2 ;;
    --skip-preflight) SKIP_PREFLIGHT=true; shift ;;
    --context-pack) CONTEXT_PACK="$2"; shift 2 ;;
    --impl-report) IMPL_REPORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      log_error "Unknown argument: $1"
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$MODE" ]]; then
  log_error "--mode is required"
  usage
  exit 2
fi

if [[ -z "$PLAN_DIR" ]]; then
  PLAN_DIR=".tmp/agent-collab/${TASK_ID}/plan"
fi
if [[ -z "$TASK_DIR" ]]; then
  TASK_DIR=".tmp/agent-collab/${TASK_ID}/task"
fi
if [[ -z "$REVIEW_DIR" ]]; then
  REVIEW_DIR=".tmp/agent-collab/${TASK_ID}/review"
fi

if [[ -n "$TIMEOUT_MS" && ! "$TIMEOUT_MS" =~ ^[0-9]+$ ]]; then
  log_error "--timeout-ms must be a non-negative integer (got: ${TIMEOUT_MS})"
  exit 2
fi

run_plan_stage() {
  if [[ -z "$PREFLIGHT_FILE" ]]; then
    log_error "--preflight is required for mode=${MODE}"
    exit 2
  fi
  if [[ ! -s "$PREFLIGHT_FILE" ]]; then
    log_error "Preflight file missing or empty: ${PREFLIGHT_FILE}"
    exit 1
  fi

  mkdir -p "$PLAN_DIR"
  cp "$PREFLIGHT_FILE" "${PLAN_DIR}/preflight.md"

  local cmd=("${SCRIPT_DIR}/run_plan_pipeline.sh" --task-dir "$PLAN_DIR")
  if [[ -n "$PLAN_PROFILE" ]]; then
    cmd+=(--profile "$PLAN_PROFILE")
  fi
  if [[ -n "$TIMEOUT_MS" ]]; then
    cmd+=(--timeout-ms "$TIMEOUT_MS")
  fi
  if [[ "$SKIP_PREFLIGHT" == "true" ]]; then
    cmd+=(--skip-preflight)
  fi

  log_info "Running plan pipeline..."
  "${cmd[@]}"

  PLAN_FILE="${PLAN_DIR}/final.md"
  if [[ ! -s "$PLAN_FILE" ]]; then
    log_error "Plan pipeline finished but final plan is missing: ${PLAN_FILE}"
    exit 1
  fi
  log_ok "Plan complete: ${PLAN_FILE}"
}

bootstrap_task_from_plan() {
  if [[ -z "$PLAN_FILE" ]]; then
    log_error "--plan-file is required to bootstrap implementation task"
    exit 2
  fi
  if [[ ! -s "$PLAN_FILE" ]]; then
    log_error "Plan file missing or empty: ${PLAN_FILE}"
    exit 1
  fi
  if [[ -z "$GOAL" ]]; then
    log_error "--goal is required when bootstrapping from plan file"
    exit 2
  fi

  log_info "Bootstrapping Task Packet from plan..."
  "${SCRIPT_DIR}/plan_to_task_packet.sh" \
    --plan-file "$PLAN_FILE" \
    --task-dir "$TASK_DIR" \
    --goal "$GOAL" \
    --intent "$INTENT"
}

run_impl_stage() {
  if [[ -f "${TASK_DIR}/manifest.yaml" && -z "$PLAN_FILE" ]]; then
    log_info "Using existing task packet: ${TASK_DIR}"
  else
    bootstrap_task_from_plan
  fi

  log_info "Running implementation pipeline..."
  "${SCRIPT_DIR}/dispatch.sh" pipeline --task "$TASK_DIR" --plan auto
  log_ok "Implementation complete: ${TASK_DIR}/outputs/_summary.md"
}

resolve_review_inputs_from_task() {
  local outputs_dir="${TASK_DIR}/outputs"

  if [[ -z "$CONTEXT_PACK" ]]; then
    local candidate_context="${TASK_DIR}/inputs/context_pack.md"
    if [[ -s "$candidate_context" ]]; then
      CONTEXT_PACK="$candidate_context"
    fi
  fi

  if [[ -z "$IMPL_REPORT" && -d "$outputs_dir" ]]; then
    local candidates=(
      "${outputs_dir}/codex_impl.codex.out"
      "${outputs_dir}/copilot_runbook.copilot.out"
      "${outputs_dir}/codex_test_impl.codex.out"
    )
    local c=""
    for c in "${candidates[@]}"; do
      if [[ -s "$c" ]]; then
        IMPL_REPORT="$c"
        break
      fi
    done
  fi
}

run_review_stage() {
  resolve_review_inputs_from_task

  if [[ -z "$CONTEXT_PACK" ]]; then
    log_error "Review requires --context-pack or a task dir containing inputs/context_pack.md"
    exit 2
  fi
  if [[ -z "$IMPL_REPORT" ]]; then
    log_error "Review requires --impl-report or a task dir containing implementation outputs"
    exit 2
  fi
  if [[ ! -s "$CONTEXT_PACK" ]]; then
    log_error "Context pack missing or empty: ${CONTEXT_PACK}"
    exit 1
  fi
  if [[ ! -s "$IMPL_REPORT" ]]; then
    log_error "Implementation report missing or empty: ${IMPL_REPORT}"
    exit 1
  fi

  log_info "Running post-implementation review..."
  "${SCRIPT_DIR}/post_impl_review.sh" "$CONTEXT_PACK" "$IMPL_REPORT" "$REVIEW_DIR"
  log_ok "Review complete: ${REVIEW_DIR}/summary.md"
}

case "$MODE" in
  plan)
    run_plan_stage
    ;;
  impl)
    run_impl_stage
    ;;
  review)
    run_review_stage
    ;;
  all)
    run_plan_stage
    run_impl_stage
    run_review_stage
    ;;
  *)
    log_error "Invalid mode: ${MODE} (expected: plan|impl|review|all)"
    exit 2
    ;;
esac

log_info "Run id: ${TASK_ID}"
if [[ -f "${PLAN_DIR}/final.md" ]]; then
  log_info "Plan output: ${PLAN_DIR}/final.md"
fi
if [[ -f "${TASK_DIR}/outputs/_summary.md" ]]; then
  log_info "Impl summary: ${TASK_DIR}/outputs/_summary.md"
fi
if [[ -f "${REVIEW_DIR}/summary.md" ]]; then
  log_info "Review summary: ${REVIEW_DIR}/summary.md"
fi
