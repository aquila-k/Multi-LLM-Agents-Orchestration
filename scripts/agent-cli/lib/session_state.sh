#!/usr/bin/env bash
# session_state.sh — Session/task state management utilities
# Usage: source this file

set -euo pipefail

SESSION_STATE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SESSION_STATE_LIB_DIR}/log.sh"
source "${SESSION_STATE_LIB_DIR}/atomic.sh"

session_state_iso_now() {
	date -u +"%Y-%m-%dT%H:%M:%SZ"
}

session_state_ensure_task_layout() {
	local task_root="$1"
	mkdir -p "${task_root}/sessions/plan" \
		"${task_root}/sessions/impl" \
		"${task_root}/sessions/review" \
		"${task_root}/state/session-validation" \
		"${task_root}/state/session-probe"
	touch "${task_root}/state/session-events.jsonl"
}

session_state_init_task_index() {
	local task_root="$1"
	local task_name="$2"
	local run_id="$3"
	local run_mode="$4"
	local phase_session_mode="$5"
	local cross_phase_resume="$6"

	session_state_ensure_task_layout "$task_root"

	python3 - "$task_root" "$task_name" "$run_id" "$run_mode" "$phase_session_mode" "$cross_phase_resume" <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone

task_root, task_name, run_id, run_mode, phase_session_mode, cross_phase_resume = sys.argv[1:]
cross_phase_resume_bool = cross_phase_resume.lower() == "true"
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

index_path = os.path.join(task_root, "task-index.json")
if os.path.isfile(index_path):
    with open(index_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            data = {}
else:
    data = {}

if not isinstance(data, dict):
    data = {}

data.setdefault("task_name", task_name)
data.setdefault("created_at", now)
data["updated_at"] = now
data["latest_run_id"] = run_id
data.setdefault("runs", [])
data.setdefault("sessions", {"plan": {}, "impl": {}, "review": {}})
data.setdefault("policies", {})
data["policies"]["phase_session_mode_default"] = phase_session_mode
data["policies"]["cross_phase_resume_default"] = cross_phase_resume_bool

run_exists = False
for run in data["runs"]:
    if isinstance(run, dict) and run.get("run_id") == run_id:
        run_exists = True
        run["updated_at"] = now
        break

if not run_exists:
    data["runs"].append(
        {
            "run_id": run_id,
            "mode": run_mode,
            "phase_session_mode": phase_session_mode,
            "cross_phase_resume": cross_phase_resume_bool,
            "status": "running",
            "started_at": now,
            "updated_at": now,
        }
    )

tmp = index_path + ".partial"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp, index_path)
PYEOF
}

session_state_mark_run_status() {
	local task_root="$1"
	local run_id="$2"
	local status="$3"

	python3 - "$task_root" "$run_id" "$status" <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone

task_root, run_id, status = sys.argv[1:]
index_path = os.path.join(task_root, "task-index.json")
if not os.path.isfile(index_path):
    sys.exit(0)

with open(index_path, "r", encoding="utf-8") as f:
    try:
        data = json.load(f)
    except Exception:
        sys.exit(0)

if not isinstance(data, dict):
    sys.exit(0)

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
data["updated_at"] = now

for run in data.get("runs", []):
    if isinstance(run, dict) and run.get("run_id") == run_id:
        run["status"] = status
        run["updated_at"] = now
        if status in {"success", "failed"}:
            run["ended_at"] = now
        break

tmp = index_path + ".partial"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp, index_path)
PYEOF
}

session_state_record_path() {
	local task_root="$1"
	local phase="$2"
	local tool="$3"
	echo "${task_root}/sessions/${phase}/${tool}.json"
}

session_state_get_phase_tool_session() {
	local task_root="$1"
	local phase="$2"
	local tool="$3"
	local field="${4-}"
	local path
	path="$(session_state_record_path "$task_root" "$phase" "$tool")"
	[[ -f $path ]] || return 1

	python3 - "$path" "$field" <<'PYEOF'
import json
import sys

path, field = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data, dict):
    sys.exit(1)

if field:
    if field not in data:
        sys.exit(1)
    value = data[field]
else:
    value = data

if isinstance(value, bool):
    print("true" if value else "false")
elif isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
elif value is None:
    sys.exit(1)
else:
    print(value)
PYEOF
}

