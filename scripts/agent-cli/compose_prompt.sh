#!/usr/bin/env bash
# compose_prompt.sh — Compose a final prompt from static template + dynamic content
#
# Usage:
#   compose_prompt.sh \
#     --template <path>   Role-specific prompt template (prompts-src/<tool>/<role>.md)
#     --user <path>       User request file (inputs/user_request.md)
#     --context <path>    Context pack file (inputs/context_pack.md)
#     --manifest <path>   manifest.yaml (for digest_policy + security settings)
#     --out <path>        Output composed prompt path (inputs/prompt/<tool>.<role>.md)
#     [--shared <path>]   Shared rules file (prompts-src/shared.md)
#     [--attachments-dir <path>]  Directory with attachment files
#     [--digest-policy <off|auto|aggressive>] Force digest policy for this invocation
#     [--sha-out <path>]  Optional file to write prompt SHA256
#
# Output: the composed prompt file at --out
# Stdout: SHA256 of the composed prompt (for meta.json)
#
# Exit codes:
#   0   Success
#   1   Missing required argument or file

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/log.sh"
source "${SCRIPT_DIR}/lib/manifest.sh"
source "${SCRIPT_DIR}/lib/atomic.sh"

# Default shared.md location (relative to repo root, caller can override)
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEFAULT_SHARED="${REPO_ROOT}/prompts-src/shared.md"

TEMPLATE=""
USER_FILE=""
CONTEXT_FILE=""
MANIFEST_FILE=""
OUT_FILE=""
SHARED_FILE="$DEFAULT_SHARED"
ATTACHMENTS_DIR=""
DIGEST_POLICY_OVERRIDE=""
SHA_OUT_FILE=""

MAX_LOG_LINES_HEAD=200
MAX_LOG_LINES_TAIL=200
CONTEXT_DIGEST_THRESHOLD=8000 # chars

while [[ $# -gt 0 ]]; do
	case "$1" in
	--template)
		TEMPLATE="$2"
		shift 2
		;;
	--user)
		USER_FILE="$2"
		shift 2
		;;
	--context)
		CONTEXT_FILE="$2"
		shift 2
		;;
	--manifest)
		MANIFEST_FILE="$2"
		shift 2
		;;
	--out)
		OUT_FILE="$2"
		shift 2
		;;
	--shared)
		SHARED_FILE="$2"
		shift 2
		;;
	--attachments-dir)
		ATTACHMENTS_DIR="$2"
		shift 2
		;;
	--digest-policy)
		DIGEST_POLICY_OVERRIDE="$2"
		shift 2
		;;
	--sha-out)
		SHA_OUT_FILE="$2"
		shift 2
		;;
	*)
		log_warn "Unknown argument: $1"
		shift
		;;
	esac
done

# Validate required args
for var_name in TEMPLATE USER_FILE CONTEXT_FILE MANIFEST_FILE OUT_FILE; do
	val="${!var_name}"
	if [[ -z $val ]]; then
		log_error "Missing required argument: --${var_name//_/-}"
		exit 1
	fi
	if [[ $var_name != "OUT_FILE" && ! -f $val ]]; then
		log_error "File not found: $val (for --${var_name//_/-})"
		exit 1
	fi
done

ensure_dir "$OUT_FILE"

# ── Step 1: Determine context file (digest or full) ───────────────────────────
if [[ -n $DIGEST_POLICY_OVERRIDE ]]; then
	DIGEST_POLICY="$DIGEST_POLICY_OVERRIDE"
else
	DIGEST_POLICY=$(manifest_get "$MANIFEST_FILE" "context.digest_policy" 2>/dev/null || echo "off")
fi
CONTEXT_DIGEST_FILE="${CONTEXT_FILE%.md}.digest.md"

use_context_file="$CONTEXT_FILE"

if [[ $DIGEST_POLICY == "aggressive" ]]; then
	log_info "compose_prompt: digest_policy=aggressive, generating digest"
	"${SCRIPT_DIR}/make_digest.sh" "$CONTEXT_FILE" "$CONTEXT_DIGEST_FILE"
	use_context_file="$CONTEXT_DIGEST_FILE"
elif [[ $DIGEST_POLICY == "auto" ]]; then
	context_size=$(wc -c <"$CONTEXT_FILE" | tr -d ' ')
	if ((context_size > CONTEXT_DIGEST_THRESHOLD)); then
		log_info "compose_prompt: context too large (${context_size} chars), generating digest"
		"${SCRIPT_DIR}/make_digest.sh" "$CONTEXT_FILE" "$CONTEXT_DIGEST_FILE"
		use_context_file="$CONTEXT_DIGEST_FILE"
	fi
