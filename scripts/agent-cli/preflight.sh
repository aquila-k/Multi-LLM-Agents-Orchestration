#!/usr/bin/env bash
# preflight.sh — Verify CLI binaries and environment before any pipeline execution
#
# Usage: preflight.sh [--quick] [--tools <comma-separated>]
#   --quick  Skip version checks (just binary existence)
#   --tools  Required external tools (gemini,codex,copilot). Default: all.
#
# Exit codes:
#   0  All checks passed
#   1  One or more required tools are missing or misconfigured

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/log.sh"
source "${SCRIPT_DIR}/lib/config.sh"

QUICK=false
TOOLS_CSV="gemini,copilot,codex"
while [[ $# -gt 0 ]]; do
	case "$1" in
	--quick)
		QUICK=true
		shift
		;;
	--tools)
		TOOLS_CSV="$2"
		shift 2
		;;
	*)
		log_warn "Unknown argument: $1"
		shift
		;;
	esac
done

FAILED=0

check_binary() {
	local name="$1"
	local install_hint="${2-}"
	if command -v "$name" &>/dev/null; then
		if [[ $QUICK == "false" ]]; then
			local ver
			ver=$("$name" --version 2>&1 | head -1 || echo "(version unknown)")
			log_ok "$name found: $ver"
		else
			log_ok "$name found"
		fi
	else
		log_error "$name not found${install_hint:+ — $install_hint}"
		FAILED=1
	fi
}

check_yaml_parser() {
	if command -v yq &>/dev/null; then
		log_ok "YAML parser: yq"
		return 0
	fi
	if command -v python3 &>/dev/null && python3 -c "import yaml" &>/dev/null 2>&1; then
		log_ok "YAML parser: python3 + pyyaml"
		return 0
	fi
	if command -v ruby &>/dev/null && ruby -e "require 'yaml'" &>/dev/null 2>&1; then
		log_ok "YAML parser: ruby + yaml"
		return 0
	fi
	log_error "No YAML parser found. Install yq, python3 with pyyaml, or ruby with yaml stdlib."
	FAILED=1
}

check_sha256() {
	if command -v sha256sum &>/dev/null || command -v shasum &>/dev/null; then
		log_ok "SHA256 tool available"
	elif command -v python3 &>/dev/null; then
		log_ok "SHA256 via python3"
	else
		log_error "No SHA256 tool available"
		FAILED=1
	fi
}

log_info "=== Preflight Check ==="

require_tool() {
	local tool="$1"
	case "$tool" in
	gemini) check_binary "gemini" "Install Gemini CLI: http://geminicli.com/docs/get-started/" ;;
	copilot) check_binary "copilot" "Install GitHub Copilot CLI: https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli" ;;
	codex) check_binary "codex" "Install OpenAI Codex CLI: https://developers.openai.com/codex/cli" ;;
	"") ;;
	*) log_warn "Unknown tool in --tools: ${tool}" ;;
	esac
}

# ISSUE-012: Bash 3.2 + set -u may leave array unset when read -a consumes empty input.
# Initialize explicitly to avoid "unbound variable" in "${REQUIRED_TOOLS[@]}" loops.
REQUIRED_TOOLS=()
if [[ -n $TOOLS_CSV ]]; then
	IFS=',' read -r -a REQUIRED_TOOLS <<<"$TOOLS_CSV"
fi
for tool in "${REQUIRED_TOOLS[@]-}"; do
	tool="${tool//[[:space:]]/}"
	require_tool "$tool"
done

# Required system tools
check_binary "git" "Install git"
check_binary "perl" "Install perl (used for timeout on macOS)"
check_binary "python3" "Install python3 (required by dispatcher scripts)"

# YAML parser
check_yaml_parser

# SHA256 tool
check_sha256

# Orchestrator config validation
if ! config_validate_global; then
	log_error "config validation failed for:"
	while IFS= read -r config_path; do
		log_error "  - ${config_path}"
	done < <(config_sources_summary)
	FAILED=1
else
	log_ok "Split config: valid"
fi

PROMPT_AUDIT_SCRIPT="${SCRIPT_DIR}/lib/prompt_profiles_audit.py"
if [[ -f $PROMPT_AUDIT_SCRIPT ]]; then
	if ! PYTHONDONTWRITEBYTECODE=1 python3 "$PROMPT_AUDIT_SCRIPT" \
		--config-root "$(config_root_dir)" \
		--prompts-root "${REPO_ROOT}/prompts-src" >/dev/null; then
		log_error "prompt profile audit failed: ${PROMPT_AUDIT_SCRIPT}"
		FAILED=1
	else
		log_ok "Prompt profile templates: valid"
	fi
fi

if [[ $FAILED -eq 1 ]]; then
	log_error "Preflight FAILED. Fix the issues above before running the pipeline."
	exit 1
fi

log_ok "=== Preflight PASSED ==="
exit 0