session_state_set_phase_tool_session() {
	local task_root="$1"
	local phase="$2"
	local tool="$3"
	local session_id="$4"
	local source="$5"
	local confidence="$6"
	local status="$7"

	session_state_ensure_task_layout "$task_root"

	python3 - "$task_root" "$phase" "$tool" "$session_id" "$source" "$confidence" "$status" <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone

task_root, phase, tool, session_id, source, confidence, status = sys.argv[1:]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

record_path = os.path.join(task_root, "sessions", phase, f"{tool}.json")
os.makedirs(os.path.dirname(record_path), exist_ok=True)

record = {}
if os.path.isfile(record_path):
    with open(record_path, "r", encoding="utf-8") as f:
        try:
            record = json.load(f)
        except Exception:
            record = {}
if not isinstance(record, dict):
    record = {}

created_at = record.get("created_at", now)
record.update(
    {
        "tool": tool,
        "phase": phase,
        "session_id": session_id,
        "source": source,
        "confidence": confidence,
        "status": status,
        "created_at": created_at,
        "updated_at": now,
        "last_used_at": now,
    }
)

tmp = record_path + ".partial"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(record, f, ensure_ascii=False, indent=2)
os.replace(tmp, record_path)

index_path = os.path.join(task_root, "task-index.json")
if os.path.isfile(index_path):
    with open(index_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            data = {}
else:
    data = {}

if not isinstance(data, dict):
    data = {}

data.setdefault("sessions", {"plan": {}, "impl": {}, "review": {}})
data["sessions"].setdefault(phase, {})
data["sessions"][phase][tool] = {
    "session_id": session_id,
    "source": source,
    "confidence": confidence,
    "status": status,
    "updated_at": now,
}
data["updated_at"] = now

tmp_index = index_path + ".partial"
with open(tmp_index, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp_index, index_path)
PYEOF
}

session_state_probe_field() {
	local task_root="$1"
	local tool="$2"
	local field="$3"
	local path="${task_root}/state/session-probe/${tool}.json"
	[[ -f $path ]] || return 1

	python3 - "$path" "$field" <<'PYEOF'
import json
import sys

path, field = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data, dict):
    sys.exit(1)

if field not in data:
    sys.exit(1)

value = data[field]
if isinstance(value, bool):
    print("true" if value else "false")
elif isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
elif value is None:
    sys.exit(1)
else:
    print(value)
PYEOF
}

session_state_validation_policy_allows_resume() {
	local task_root="$1"
	local phase="$2"
	local tool="$3"

	if [[ ${AGENT_CLI_SESSION_ALLOW_UNVALIDATED:-0} == "1" ]]; then
		echo "true"
		return 0
	fi

	local path="${task_root}/state/session-validation/policy.json"
	if [[ ! -f $path ]]; then
		echo "false"
		return 0
	fi

	python3 - "$path" "$phase" "$tool" <<'PYEOF'
import json
import sys

path, phase, tool = sys.argv[1:]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data, dict):
    print("false")
    sys.exit(0)

default_enabled = bool(data.get("default_enabled", False))
phases = data.get("phases", {})
if isinstance(phases, dict):
    phase_map = phases.get(phase, {})
    if isinstance(phase_map, dict) and tool in phase_map:
        print("true" if bool(phase_map.get(tool)) else "false")
        sys.exit(0)

print("true" if default_enabled else "false")
PYEOF
}

session_state_record_validation_result() {
	local task_root="$1"
	local phase="$2"
	local tool="$3"
	local event="$4"
	local ok="$5"
	local details="${6-}"
	local path="${task_root}/state/session-validation/${phase}-${tool}.jsonl"

	mkdir -p "$(dirname "$path")"
	python3 - "$path" "$phase" "$tool" "$event" "$ok" "$details" <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone

path, phase, tool, event, ok, details = sys.argv[1:]
row = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "phase": phase,
    "tool": tool,
    "event": event,
    "ok": ok.lower() == "true",
    "details": details,
}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
PYEOF
}

session_state_record_event() {
	local task_root="$1"
	local event="$2"
	local phase="$3"
	local tool="$4"
	local stage="$5"
	local status="$6"
	local details="${7-}"
	local path="${task_root}/state/session-events.jsonl"

	mkdir -p "$(dirname "$path")"
	python3 - "$path" "$event" "$phase" "$tool" "$stage" "$status" "$details" <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone

path, event, phase, tool, stage, status, details = sys.argv[1:]
row = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event": event,
    "phase": phase,
    "tool": tool,
    "stage": stage,
    "status": status,
    "details": details,
}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
PYEOF
}

session_state_write_recovery() {
	local state_dir="$1"
	local phase="$2"
	local tool="$3"
	local stage="$4"
	local reason="$5"
	local expected_id="${6-}"
	local actual_id="${7-}"
	local resume_target="${8-}"

	mkdir -p "$state_dir"
	local out_file="${state_dir}/session_recovery.md"
	cat >"${out_file}.partial" <<EOF
# Session Recovery Required

Generated: $(session_state_iso_now)
Phase: ${phase}
Tool: ${tool}
Stage: ${stage}

## Reason

${reason}

## Session Values

- Expected session ID: ${expected_id:-<none>}
- Actual session ID: ${actual_id:-<none>}
- Resume target: ${resume_target:-<none>}

## Recovery Procedure (Required)

1. Re-run capability probe and confirm \`resume_supported\` for this tool.
2. Re-detect session candidates and validate which ID is the correct continuation.
3. Update phase session record under \`.tmp/agent-collab/tasks/<task-name>/sessions/${phase}/${tool}.json\`.
4. Resume the same phase from the failed stage.
5. Do not continue with a fresh session for this phase unless policy is explicitly changed.
EOF
	atomic_write "${out_file}.partial" "$out_file"
}

session_state_json_field() {
	local file="$1"
	local field="$2"
	[[ -f $file ]] || return 1
	python3 - "$file" "$field" <<'PYEOF'
import json
import sys

path, field = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

value = data
for part in field.split("."):
    if isinstance(value, dict) and part in value:
        value = value[part]
    else:
        sys.exit(1)

if isinstance(value, bool):
    print("true" if value else "false")
elif isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
elif value is None:
    sys.exit(1)
else:
    print(value)
PYEOF
}

session_state_confidence_is_strong() {
	local confidence="${1-}"
	[[ $confidence == "high" || $confidence == "medium" ]]
}
