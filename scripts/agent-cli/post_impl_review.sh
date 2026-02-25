#!/usr/bin/env bash
# post_impl_review.sh — Run post-implementation review/verification pipeline
#
# Usage:
#   post_impl_review.sh <context-pack-path> <impl-report-path> [output-dir]
#
# Outputs:
#   <output-dir>/gemini_review.md
#   <output-dir>/test_matrix.md
#   <output-dir>/verification_checklist.md
#   <output-dir>/codex_precision_review.md
#   <output-dir>/test_implementation_report.md
#   <output-dir>/verification_report.md
#   <output-dir>/summary.md
#
# Exit codes:
#   0  Success
#   1  Failure
#   2  Bad arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/log.sh"

usage() {
	cat <<'EOF'
Usage:
  post_impl_review.sh <context-pack-path> <impl-report-path> [output-dir]

Example:
  ./scripts/agent-cli/post_impl_review.sh \
    .tmp/task/20260218-001/inputs/context_pack.md \
    .tmp/task/20260218-001/outputs/codex_impl.codex.out \
    .tmp/post-impl
EOF
}

CONTEXT_PACK="${1-}"
IMPL_REPORT="${2-}"
OUTPUT_DIR="${3:-.tmp/post-impl}"
REVIEW_PROFILE="${4:-post_impl_review}"

if [[ -z $CONTEXT_PACK || -z $IMPL_REPORT ]]; then
	usage
	exit 2
fi

case "$REVIEW_PROFILE" in
post_impl_review | review_cross | review_only | codex_only) ;;
*)
	log_error "Unknown review profile: ${REVIEW_PROFILE} (expected: post_impl_review|review_cross|review_only|codex_only)"
	exit 2
	;;
esac
if [[ ! -s $CONTEXT_PACK ]]; then
	log_error "Context pack missing or empty: ${CONTEXT_PACK}"
	exit 1
fi
if [[ ! -s $IMPL_REPORT ]]; then
	log_error "Implementation report missing or empty: ${IMPL_REPORT}"
	exit 1
fi

TASK_ID="post-impl-$(date +%Y%m%d-%H%M%S)"
TASK_DIR="${OUTPUT_DIR}/task-${TASK_ID}"
INPUTS_DIR="${TASK_DIR}/inputs"
ATTACH_DIR="${INPUTS_DIR}/attachments"
OUTPUTS_DIR="${TASK_DIR}/outputs"
STATE_DIR="${TASK_DIR}/state"
DONE_DIR="${TASK_DIR}/done"

mkdir -p "$ATTACH_DIR" "$OUTPUTS_DIR" "$STATE_DIR" "$DONE_DIR"

cp "$CONTEXT_PACK" "${INPUTS_DIR}/context_pack.md"
cp "$IMPL_REPORT" "${ATTACH_DIR}/implementation_report.md"

cat >"${INPUTS_DIR}/user_request.md" <<'EOF'
Run a strict post-implementation review and verification workflow.

Primary artifact:
- inputs/attachments/implementation_report.md

Required outputs:
1. Wide review findings (design, risk, compatibility)
2. Test matrix and failure triage order
3. Static verification checklist and rollback plan
4. Precision review for high-reliability zones
5. Minimal test implementation proposal (diff when needed)
6. Dynamic verification report
EOF

ACCEPTANCE_COMMANDS_BLOCK=$(
	python3 - "${INPUTS_DIR}/context_pack.md" <<'PYEOF'
import json
import re
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8", errors="replace") as f:
    lines = f.read().splitlines()

in_verify_heading = False
in_code_block = False
commands = []
fence = chr(96) * 3

for line in lines:
    heading = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
    if heading:
        title = heading.group(1).strip().lower()
        if title == "verify commands":
            in_verify_heading = True
            in_code_block = False
            continue
        if in_verify_heading and not in_code_block:
            break
    if not in_verify_heading:
        continue
    if line.strip().startswith(fence):
        if not in_code_block:
            in_code_block = True
            continue
        break
    if in_code_block:
        cmd = line.strip()
        if cmd and not cmd.startswith("#"):
            commands.append(cmd)

if not commands:
    print("  commands: []")
else:
    print("  commands:")
    for cmd in commands:
        print(f"    - {json.dumps(cmd, ensure_ascii=False)}")
PYEOF
)

cat >"${TASK_DIR}/manifest.yaml" <<EOF
task_id: "${TASK_ID}"
goal: "Post-implementation review and verification"

routing:
  intent: ${REVIEW_PROFILE}

scope:
  allow:
    - src/
    - tests/
    - scripts/
    - docs/
    - prompts-src/
  deny:
    - .env
    - secrets/

