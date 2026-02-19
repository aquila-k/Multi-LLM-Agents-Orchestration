#!/usr/bin/env bash
# path_resolve.sh — Resolve CLI tool paths in non-interactive shell environments
#
# Problem: Claude Code and CI runners use non-interactive shells that do not
# source ~/.zshrc / ~/.bashrc, so NVM-managed binaries (gemini, copilot) and
# tools installed in non-standard locations are invisible to `command -v`.
#
# Usage (from wrapper scripts):
#   source "${LIB_DIR}/path_resolve.sh"
#   resolve_tool_or_die <tool_name> <exit_code_on_fail> || finish_exit <exit_code>
#
# On success: prepends the resolved binary's directory to PATH (inherited by
#             all subprocesses, including perl exec calls).
# On failure: emits a structured, machine-readable error block to stderr so
#             that Claude Code can parse the required action and prompt the user
#             to supply the missing path (e.g. via `which <tool>`).

# _path_resolve_search <name>
#   Prints the absolute path of <name> if found, returns 0. Returns 1 if not found.
_path_resolve_search() {
  local name="$1"

  # 1. Standard PATH lookup (covers most interactive-shell-equivalent setups)
  if command -v "$name" &>/dev/null; then
    command -v "$name"
    return 0
  fi

  # 2. NVM: search all installed Node.js versions
  #    NVM_DIR defaults to ~/.nvm but may be overridden by the environment.
  local nvm_root="${NVM_DIR:-$HOME/.nvm}/versions/node"
  if [[ -d "$nvm_root" ]]; then
    local candidate
    # find is portable; sort -r gives lexicographic reverse (newer semver last
    # digit wins in most cases). We take the first executable match.
    while IFS= read -r candidate; do
      if [[ -x "$candidate" ]]; then
        echo "$candidate"
        return 0
      fi
    done < <(find "$nvm_root" -maxdepth 3 -name "$name" -path "*/bin/$name" 2>/dev/null | sort -r)
  fi

  # 3. Homebrew — Apple Silicon (/opt/homebrew) and Intel (/usr/local)
  local dir
  for dir in /opt/homebrew/bin /usr/local/bin; do
    if [[ -x "${dir}/${name}" ]]; then
      echo "${dir}/${name}"
      return 0
    fi
  done

  # 4. ~/.local/bin (common user-level install target)
  if [[ -x "${HOME}/.local/bin/${name}" ]]; then
    echo "${HOME}/.local/bin/${name}"
    return 0
  fi

  return 1
}

# resolve_tool_or_die <tool_name> [exit_code]
#   Resolves <tool_name> using the search strategy above.
#   On success: exports the resolved directory into PATH and returns 0.
#   On failure: writes a structured error block to stderr and returns <exit_code> (default 1).
#
#   The error block is intentionally formatted for Claude Code consumption:
#   Claude Code reads stderr and can extract the ACTION_REQUIRED lines to
#   prompt the user for `which <tool>` output, then patch PATH and retry.
resolve_tool_or_die() {
  local name="$1"
  local exit_code="${2:-1}"

  local resolved
  if resolved=$(_path_resolve_search "$name"); then
    local bin_dir
    bin_dir="$(dirname "$resolved")"
    # Prepend so that both direct calls and perl exec() subprocesses find it
    export PATH="${bin_dir}:${PATH}"
    return 0
  fi

  # Structured error — parseable by Claude Code
  {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  [TOOL_NOT_FOUND] ${name}"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  Searched locations:"
    echo "║    • \$PATH (current: ${PATH})"
    echo "║    • \${NVM_DIR:-~/.nvm}/versions/node/*/bin/${name}"
    echo "║    • /opt/homebrew/bin/${name}"
    echo "║    • /usr/local/bin/${name}"
    echo "║    • ~/.local/bin/${name}"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  ACTION_REQUIRED:"
    echo "║    Run in your terminal:  which ${name}"
    echo "║    Then provide the output to Claude Code."
    echo "║    Claude Code will update PATH resolution and retry."
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
  } >&2

  return "$exit_code"
}
