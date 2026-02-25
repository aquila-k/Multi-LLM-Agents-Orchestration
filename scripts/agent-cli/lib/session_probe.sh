#!/usr/bin/env bash
# session_probe.sh — Capability probe for tool-level session/resume support
# Usage: source this file

set -euo pipefail

SESSION_PROBE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SESSION_PROBE_LIB_DIR}/log.sh"
source "${SESSION_PROBE_LIB_DIR}/atomic.sh"

# ── Internal helper ────────────────────────────────────────────────────────────

_session_probe_write() {
	local out_file="$1"
	local tool="$2"
	local binary_found="$3"
	local binary_path="$4"
	local resume_supported="$5"
	local id_source="$6"
	local notes="$7"

	mkdir -p "$(dirname "$out_file")"

	python3 - "$out_file" "$tool" "$binary_found" "$binary_path" \
		"$resume_supported" "$id_source" "$notes" <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone

out_file, tool, binary_found, binary_path, resume_supported, id_source, notes = sys.argv[1:]

data = {
    "tool": tool,
    "resume_supported": resume_supported == "true",
    "id_source": id_source,
    "probe_ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "binary_found": binary_found == "true",
    "binary_path": binary_path,
    "notes": notes,
}

tmp = out_file + ".partial"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(tmp, out_file)
PYEOF
}

# ── Per-tool probes ────────────────────────────────────────────────────────────

session_probe_codex() {
	local task_root="$1"
	local probe_dir="${task_root}/state/session-probe"
	local out_file="${probe_dir}/codex.json"

	local binary_path="" binary_found="false"
	local resume_supported="false" id_source="unknown" notes=""

	binary_path=$(command -v codex 2>/dev/null || true)
	if [[ -n $binary_path ]]; then
		binary_found="true"
		# Check that 'codex resume' subcommand is available
		if codex resume --help >/dev/null 2>&1; then
			resume_supported="true"
			id_source="state_dir"
		else
			notes="codex resume subcommand returned non-zero"
		fi
	else
		notes="codex binary not found in PATH"
	fi

	_session_probe_write "$out_file" "codex" "$binary_found" \
		"$binary_path" "$resume_supported" "$id_source" "$notes"
}

session_probe_copilot() {
	local task_root="$1"
	local probe_dir="${task_root}/state/session-probe"
	local out_file="${probe_dir}/copilot.json"

	local binary_path="" binary_found="false"
	local resume_supported="false" id_source="unknown" notes=""

	binary_path=$(command -v copilot 2>/dev/null || true)
	if [[ -n $binary_path ]]; then
		binary_found="true"
		# Check that --resume flag exists in help output
		if copilot --help 2>&1 | grep -q -- '--resume'; then
			resume_supported="true"
			id_source="state_dir"
		else
			notes="--resume flag not found in copilot --help output"
		fi
	else
		notes="copilot binary not found in PATH"
	fi

	_session_probe_write "$out_file" "copilot" "$binary_found" \
		"$binary_path" "$resume_supported" "$id_source" "$notes"
}

session_probe_gemini() {
	local task_root="$1"
	local probe_dir="${task_root}/state/session-probe"
	local out_file="${probe_dir}/gemini.json"

	local binary_path="" binary_found="false"
	local resume_supported="false" id_source="unknown" notes=""

	binary_path=$(command -v gemini 2>/dev/null || true)
	if [[ -n $binary_path ]]; then
		binary_found="true"
		# Check that --resume flag exists in help output
		if gemini --help 2>&1 | grep -q -- '--resume'; then
			resume_supported="true"
			id_source="stream_json_init"
			notes="session_id obtained from init event in --output-format stream-json"
		else
			notes="--resume flag not found in gemini --help output"
		fi
	else
		notes="gemini binary not found in PATH"
	fi

	_session_probe_write "$out_file" "gemini" "$binary_found" \
		"$binary_path" "$resume_supported" "$id_source" "$notes"
}

session_probe_run_all() {
	local task_root="$1"
	local probe_dir="${task_root}/state/session-probe"
	mkdir -p "$probe_dir"

	# Run probes; each writes its own JSON and is independent
	session_probe_codex "$task_root" || log_warn "session_probe_codex failed"
	session_probe_copilot "$task_root" || log_warn "session_probe_copilot failed"
	session_probe_gemini "$task_root" || log_warn "session_probe_gemini failed"
}

session_probe_resume_supported() {
	local task_root="$1"
	local tool="$2"
	local path="${task_root}/state/session-probe/${tool}.json"

	if [[ ! -f $path ]]; then
		echo "false"
		return 0
	fi

	python3 - "$path" <<'PYEOF'
import json, sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

if isinstance(data, dict) and data.get("resume_supported") is True:
    print("true")
else:
    print("false")
PYEOF
}
