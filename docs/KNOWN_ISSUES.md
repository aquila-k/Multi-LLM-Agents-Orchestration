# Known Issues and Workarounds

This document records confirmed script bugs, CLI quirks, and their workarounds.
Workarounds applied in scripts are linked to the root cause to prevent re-introduction.

---

## Shell / Bash

### ISSUE-001: Bash 3.2 empty array with `set -u` causes "unbound variable"

**Affects:** macOS (default bash 3.2.57)
**Symptom:** `"${arr[@]}"` triggers `unbound variable` error when `arr` is declared but empty and `set -u` is active.
**Confirmed in:** `scripts/agent-cli/gate.sh` — `write_gate_result()` (fixed 2026-02-25)

**Root cause:**
Bash 3.2 treats `[@]` subscript on an empty array as unset under `set -u`, unlike bash 4.x which safely expands to nothing.

**Workaround (applied):**
Check `${#arr[@]}` before expanding the array:

```bash
# WRONG (bash 3.2 incompatible with set -u):
python3 - "${FAILURE_REASONS[@]}" ...

# CORRECT:
local reasons_json="[]"
if [[ ${#FAILURE_REASONS[@]} -gt 0 ]]; then
    reasons_json=$(printf '%s\n' "${FAILURE_REASONS[@]}" | \
        python3 -c 'import json,sys; print(json.dumps([l.rstrip("\n") for l in sys.stdin]))')
fi
python3 - "$reasons_json" ...
```

**Also avoid:**

- `declare -A` (associative arrays — bash 3.2 does not support them)
- `${var,,}` / `${var^^}` (case conversion operators — bash 4.0+)
- `local -n` (nameref — bash 4.3+)

---

## codex CLI

### ISSUE-002: `codex exec --quiet` flag does not exist

**Symptom:** `codex exec --quiet ...` fails immediately with an unknown flag error.
**Confirmed in:** Session 2026-02-25 during codex exec delegation tests.

**Workaround:** Omit `--quiet`. codex exec outputs to the file specified by `-o` and stderr is minimal by default.

---

### ISSUE-003: `codex exec --output-last-message` is a subcommand flag, not top-level

**Symptom:** Placing `--output-last-message` before `exec` fails.
**Confirmed in:** Session 2026-02-25.

**Correct usage:**

```bash
# WRONG:
codex --output-last-message exec "prompt"

# CORRECT:
codex exec -o /tmp/output.txt "prompt"
# or:
codex exec --output-last-message "prompt"
```

---

### ISSUE-004: `cat file | codex exec -` with additional flags fails

**Symptom:** When piping a file to `codex exec -` (stdin), adding extra flags like `-c` after the `-` causes argument parsing errors.
**Confirmed in:** Session 2026-02-25.

**Workaround:** Use inline command substitution for the prompt instead of stdin pipe:

```bash
# WRONG:
cat .tmp/prompt.md | codex exec - -c "model=gpt-5.3-codex"

# CORRECT:
codex exec -c "model=gpt-5.3-codex" "$(cat .tmp/prompt.md)"
```

**Constraint:** The inline approach has a practical limit — very large prompts (>100KB) may hit ARG_MAX. For large inputs, write to a temp file and use a different approach.

---

## Gemini CLI

### ISSUE-005: Gemini large input via positional argument may hit ARG_MAX

**Symptom:** Very long prompts passed as a positional argument may cause "Argument list too long" on macOS.
**Current mitigation:** `gemini_headless.sh` uses stdin pipe (`--stdin` or `--stdin-file` flags) for all substantial input.

**Rule:** Always use stdin pipe for Gemini input — never positional argument for content longer than a few hundred characters.

```bash
# PREFERRED (safe for any size):
cat prompt.md | gemini ...
# or via wrapper:
gemini_headless.sh --stdin-file prompt.md ...
```

---

## gate.sh

### ISSUE-006: `gate_brief()` and `gate_review()` Gemini line-wrapping false positives

**Symptom:** Gemini output sometimes wraps multi-line headings like:

```
## N.
 Title continuation
```

This causes `gate_brief()` and `gate_review()` to miss required sections.

**Fix (applied 2026-02-25):** Both gates use Python normalization to collapse `## N.\n Title` and `## Word\n continuation` into single lines before checking for required sections.

