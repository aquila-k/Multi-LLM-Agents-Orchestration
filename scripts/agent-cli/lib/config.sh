#!/usr/bin/env bash
# config.sh — helpers to validate/resolve split config

set -euo pipefail

CONFIG_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_CLI_DIR="$(cd "${CONFIG_LIB_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${AGENT_CLI_DIR}/../.." && pwd)"

config_root_dir() {
  echo "${AGENT_CLI_CONFIG_ROOT:-${REPO_ROOT}/configs}"
}

config_sources_summary() {
  local root
  root="$(config_root_dir)"
  printf '%s\n' \
    "${root}/servant/codex.yaml" \
    "${root}/servant/gemini.yaml" \
    "${root}/servant/copilot.yaml" \
    "${root}/pipeline/impl-pipeline.yaml" \
    "${root}/pipeline/review-pipeline.yaml" \
    "${root}/pipeline/plan-pipeline.yaml"
}

config_snapshot_sync() {
  local root
  root="$(config_root_dir)"
  python3 "${CONFIG_LIB_DIR}/config_snapshot.py" --config-root "$root" >/dev/null
}

config_validate_global() {
  local root
  root="$(config_root_dir)"
  python3 "${CONFIG_LIB_DIR}/config_validate.py" --config-root "$root" >/dev/null
  config_snapshot_sync
}

config_validate_with_manifest() {
  local manifest_file="$1"
  local root
  root="$(config_root_dir)"
  python3 "${CONFIG_LIB_DIR}/config_validate.py" --config-root "$root" --manifest "$manifest_file" >/dev/null
  config_snapshot_sync
}

config_print_choices() {
  local root
  root="$(config_root_dir)"
  python3 "${CONFIG_LIB_DIR}/config_validate.py" --config-root "$root" --print-choices
}

resolve_dispatch_config() {
  local manifest_file="$1"
  local plan_name="$2"
  local intent_default="$3"
  local out_file="$4"
  local root
  root="$(config_root_dir)"
  config_snapshot_sync

  python3 "${CONFIG_LIB_DIR}/config_resolve.py" dispatch \
    --config-root "$root" \
    --manifest "$manifest_file" \
    --plan-name "$plan_name" \
    --intent-default "$intent_default" \
    > "${out_file}.partial"
  mv "${out_file}.partial" "$out_file"
}

resolve_plan_pipeline_config() {
  local out_file="$1"
  local profile="${2:-}"
  local copilot_model="${3:-}"
  local gemini_model="${4:-}"
  local codex_model="${5:-}"

  local root
  root="$(config_root_dir)"
  config_snapshot_sync

  local args=(
    plan
    --config-root "$root"
  )

  if [[ -n "$profile" ]]; then
    args+=(--profile "$profile")
  fi
  if [[ -n "$copilot_model" ]]; then
    args+=(--copilot-model "$copilot_model")
  fi
  if [[ -n "$gemini_model" ]]; then
    args+=(--gemini-model "$gemini_model")
  fi
  if [[ -n "$codex_model" ]]; then
    args+=(--codex-model "$codex_model")
  fi

  python3 "${CONFIG_LIB_DIR}/config_resolve.py" "${args[@]}" > "${out_file}.partial"
  mv "${out_file}.partial" "$out_file"
}

config_json_get() {
  local json_file="$1"
  local key_path="$2"
  python3 - "$json_file" "$key_path" <<'PYEOF'
import json
import sys

json_file = sys.argv[1]
path = sys.argv[2]

with open(json_file, "r", encoding="utf-8") as f:
    data = json.load(f)

value = data
for part in path.split('.'):
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

config_json_get_lines() {
  local json_file="$1"
  local key_path="$2"
  python3 - "$json_file" "$key_path" <<'PYEOF'
import json
import sys

json_file = sys.argv[1]
path = sys.argv[2]

with open(json_file, "r", encoding="utf-8") as f:
    data = json.load(f)

value = data
for part in path.split('.'):
    if isinstance(value, dict) and part in value:
        value = value[part]
    else:
        sys.exit(1)

if not isinstance(value, list):
    sys.exit(1)

for item in value:
    print(item)
PYEOF
}
