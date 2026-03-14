---
name: use-gemini
description: Invoke the Gemini CLI directly for headless automation, JSON or stream-json output, model selection, and session resume. Use this skill when you need to call `gemini` from Bash instead of going through Copilot or Codex.
compatibility: Requires Gemini CLI installed locally. Verified against the local `gemini --help` surface (v0.32.1) in this repository environment.
metadata:
  version: "1.0"
---

# use-gemini skill

Invoke the Gemini CLI directly. Prefer this skill when you want Gemini's own CLI
features (`stream-json`, headless `-p`, or Gemini session resume) rather than
another provider wrapper.

## Quick reference

```bash
GEMINI=~/.nvm/versions/node/v22.18.0/bin/gemini

# Headless one-shot
$GEMINI -p "Summarize @README.md in 5 bullets." --model flash

# Headless with stdin context
git diff --staged | $GEMINI -p "Write a concise Conventional Commit message." --model flash

# Machine-readable final output
$GEMINI -p "Return a raw JSON object with keys summary and risks for @/tmp/plan.md." \
  --model pro \
  --output-format json > /tmp/gemini.json
jq -r '.response' /tmp/gemini.json

# Capture session metadata
$GEMINI -p "Review @/tmp/design.md and suggest the top 3 issues." \
  --output-format stream-json > /tmp/gemini-events.jsonl
jq -r 'select(.type == "init") | .session_id' /tmp/gemini-events.jsonl

# Resume the latest same-project session
$GEMINI --resume latest -p "Continue from the previous step and finish the review." \
  --output-format json > /tmp/gemini-resume.json
jq -r '.response' /tmp/gemini-resume.json
```

## Rules

- **For scripted or headless use, always pass `-p/--prompt`.** Local
  `gemini --help` (v0.32.1) says positional `query` runs in interactive mode by
  default. Do not rely on positional prompts for automation, even if older docs
  show that pattern.
- **Use stdin for large transient context.** `-p` text is appended to stdin
  input, so `git diff | gemini -p "..."` is a safe pattern for reviews, commit
  messages, and summaries.
- **Prefer `@path` references for repo files.** This keeps prompts short and
  avoids bloating shell arguments.
- **Prefer `--output-format json` for one-shot scripted capture.** It returns a
  single object with `response`, `stats`, and optional `error`.
- **Use `--output-format stream-json` when you need event-level tracing or
  session metadata.** Verified project facts confirm the `init` event exposes
  `session_id`.
- **Do not use `--allowed-tools` for new flows.** It is deprecated in the
  current CLI help surface. Use `--approval-mode` and optional `--policy`
  instead.
- **Choose approval mode deliberately.**
  - `plan`: read-only or analysis-first runs
  - `default`: prompt for approvals
  - `auto_edit`: auto-approve edit tools
  - `yolo` / `-y`: auto-approve everything; use only with explicit intent
- **Avoid `--raw-output` unless you truly need unsanitized ANSI or control
  output.** If you do use it, you must also pass `--accept-raw-output-risk`.
- **When calling Gemini from an agent Bash tool, keep the Gemini invocation
  isolated.** Do not append unrelated shell commands after it in the same call
  unless you explicitly need shell redirection.

## Useful flags

