#!/usr/bin/env bash
# atomic.sh — Atomic file operations and done-marker utilities
# Usage: source this file

set -euo pipefail

# atomic_write <src> <dst>
# Rename src to dst atomically (POSIX rename is atomic on same filesystem).
# The src file should be a .partial file written completely before calling this.
atomic_write() {
	local src="$1"
	local dst="$2"
	if [[ ! -f $src ]]; then
		echo "atomic_write: source file not found: $src" >&2
		return 1
	fi
	mv -f "$src" "$dst"
}

# write_done_marker <path>
# Creates a done marker file with ISO-8601 timestamp content.
write_done_marker() {
	local path="$1"
	mkdir -p "$(dirname "$path")"
	date -u +"%Y-%m-%dT%H:%M:%SZ" >"$path"
}

# write_meta_json <meta_path> <stage> <tool> <exit_code> <start_epoch> <end_epoch> <prompt_sha256>
# Writes the stage meta.json file.
write_meta_json() {
	local meta_path="$1"
	local stage="$2"
	local tool="$3"
	local exit_code="$4"
	local start_epoch="$5"
	local end_epoch="$6"
	local prompt_sha256="${7-}"

	local start_iso end_iso
	start_iso=$(date -u -r "$start_epoch" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null ||
		python3 -c "import datetime; print(datetime.datetime.utcfromtimestamp($start_epoch).strftime('%Y-%m-%dT%H:%M:%SZ'))")
	end_iso=$(date -u -r "$end_epoch" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null ||
		python3 -c "import datetime; print(datetime.datetime.utcfromtimestamp($end_epoch).strftime('%Y-%m-%dT%H:%M:%SZ'))")

	mkdir -p "$(dirname "$meta_path")"
	cat >"${meta_path}.partial" <<EOF
{
  "stage": "${stage}",
  "tool": "${tool}",
  "exit_code": ${exit_code},
  "start": "${start_iso}",
  "end": "${end_iso}",
  "duration_sec": $((end_epoch - start_epoch)),
  "prompt_sha256": "${prompt_sha256}"
}
EOF
	atomic_write "${meta_path}.partial" "$meta_path"
}

# partial_path <final_path>
# Returns the .partial path for a given destination path.
partial_path() {
	echo "${1}.partial"
}

# ensure_dir <path>
# Creates directory for a file path if it doesn't exist.
ensure_dir() {
	mkdir -p "$(dirname "$1")"
}