acceptance:
${ACCEPTANCE_COMMANDS_BLOCK}
  criteria:
    - "All post-implementation artifacts are generated"

budgets:
  retry_budget: 2
  paid_call_budget: 12
  max_wallclock_sec: 900

context:
  digest_policy: auto

security:
  redaction_patterns: []
  forbidden_paths:
    - ".env"
    - "secrets/"
EOF

if [[ $ACCEPTANCE_COMMANDS_BLOCK == "  commands: []" ]]; then
	log_warn "No Verify Commands found in context pack; codex_verify gate commands will be skipped."
fi

log_info "Running post-implementation pipeline in ${TASK_DIR}"
"${SCRIPT_DIR}/dispatch.sh" pipeline --task "$TASK_DIR" --plan auto

declare -a ARTIFACT_MAP=()
case "$REVIEW_PROFILE" in
post_impl_review)
	ARTIFACT_MAP=(
		"${OUTPUTS_DIR}/gemini_review.gemini.out:${OUTPUT_DIR}/gemini_review.md"
		"${OUTPUTS_DIR}/gemini_test_design.gemini.out:${OUTPUT_DIR}/test_matrix.md"
		"${OUTPUTS_DIR}/gemini_static_verify.gemini.out:${OUTPUT_DIR}/verification_checklist.md"
		"${OUTPUTS_DIR}/codex_review.codex.out:${OUTPUT_DIR}/codex_precision_review.md"
		"${OUTPUTS_DIR}/codex_test_impl.codex.out:${OUTPUT_DIR}/test_implementation_report.md"
		"${OUTPUTS_DIR}/codex_verify.codex.out:${OUTPUT_DIR}/verification_report.md"
	)
	;;
review_cross)
	ARTIFACT_MAP=(
		"${OUTPUTS_DIR}/gemini_review.gemini.out:${OUTPUT_DIR}/gemini_review.md"
		"${OUTPUTS_DIR}/codex_review.codex.out:${OUTPUT_DIR}/codex_precision_review.md"
		"${OUTPUTS_DIR}/copilot_review_consolidate.copilot.out:${OUTPUT_DIR}/review_consolidated.md"
	)
	;;
review_only)
	ARTIFACT_MAP=(
		"${OUTPUTS_DIR}/gemini_review.gemini.out:${OUTPUT_DIR}/gemini_review.md"
	)
	;;
codex_only)
	ARTIFACT_MAP=(
		"${OUTPUTS_DIR}/codex_review.codex.out:${OUTPUT_DIR}/codex_precision_review.md"
		"${OUTPUTS_DIR}/codex_verify.codex.out:${OUTPUT_DIR}/verification_report.md"
	)
	;;
esac

for pair in "${ARTIFACT_MAP[@]}"; do
	src="${pair%%:*}"
	dst="${pair##*:}"
	if [[ ! -s $src ]]; then
		log_error "Expected artifact missing or empty: ${src}"
		exit 1
	fi
	cp "$src" "$dst"
done

if [[ -f "${OUTPUTS_DIR}/_summary.md" ]]; then
	cp "${OUTPUTS_DIR}/_summary.md" "${OUTPUT_DIR}/dispatch_summary.md"
fi

# Write summary.md: use consolidated output if available, else template
case "$REVIEW_PROFILE" in
review_cross)
	if [[ -s "${OUTPUT_DIR}/review_consolidated.md" ]]; then
		cp "${OUTPUT_DIR}/review_consolidated.md" "${OUTPUT_DIR}/summary.md"
	fi
	;;
review_only)
	if [[ -s "${OUTPUT_DIR}/gemini_review.md" ]]; then
		cp "${OUTPUT_DIR}/gemini_review.md" "${OUTPUT_DIR}/summary.md"
	fi
	;;
codex_only)
	if [[ -s "${OUTPUT_DIR}/codex_precision_review.md" ]]; then
		cp "${OUTPUT_DIR}/codex_precision_review.md" "${OUTPUT_DIR}/summary.md"
	fi
	;;
esac

if [[ ! -s "${OUTPUT_DIR}/summary.md" ]]; then
	cat >"${OUTPUT_DIR}/summary.md" <<EOF
# Post-Implementation Review Summary

Profile: ${REVIEW_PROFILE}
Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Task dir: ${TASK_DIR}

## Artifacts

$(for pair in "${ARTIFACT_MAP[@]}"; do echo "- ${pair##*:}"; done)

## Notes

- Raw stage logs and metadata are preserved under: ${TASK_DIR}/outputs
- Dispatcher summary (if available): ${OUTPUT_DIR}/dispatch_summary.md
EOF
fi

log_ok "Post-implementation review complete: ${OUTPUT_DIR}/summary.md"
exit 0
