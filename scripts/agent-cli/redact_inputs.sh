#!/usr/bin/env bash
# redact_inputs.sh — Mask secrets and sensitive data before passing to external CLIs
#
# Usage: redact_inputs.sh <input-file> <output-file> [manifest-file]
#
# If manifest-file is provided, also applies security.redaction_patterns[] from it.
# Forbidden paths from security.forbidden_paths[] are replaced with [FORBIDDEN_PATH].
#
# Exit codes:
#   0  Success (output file written)
#   1  Input file not found
#   2  Output file could not be written

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/log.sh"
source "${SCRIPT_DIR}/lib/manifest.sh"

INPUT_FILE="${1-}"
OUTPUT_FILE="${2-}"
MANIFEST_FILE="${3-}"

if [[ -z $INPUT_FILE || -z $OUTPUT_FILE ]]; then
	echo "Usage: redact_inputs.sh <input-file> <output-file> [manifest-file]" >&2
	exit 2
fi

if [[ ! -f $INPUT_FILE ]]; then
	log_error "Input file not found: $INPUT_FILE"
	exit 1
fi

# Run Python-based redaction (robust regex, handles multiline)
python3 - "$INPUT_FILE" "$OUTPUT_FILE" "$MANIFEST_FILE" <<'PYEOF'
import sys
import re
import os

input_file = sys.argv[1]
output_file = sys.argv[2]
manifest_file = sys.argv[3] if len(sys.argv) > 3 else ""

with open(input_file, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# ── Hard-coded always-redact patterns (defense in depth) ──────────────────────
ALWAYS_REDACT = [
    # OpenAI / Anthropic / generic API keys
    (r'(sk-[a-zA-Z0-9]{20,})', '[REDACTED_API_KEY]'),
    (r'(sk-ant-[a-zA-Z0-9\-_]{20,})', '[REDACTED_API_KEY]'),
    # GitHub tokens
    (r'(ghp_[a-zA-Z0-9]{36,})', '[REDACTED_GH_TOKEN]'),
    (r'(gho_[a-zA-Z0-9]{36,})', '[REDACTED_GH_TOKEN]'),
    (r'(github_pat_[a-zA-Z0-9_]{20,})', '[REDACTED_GH_TOKEN]'),
    (r'(ghs_[a-zA-Z0-9]{36,})', '[REDACTED_GH_TOKEN]'),
    # Bearer tokens in headers
    (r'(Bearer\s+)[a-zA-Z0-9\-._~+/]+=*', r'\1[REDACTED_TOKEN]'),
    # Generic password/secret assignments
    (r'(?i)(password\s*[:=]\s*)[^\s\n"\']+', r'\1[REDACTED]'),
    (r'(?i)(secret\s*[:=]\s*)[^\s\n"\']+', r'\1[REDACTED]'),
    (r'(?i)(api[_\-]?key\s*[:=]\s*)[^\s\n"\']+', r'\1[REDACTED]'),
    (r'(?i)(access[_\-]?token\s*[:=]\s*)[^\s\n"\']+', r'\1[REDACTED]'),
    # AWS keys
    (r'(AKIA[0-9A-Z]{16})', '[REDACTED_AWS_KEY]'),
    (r'(aws[_\-]?secret[_\-]?access[_\-]?key\s*[:=]\s*)[^\s\n"\']+', r'\1[REDACTED]'),
    # Private keys (PEM blocks)
    (r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----',
     '[REDACTED_PRIVATE_KEY]'),
]

for pattern, replacement in ALWAYS_REDACT:
    content = re.sub(pattern, replacement, content)

# ── Manifest-defined patterns ─────────────────────────────────────────────────
if manifest_file and os.path.isfile(manifest_file):
    try:
        import yaml
        with open(manifest_file) as mf:
            manifest = yaml.safe_load(mf)
        security = manifest.get('security', {}) if manifest else {}
        redaction_patterns = security.get('redaction_patterns', []) or []
        forbidden_paths = security.get('forbidden_paths', []) or []

        for pattern in redaction_patterns:
            if pattern:
                try:
                    content = re.sub(pattern, '[REDACTED]', content)
                except re.error:
                    pass  # skip invalid patterns silently

        for path in forbidden_paths:
            if path and path in content:
                content = content.replace(path, '[FORBIDDEN_PATH]')
    except Exception:
        pass  # manifest parse errors should not block redaction

# ── Write output ──────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
partial = output_file + '.partial'
with open(partial, 'w', encoding='utf-8') as f:
    f.write(content)
os.replace(partial, output_file)
PYEOF

log_info "Redacted: $(basename "$INPUT_FILE") -> $(basename "$OUTPUT_FILE")"
exit 0