fi

# ── Step 2: Redact all dynamic input files ────────────────────────────────────
TMPDIR_REDACT=$(mktemp -d)
trap 'rm -rf "$TMPDIR_REDACT"' EXIT

redact_file() {
	local src="$1"
	local dst="${TMPDIR_REDACT}/$(basename "$src").redacted"
	"${SCRIPT_DIR}/redact_inputs.sh" "$src" "$dst" "$MANIFEST_FILE" 2>/dev/null
	echo "$dst"
}

USER_REDACTED=$(redact_file "$USER_FILE")
CONTEXT_REDACTED=$(redact_file "$use_context_file")

# ── Step 3: Process attachments ───────────────────────────────────────────────
declare -a ATTACHMENT_FILES=()

if [[ -n $ATTACHMENTS_DIR && -d $ATTACHMENTS_DIR ]]; then
	for attachment in "$ATTACHMENTS_DIR"/*; do
		[[ -f $attachment ]] || continue
		filename=$(basename "$attachment")
		redacted_att="${TMPDIR_REDACT}/${filename}.redacted"

		if [[ $filename == "logs.txt" || $filename == *.log ]]; then
			# Trim logs to head + tail
			trimmed="${TMPDIR_REDACT}/${filename}.trimmed"
			{
				head -n $MAX_LOG_LINES_HEAD "$attachment"
				total=$(wc -l <"$attachment" | tr -d ' ')
				if ((total > MAX_LOG_LINES_HEAD + MAX_LOG_LINES_TAIL)); then
					echo "... [$((total - MAX_LOG_LINES_HEAD - MAX_LOG_LINES_TAIL)) lines omitted] ..."
					tail -n $MAX_LOG_LINES_TAIL "$attachment"
				fi
			} >"$trimmed"
			"${SCRIPT_DIR}/redact_inputs.sh" "$trimmed" "$redacted_att" "$MANIFEST_FILE" 2>/dev/null
		else
			"${SCRIPT_DIR}/redact_inputs.sh" "$attachment" "$redacted_att" "$MANIFEST_FILE" 2>/dev/null
		fi

		ATTACHMENT_FILES+=("$redacted_att:$filename")
	done
fi

# ── Step 4: Concatenate into final prompt ─────────────────────────────────────
OUT_PARTIAL="${OUT_FILE}.partial"

{
	# Shared rules (if exists)
	if [[ -f $SHARED_FILE ]]; then
		cat "$SHARED_FILE"
		echo ""
		echo "--- END SHARED RULES ---"
		echo ""
	fi

	# Role template
	echo "--- BEGIN ROLE TEMPLATE ---"
	cat "$TEMPLATE"
	echo ""
	echo "--- END ROLE TEMPLATE ---"
	echo ""

	# Context pack
	echo "--- BEGIN CONTEXT PACK ---"
	cat "$CONTEXT_REDACTED"
	echo ""
	echo "--- END CONTEXT PACK ---"
	echo ""

	# User request
	echo "--- BEGIN USER REQUEST ---"
	cat "$USER_REDACTED"
	echo ""
	echo "--- END USER REQUEST ---"
	echo ""

	# Attachments
	if [[ ${#ATTACHMENT_FILES[@]} -gt 0 ]]; then
		for att_entry in "${ATTACHMENT_FILES[@]}"; do
			att_path="${att_entry%%:*}"
			att_name="${att_entry##*:}"
			echo "--- BEGIN ATTACHMENT: ${att_name} ---"
			cat "$att_path"
			echo ""
			echo "--- END ATTACHMENT: ${att_name} ---"
			echo ""
		done
	fi
} >"$OUT_PARTIAL"

atomic_write "$OUT_PARTIAL" "$OUT_FILE"

# ── Step 5: Output SHA256 to stdout (for meta.json) ───────────────────────────
PROMPT_SHA256=$(sha256_file "$OUT_FILE")
echo "$PROMPT_SHA256"

if [[ -n $SHA_OUT_FILE ]]; then
	ensure_dir "$SHA_OUT_FILE"
	printf '%s\n' "$PROMPT_SHA256" >"${SHA_OUT_FILE}.partial"
	atomic_write "${SHA_OUT_FILE}.partial" "$SHA_OUT_FILE"
fi

prompt_size=$(wc -c <"$OUT_FILE" | tr -d ' ')
log_info "compose_prompt: output ${prompt_size} bytes -> $(basename "$OUT_FILE")"

exit 0
