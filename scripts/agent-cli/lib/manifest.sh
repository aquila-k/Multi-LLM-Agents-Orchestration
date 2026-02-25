#!/usr/bin/env bash
# manifest.sh — YAML manifest reader utility
# Usage: source this file, then call manifest_get <yaml-file> <dotted.key>
#
# manifest_get returns the value for a dotted key path.
# Examples:
#   manifest_get manifest.yaml "task_id"
#   manifest_get manifest.yaml "routing.intent"
#   manifest_get manifest.yaml "budgets.retry_budget"

set -euo pipefail

# Detect YAML parser once at source time
_MANIFEST_PARSER=""
if command -v yq &>/dev/null; then
	_yq_version=$(yq --version 2>&1 || true)
	# mikefarah/yq uses "eval" expression syntax; kislyuk/yq uses jq-like syntax
	# Detect by checking if 'yq e' works (mikefarah)
	if yq e '.' /dev/null &>/dev/null 2>&1; then
		_MANIFEST_PARSER="yq_mikefarah"
	else
		_MANIFEST_PARSER="yq_kislyuk"
	fi
elif command -v python3 &>/dev/null && python3 -c "import yaml" &>/dev/null 2>&1; then
	_MANIFEST_PARSER="python3"
elif command -v ruby &>/dev/null && ruby -e "require 'yaml'" &>/dev/null 2>&1; then
	_MANIFEST_PARSER="ruby"
else
	_MANIFEST_PARSER="none"
fi

# manifest_get <yaml-file> <dotted.key>
# Outputs the value to stdout. Returns 1 if key not found or file missing.
manifest_get() {
	local yaml_file="$1"
	local key_path="$2"

	if [[ ! -f $yaml_file ]]; then
		echo "manifest_get: file not found: $yaml_file" >&2
		return 1
	fi

	case "$_MANIFEST_PARSER" in
	yq_mikefarah)
		local expr
		# Convert dotted path to yq expression: "routing.intent" -> ".routing.intent"
		expr=".${key_path}"
		local result
		result=$(yq e "$expr" "$yaml_file" 2>/dev/null)
		if [[ $result == "null" || -z $result ]]; then
			return 1
		fi
		echo "$result"
		;;
	yq_kislyuk)
		local expr
		expr=".${key_path}"
		local result
		result=$(yq "$expr" "$yaml_file" 2>/dev/null)
		if [[ $result == "null" || -z $result ]]; then
			return 1
		fi
		echo "$result"
		;;
	python3)
		python3 - "$yaml_file" "$key_path" <<'PYEOF'
import sys, yaml

def get_nested(d, key_path):
    keys = key_path.split('.')
    val = d
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return None
    return val

yaml_file = sys.argv[1]
key_path = sys.argv[2]

with open(yaml_file) as f:
    data = yaml.safe_load(f)

val = get_nested(data, key_path)
if val is None:
    sys.exit(1)
# Print list as newline-separated values, scalars as-is
if isinstance(val, list):
    for item in val:
        print(item)
else:
    print(val)
PYEOF
		;;
	ruby)
		ruby - "$yaml_file" "$key_path" <<'RBEOF'
require "yaml"

yaml_file = ARGV[0]
key_path = ARGV[1]

data = YAML.load_file(yaml_file)
keys = key_path.split(".")

val = keys.reduce(data) do |acc, key|
  if acc.is_a?(Hash)
    acc[key] || acc[key.to_sym]
  else
    nil
  end
end

exit 1 if val.nil?

if val.is_a?(Array)
  val.each { |item| puts item }
else
  puts val
end
RBEOF
		;;
	none)
		echo "manifest_get: no YAML parser available (install yq, python3+pyyaml, or ruby)" >&2
		return 1
		;;
	esac
}

# manifest_get_list <yaml-file> <dotted.key> — returns array items one per line
manifest_get_list() {
	manifest_get "$1" "$2"
}

# manifest_require <yaml-file> <dotted.key> <description>
# Like manifest_get but exits with error if missing
manifest_require() {
	local yaml_file="$1"
	local key_path="$2"
	local desc="${3:-$key_path}"
	local val
	if ! val=$(manifest_get "$yaml_file" "$key_path"); then
		echo "ERROR: Required manifest field missing: $desc (path: $key_path)" >&2
		return 1
	fi
	echo "$val"
}
