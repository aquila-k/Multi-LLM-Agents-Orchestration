#!/usr/bin/env bash
# wait_parallel_tasks.sh — Monitor and wait for parallel wrapper tasks to complete
#
# Usage:
#   wait_parallel_tasks.sh \
#     --label <label> \
#     --timeout <seconds> \
#     --task-1-done <path> --task-1-pid <path> --task-1-out <path> \
#     --task-2-done <path> --task-2-pid <path> --task-2-out <path> \
#     [--task-3-done ... --task-4-done ...]
#     [--min-lines <n>]
#
# Completion detection priority (per task):
#   1. done-marker file exists
#   2. PID file's process no longer running (and done-marker still absent → FAILURE)
#   3. Timeout (skipped when --timeout is 0 or negative)
#
# Exit codes:
#   0  All tasks completed successfully (done-markers present, min-lines satisfied)
#   1  One or more tasks failed or timed out
#   2  Bad arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
source "${LIB_DIR}/log.sh"

LABEL="parallel"
TIMEOUT=300
MIN_LINES=0
POLL_INTERVAL=5
PROGRESS_INTERVAL="${AGENT_CLI_PROGRESS_INTERVAL_SEC:-10}"

# Parallel task arrays (supports up to 4 tasks)
declare -a TASK_DONE=()
declare -a TASK_PID=()
declare -a TASK_OUT=()

# Parse arguments
idx=-1
while [[ $# -gt 0 ]]; do
	case "$1" in
	--label)
		LABEL="$2"
		shift 2
		;;
	--timeout)
		TIMEOUT="$2"
		shift 2
		;;
	--min-lines)
		MIN_LINES="$2"
		shift 2
		;;
	--task-1-done)
		TASK_DONE[0]="$2"
		shift 2
		;;
	--task-1-pid)
		TASK_PID[0]="$2"
		shift 2
		;;
	--task-1-out)
		TASK_OUT[0]="$2"
		shift 2
		;;
	--task-2-done)
		TASK_DONE[1]="$2"
		shift 2
		;;
	--task-2-pid)
		TASK_PID[1]="$2"
		shift 2
		;;
	--task-2-out)
		TASK_OUT[1]="$2"
		shift 2
		;;
	--task-3-done)
		TASK_DONE[2]="$2"
		shift 2
		;;
	--task-3-pid)
		TASK_PID[2]="$2"
		shift 2
		;;
	--task-3-out)
		TASK_OUT[2]="$2"
		shift 2
		;;
	--task-4-done)
		TASK_DONE[3]="$2"
		shift 2
		;;
	--task-4-pid)
		TASK_PID[3]="$2"
		shift 2
		;;
	--task-4-out)
		TASK_OUT[3]="$2"
		shift 2
		;;
	*)
		log_warn "Unknown argument: $1"
		shift
		;;
	esac
done

TASK_COUNT=${#TASK_DONE[@]}
if [[ $TASK_COUNT -eq 0 ]]; then
	log_error "No tasks specified (use --task-1-done etc.)"
	exit 2
fi

if ((TIMEOUT > 0)); then
	log_info "[${LABEL}] Waiting for ${TASK_COUNT} task(s), timeout=${TIMEOUT}s, min-lines=${MIN_LINES}"
else
	log_info "[${LABEL}] Waiting for ${TASK_COUNT} task(s), timeout=none, min-lines=${MIN_LINES}"
fi

# Track completion status per task
declare -a TASK_STATUS=()
for ((i = 0; i < TASK_COUNT; i++)); do
	TASK_STATUS[$i]="pending"
done

ELAPSED=0
OVERALL_FAILED=0

while true; do
	ALL_DONE=true

	for ((i = 0; i < TASK_COUNT; i++)); do
		[[ ${TASK_STATUS[$i]} != "pending" ]] && continue

		done_file="${TASK_DONE[$i]-}"
		pid_file="${TASK_PID[$i]-}"
		out_file="${TASK_OUT[$i]-}"
		task_label="task-$((i + 1))"

		# Priority 1: done-marker exists
		if [[ -n $done_file && -f $done_file ]]; then
			# Verify output has minimum lines
			if [[ $MIN_LINES -gt 0 && -n $out_file && -f $out_file ]]; then
				actual_lines=$(wc -l <"$out_file" | tr -d ' ')
				if ((actual_lines < MIN_LINES)); then
					log_error "[${LABEL}] ${task_label}: output too short (${actual_lines} < ${MIN_LINES} lines)"
					TASK_STATUS[$i]="failed"
					OVERALL_FAILED=1
					continue
				fi
			fi
			log_ok "[${LABEL}] ${task_label}: done"
			TASK_STATUS[$i]="done"
			continue
		fi

		# Priority 2: PID no longer running (without done-marker = failure)
		if [[ -n $pid_file && -f $pid_file ]]; then
			pid=$(cat "$pid_file" 2>/dev/null || echo "")
			if [[ -n $pid ]] && ! kill -0 "$pid" 2>/dev/null; then
				log_error "[${LABEL}] ${task_label}: process ${pid} died without done-marker"
				TASK_STATUS[$i]="failed"
				OVERALL_FAILED=1
				continue
			fi
		fi

		ALL_DONE=false
	done

	if [[ $ALL_DONE == "true" ]]; then
		break
	fi

	if ((TIMEOUT > 0 && ELAPSED >= TIMEOUT)); then
		log_error "[${LABEL}] TIMEOUT after ${TIMEOUT}s"
		OVERALL_FAILED=1
		break
	fi

	sleep $POLL_INTERVAL
	ELAPSED=$((ELAPSED + POLL_INTERVAL))
	if ((PROGRESS_INTERVAL > 0)) && ((ELAPSED % PROGRESS_INTERVAL == 0)); then
		log_info "[${LABEL}] running (${ELAPSED}s)"
	fi
done

# Summary
DONE_COUNT=0
FAIL_COUNT=0
for ((i = 0; i < TASK_COUNT; i++)); do
	case "${TASK_STATUS[$i]}" in
	done) DONE_COUNT=$((DONE_COUNT + 1)) ;;
	failed) FAIL_COUNT=$((FAIL_COUNT + 1)) ;;
	pending)
		FAIL_COUNT=$((FAIL_COUNT + 1))
		log_error "[${LABEL}] task-$((i + 1)): still pending (timed out)"
		;;
	esac
done

log_info "[${LABEL}] Results: ${DONE_COUNT} done, ${FAIL_COUNT} failed"

if [[ $OVERALL_FAILED -eq 0 ]]; then
	log_ok "[${LABEL}] All tasks completed successfully"
	exit 0
else
	log_error "[${LABEL}] One or more tasks failed"
	exit 1
fi
