#!/usr/bin/env bash
# make_digest.sh — Generate a compact digest of a context pack
#
# Usage: make_digest.sh <context-pack.md> <output-digest.md>
#
# Extracts only the essential sections (Goal, Non-goals, Scope, Acceptance,
# Fixed Decisions, Files to Read, Prohibited Actions) and truncates each to
# at most MAX_LINES_PER_SECTION lines.
#
# Exit codes:
#   0  Digest written successfully
#   1  Input file not found

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/log.sh"
source "${SCRIPT_DIR}/lib/atomic.sh"

MAX_LINES_PER_SECTION=40

INPUT_FILE="${1-}"
OUTPUT_FILE="${2-}"

if [[ -z $INPUT_FILE || -z $OUTPUT_FILE ]]; then
	echo "Usage: make_digest.sh <context-pack.md> <output-digest.md>" >&2
	exit 1
fi

if [[ ! -f $INPUT_FILE ]]; then
	log_error "Context pack not found: $INPUT_FILE"
	exit 1
fi

python3 - "$INPUT_FILE" "$OUTPUT_FILE" "$MAX_LINES_PER_SECTION" <<'PYEOF'
import sys
import os
import re
from datetime import datetime, timezone

input_file = sys.argv[1]
output_file = sys.argv[2]
max_lines = int(sys.argv[3])

with open(input_file, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Section names to extract (case-insensitive substring match on ## heading)
# Handles both "## Goal" and "## 0. Goal" style numbering
DIGEST_SECTIONS = [
    'goal',
    'non-goal',
    'scope',
    'acceptance',
    'fixed decision',
    'files to read',
    'prohibited action',
]

def normalize_heading(h):
    # Strip leading numbers and dots: "0. Goal" -> "goal"
    import re
    h = re.sub(r'^\d+\.\s*', '', h.strip())
    return h.lower()

def matches_digest(heading):
    h = normalize_heading(heading)
    return any(d.rstrip('s') in h or h.startswith(d.rstrip('s')) for d in DIGEST_SECTIONS)

# Split into sections by ## headings
# We look for lines starting with ## (level 2 headings)
lines = content.splitlines(keepends=True)
sections = []
current_heading = None
current_body = []

for line in lines:
    m = re.match(r'^(#{1,3})\s+(.+)', line)
    if m:
        level = len(m.group(1))
        heading_text = m.group(2).strip()
        if level <= 2:
            # Save previous section
            if current_heading is not None:
                sections.append((current_heading, current_body))
            current_heading = heading_text
            current_body = [line]
            continue
    if current_heading is not None:
        current_body.append(line)

if current_heading is not None:
    sections.append((current_heading, current_body))

# Build digest
now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
digest_parts = [
    f"# Context Pack Digest (auto-generated)\n",
    f"Source: {input_file}\n",
    f"Generated: {now}\n\n",
    "---\n\n",
]

found_any = False
for heading, body_lines in sections:
    if matches_digest(heading):
        found_any = True
        # Truncate body to max_lines
        truncated = body_lines[:max_lines + 1]  # +1 for the heading line
        if len(body_lines) > max_lines + 1:
            truncated.append(f"... [{len(body_lines) - max_lines - 1} lines truncated]\n")
        digest_parts.extend(truncated)
        digest_parts.append('\n')

if not found_any:
    # Fallback: include first 100 lines of the original
    digest_parts.append("## (No standard sections found — first 100 lines)\n\n")
    digest_parts.extend(lines[:100])
    if len(lines) > 100:
        digest_parts.append(f"... [{len(lines) - 100} lines truncated]\n")

digest_content = ''.join(digest_parts)

os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
partial = output_file + '.partial'
with open(partial, 'w', encoding='utf-8') as f:
    f.write(digest_content)
os.replace(partial, output_file)
PYEOF

log_info "Digest created: $(basename "$OUTPUT_FILE") ($(wc -l <"$OUTPUT_FILE") lines)"
exit 0