| Flag                         | Purpose                                | Notes                                                      |
| ---------------------------- | -------------------------------------- | ---------------------------------------------------------- |
| `-p`, `--prompt`             | Headless prompt text                   | Recommended for all scripted runs                          |
| `-i`, `--prompt-interactive` | Run a prompt, then stay interactive    | Good for bootstrapping a session                           |
| `-m`, `--model`              | Select model alias or concrete model   | See models section below                                   |
| `-o`, `--output-format`      | `text`, `json`, or `stream-json`       | Use `json` or `stream-json` for automation                 |
| `-r`, `--resume`             | Resume a saved session                 | Safest documented selectors are `latest` and session index |
| `--list-sessions`            | List current-project sessions          | Use before selecting by index                              |
| `--delete-session`           | Delete a session by index              | Pair with `--list-sessions` first                          |
| `--approval-mode`            | Control tool approvals                 | `default`, `auto_edit`, `yolo`, `plan`                     |
| `--policy`                   | Load extra policy files or directories | Preferred over deprecated `--allowed-tools`                |
| `--include-directories`      | Extend workspace roots                 | Useful for sibling directories                             |
| `--allowed-mcp-server-names` | Allow specific MCP servers             | Optional, for locked-down runs                             |
| `-e`, `--extensions`         | Restrict enabled extensions            | Otherwise all enabled extensions are used                  |
| `-s`, `--sandbox`            | Run in sandbox mode                    | Use when you want extra isolation                          |
| `--raw-output`               | Disable output sanitization            | Risky; requires `--accept-raw-output-risk`                 |
| `--accept-raw-output-risk`   | Acknowledge raw output risk            | Only use together with `--raw-output`                      |

## Models and aliases

Current concrete Gemini CLI models this project tracks:

- `gemini-3.1-pro-preview`
- `gemini-3-flash-preview`
- `gemini-2.5-pro`
- `gemini-2.5-flash`
- `gemini-2.5-flash-lite`

Current alias mapping used by project configs:

| Alias        | Resolves to              | When to use                                |
| ------------ | ------------------------ | ------------------------------------------ |
| `auto`       | `gemini-3.1-pro-preview` | Default general choice                     |
| `pro`        | `gemini-3.1-pro-preview` | Deeper reasoning or quality-critical tasks |
| `flash`      | `gemini-3-flash-preview` | Fast, balanced tasks                       |
| `flash-lite` | `gemini-2.5-flash-lite`  | Cheapest or simplest tasks                 |

If you need a fixed target, pass the concrete model name directly (for example
`--model gemini-3-flash-preview`).

## Thinking / reasoning

There is **no CLI flag** to override thinking behavior per-call. However,
**`GEMINI_CLI_SYSTEM_SETTINGS_PATH`** (env var) provides a verified per-call
mechanism without touching persistent settings files.

### Verified approach 1: `GEMINI_CLI_SYSTEM_SETTINGS_PATH` (recommended for scripting)

Point to a temporary JSON file containing `customAliases`. System settings have
the **highest precedence** in the merge order (beats user + workspace settings),
and authentication is still read from `~/.gemini` as normal.

```bash
GEMINI=~/.nvm/versions/node/v22.18.0/bin/gemini

# One-liner: write temp settings, run, clean up
_TMPCFG=$(mktemp /tmp/gemini-cfg-XXXXXX.json)
cat > "$_TMPCFG" << 'EOF'
{
  "modelConfigs": {
    "customAliases": {
      "flash-low": {
        "modelConfig": {
          "model": "gemini-3-flash-preview",
          "generateContentConfig": {
            "thinkingConfig": { "thinkingLevel": "low" }
          }
        }
      }
    }
  }
}
EOF
GEMINI_CLI_SYSTEM_SETTINGS_PATH="$_TMPCFG" \
  $GEMINI -p "your prompt" --model flash-low --output-format json --approval-mode yolo
rm -f "$_TMPCFG"
```

Verified (2026-03-10): `thoughts: 0` in response stats, `EXIT: 0`, credentials
loaded from `~/.gemini` normally.

### Verified approach 2: custom aliases in persistent settings.json

Define a named alias that embeds the desired `thinkingConfig`, then pass the
alias name to `--model`. Verified working (2026-03-10) with the `thoughts`
token field in `--output-format json` stats:

| Alias config               | `thoughts` tokens      | Use case                              |
| -------------------------- | ---------------------- | ------------------------------------- |
| `thinkingLevel: "minimal"` | 0 (guaranteed minimal) | Cheapest, lowest latency              |
| `thinkingLevel: "low"`     | 0 (tested)             | Simple tasks, high throughput         |
| `thinkingLevel: "medium"`  | varies                 | Balanced                              |
| `thinkingLevel: "high"`    | varies (default)       | Deep reasoning (default for Gemini 3) |
| `thinkingBudget: 0`        | 0                      | Gemini 2.5 Flash: disable thinking    |
| `thinkingBudget: -1`       | dynamic                | Gemini 2.5: dynamic thinking          |

