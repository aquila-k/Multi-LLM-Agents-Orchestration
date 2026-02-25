#!/usr/bin/env bash
# task_paths.sh — Canonical task root path resolution
# Usage: source this file
#
# Canonical task root: .tmp/task/<task-name>/
# Fallback (read-only): .tmp/agent-collab/tasks/<task-name>/
#                       .tmp/agent-collab/<task-id>/{plan,task,review}
#
# Rules:
# - All new writes go to canonical root ONLY
# - Old roots are referenced as read-fallback only
# - task-name: 16-72 chars, lowercase alphanum + hyphen, no leading/trailing hyphen

set -euo pipefail

# ── Canonical path builders ────────────────────────────────────────────────────

# task_path_root <task-name> [repo-root]
# Returns: .tmp/task/<task-name>
task_path_root() {
	local task_name="$1"
	local repo_root="${2:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
	echo "${repo_root}/.tmp/task/${task_name}"
}

# task_path_plan <task-name> [repo-root]
task_path_plan() {
	echo "$(task_path_root "$@")/plan"
}

# task_path_impl <task-name> [repo-root]
task_path_impl() {
	echo "$(task_path_root "$@")/impl"
}

# task_path_review <task-name> [repo-root]
task_path_review() {
	echo "$(task_path_root "$@")/review"
}

# task_path_state <task-name> [repo-root]
task_path_state() {
	echo "$(task_path_root "$@")/state"
}

# task_path_sessions <task-name> [repo-root]
task_path_sessions() {
	echo "$(task_path_root "$@")/sessions"
}

# ── Task name validation ───────────────────────────────────────────────────────

# task_name_valid <task-name>
# Returns 0 if valid, 1 if invalid
# Rule: 16-72 chars, lowercase alphanum + hyphen, no leading/trailing hyphen
task_name_valid() {
	local name="$1"
	local len="${#name}"
	if ((len < 16 || len > 72)); then
		return 1
	fi
	if [[ ! $name =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$ ]]; then
		return 1
	fi
	return 0
}

# task_name_generate [prefix]
# Generates a canonical task name: task-YYYYMMDD-HHMMSS (19 chars)
task_name_generate() {
	local prefix="${1:-task}"
	echo "${prefix}-$(date -u +"%Y%m%d-%H%M%S")"
}

# ── Fallback path search ───────────────────────────────────────────────────────

# task_path_find_existing <task-name> [repo-root]
# Searches canonical root first, then fallback roots.
# Prints the found path or nothing if not found.
# Emits a warning if a fallback path is used.
task_path_find_existing() {
	local task_name="$1"
	local repo_root="${2:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

	# 1. Canonical
	local canonical="${repo_root}/.tmp/task/${task_name}"
	if [[ -d $canonical ]]; then
		echo "$canonical"
		return 0
	fi

	# 2. Legacy: .tmp/agent-collab/tasks/<task-name>
	local legacy1="${repo_root}/.tmp/agent-collab/tasks/${task_name}"
	if [[ -d $legacy1 ]]; then
		echo "WARNING: using legacy path (read-only): ${legacy1}" >&2
		echo "$legacy1"
		return 0
	fi

	return 1
}

# task_path_ensure <task-name> [repo-root]
# Ensures the canonical task root and sub-directories exist.
# Prints the canonical root path.
task_path_ensure() {
	local task_name="$1"
	local repo_root="${2:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
	local root="${repo_root}/.tmp/task/${task_name}"

	mkdir -p \
		"${root}/plan" \
		"${root}/impl" \
		"${root}/review" \
		"${root}/state" \
		"${root}/sessions/plan" \
		"${root}/sessions/impl" \
		"${root}/sessions/review" \
		"${root}/state/session-probe" \
		"${root}/state/session-validation"

	touch "${root}/state/session-events.jsonl"
	echo "$root"
}