---

### ISSUE-007: `gate.sh` soft-pass file path stripping for patch headers

**Symptom:** Patch headers in the format `+++ b/<path>\t<timestamp>` include a tab and timestamp, causing path extraction to fail.

**Fix (applied):** `fpath="${fpath%%\t*}"` strips the tab and anything after it before path validation.

---

## configs-v2

### ISSUE-008: servant/ vs servants/ directory duality in configs-v2

**Symptom:** `configs-v2` had both `servant/` (v1-compat) and `servants/` (v2 format), causing the runtime to use `servant/` while the v2 validator used `servants/`.

**Fix (applied 2026-02-25):**

- `config.sh::_servant_dir()` prefers `servants/` over `servant/` (preference order check)
- `config_validate.py::_servant_subdir()` mirrors same logic
- `configs-v2/servant/` deleted (was a workaround)
- `configs-v2/servants/*.yaml` updated with merged v1+v2 fields (satisfies both validators)

---

## Python scripts

### ISSUE-009: `pyyaml` must be installed — not available by default

**Symptom:** Scripts that `import yaml` fail with `ModuleNotFoundError` if pyyaml is not installed.
**Affected scripts:** `lib/config_resolve.py`, `lib/config_validate.py`, `lib/config_snapshot.py`, and others.

**Fix:**

```bash
pip3 install pyyaml
```

All scripts using `import yaml` have a fallback path via `manifest.sh` that tries yq or ruby if pyyaml is missing, but the Python validators require pyyaml directly.

---

### ISSUE-010: `review_parallel.sh` security template path uses wrong `../../` depth

**Affects:** `review_lens_focus_prompt("security")` — security_review.md not found, falls back to inline text.
**Confirmed in:** Session 2026-02-25 during security review integration.

**Root cause:**
`REVIEW_PARALLEL_LIB_DIR` is `scripts/agent-cli/lib` (absolute). The template path used `../../` (2 levels up → `scripts/`), but `prompts-src/` is at the repo root, which requires 3 levels up.

**Fix (applied 2026-02-25):** Changed `../../` to `../../../` in `review_lens_focus_prompt()`:

```bash
# WRONG (goes up 2 levels: lib → agent-cli → scripts):
local _sec_tmpl="${REVIEW_PARALLEL_LIB_DIR}/../../prompts-src/security/security_review.md"

# CORRECT (goes up 3 levels: lib → agent-cli → scripts → repo-root):
local _sec_tmpl="${REVIEW_PARALLEL_LIB_DIR}/../../../prompts-src/security/security_review.md"
```

**Rule:** Count the directory depth from the script location to the repo root carefully. `lib/` is 3 levels deep (`lib → agent-cli → scripts → root`).

### ISSUE-011: `security_review.yaml` config files are intentionally removed in V2

**Symptom:** Adding legacy `security_review.yaml` files under `configs-v2/policies/` or `configs-v2/skills/` causes `config_validate_v2.py` to fail with unknown-file errors.

**Expected behavior:** Security lens control is runtime-owned (`dispatch_review.sh` + `review_parallel.sh`) and does not use optional `security_review.yaml` files.

---

## preflight.sh

### ISSUE-012: `preflight.sh --tools ""` can fail on bash 3.2 with `set -u`

**Symptom:** Running preflight with an empty `--tools` value may fail with:

```text
unbound variable: REQUIRED_TOOLS[@]
```

**Confirmed in:** Session 2026-02-25 while smoke-testing prompt profile audit integration.

**Root cause:**
`read -a REQUIRED_TOOLS <<< ""` may leave the array effectively unset under bash 3.2 + `set -u`.

**Fix (applied 2026-02-25):**
Initialize the array before parsing and guard the loop expansion:

```bash
REQUIRED_TOOLS=()
if [[ -n $TOOLS_CSV ]]; then
    IFS=',' read -r -a REQUIRED_TOOLS <<<"$TOOLS_CSV"
fi
for tool in "${REQUIRED_TOOLS[@]:-}"; do
    ...
done
```

---

## Adding new entries

When a new bug is confirmed and a workaround is applied:

1. Add an entry here with ISSUE-NNN format
2. Add a comment in the fixed code referencing the ISSUE-NNN
3. If the fix changes script behavior, update `MEMORY.md` accordingly