> **Model note:** `thinkingLevel` is for Gemini 3 series.
> `thinkingBudget` (integer tokens, 0 to 24576) is for Gemini 2.5 series.
> Do not mix them.

**Example `~/.gemini/settings.json` snippet:**

```json
{
  "modelConfigs": {
    "customAliases": {
      "flash-low": {
        "modelConfig": {
          "model": "gemini-3-flash-preview",
          "generateContentConfig": {
            "thinkingConfig": { "thinkingLevel": "low" }
          }
        }
      },
      "flash-minimal": {
        "modelConfig": {
          "model": "gemini-3-flash-preview",
          "generateContentConfig": {
            "thinkingConfig": { "thinkingLevel": "minimal" }
          }
        }
      },
      "flash25-no-think": {
        "modelConfig": {
          "model": "gemini-2.5-flash",
          "generateContentConfig": {
            "thinkingConfig": { "thinkingBudget": 0 }
          }
        }
      }
    }
  }
}
```

**Usage:**

```bash
GEMINI=~/.nvm/versions/node/v22.18.0/bin/gemini

# Low thinking (fast, cheap)
$GEMINI -p "Summarize this." --model flash-low --output-format json --approval-mode yolo

# Verify thinking tokens in response stats:
# .stats.models.<model>.tokens.thoughts == 0  → thinking suppressed
# .stats.models.<model>.tokens.thoughts > 0   → thinking active
```

### Default thinking behavior (no alias)

- `gemini-3-flash-preview` without config: **`high` (dynamic)** — `thoughts > 0`
- `gemini-2.5-flash-lite` without config: **no thinking by default**
- `gemini-2.5-pro` / `gemini-2.5-flash` without config: **dynamic thinking**

### Recommendations for this project

- **Quality-critical tasks** (review, plan finalize, R5_signoff): use default
  model without thinking override (keep `high`)
- **Cheap/fast steps** (gate, smoke-test, routing): use `flash-low` or
  `flash-minimal` alias to save cost
- **Gemini 2.5 Flash dispatch steps** (I3_apply, I4_gate): consider
  `thinkingBudget: 0` alias to match `gpt-5.1-codex-mini` cost tier

## Sessions and resume

- Gemini auto-saves conversations.
- `--list-sessions` and the interactive `/resume` or `/chat` browser are
  project-scoped; they only show sessions for the current project.
- Current local help documents `--resume latest` and `--resume <index>` as the
  safest selectors.
- Project verified facts also record successful headless `--resume <uuid>`
  usage. Because the current local help surface no longer advertises UUID
  selection directly, treat UUID resume as a probed capability, not a universal
  assumption.
- For robust scripted tracking, capture the `session_id` from `stream-json`
  `init` events and fall back to a fresh run if resume behavior is uncertain.
- `/chat` is an alias for `/resume`. Both expose the same session browser and
  manual checkpoint commands (`list`, `save`, `resume`, `delete`, `share`).

## PATH resolution

Gemini is currently available at:

```bash
~/.nvm/versions/node/v22.18.0/bin/gemini
```

If `gemini` is not on `PATH`, use the full path above.

## Full example

```bash
GEMINI=~/.nvm/versions/node/v22.18.0/bin/gemini

# 1. Review staged changes with machine-readable output
git diff --staged | $GEMINI \
  -p "Review the diff above. Return exactly 3 bullets: risks, missing tests, next step." \
  --model flash \
  --approval-mode plan \
  --output-format json > /tmp/gemini-review.json

# 2. Read the final answer
jq -r '.response' /tmp/gemini-review.json

# 3. Continue the same work later
$GEMINI --resume latest \
  -p "Continue the previous review and produce the final verdict." \
  --model pro \
  --output-format stream-json > /tmp/gemini-resume.jsonl

# 4. Extract the resumed session ID
jq -r 'select(.type == "init") | .session_id' /tmp/gemini-resume.jsonl
```
