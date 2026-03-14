# use-copilot skill

Invoke the copilot CLI non-interactively. Use this skill whenever you need to call copilot directly.

## Quick reference

```bash
COPILOT=~/.nvm/versions/node/v22.18.0/bin/copilot

# Basic: prompt from string, silent output
$COPILOT -p "$(cat <prompt-file>)" --model claude-sonnet-4.6 --allow-all-tools --silent --no-ask-user

# With file read limit (for large prompts — copilot has 50KB hard limit)
$COPILOT -p "$(cat <prompt-file>)" --model claude-haiku-4.5 --allow-all-tools --silent --no-ask-user

# Resume most recent session
$COPILOT --continue -p "<follow-up prompt>" --allow-all-tools --silent
```

## Rules

- **Always use `-p "$(cat <file>)"`** for file-based prompts — never use positional arg or redirection
- **50KB hard limit on prompt size** — use digest/summary if prompt is large
- **Always include `--allow-all-tools`** for non-interactive use (required, or tool calls prompt for approval)
- **Always include `--silent`** for scripted use — suppresses stats, outputs only agent response
- **Always include `--no-ask-user`** — prevents copilot from asking clarifying questions mid-run
- **`--reasoning-effort` is NOT a CLI flag** — there is no CLI flag for it
- Separate copilot invocation from other shell commands in Bash tool — never chain with `&&`

## Setting reasoning effort

Effort levels: `low` | `medium` | `high` | `xhigh` — default is `medium` (from `~/.copilot/config.json`)

**`COPILOT_REASONING_EFFORT` env var works for per-call override** (confirmed via `reasoningOpaque` blob size measurement). It is NOT listed in official CLI docs, but is honored by copilot at runtime — especially `xhigh` shows a clear 2x increase in thinking budget.

```bash
# Per-invocation override (undocumented but confirmed working)
COPILOT_REASONING_EFFORT=high $COPILOT -p "..." --model claude-sonnet-4.6 --allow-all-tools --silent --no-ask-user
COPILOT_REASONING_EFFORT=low  $COPILOT -p "..." --model claude-haiku-4.5  --allow-all-tools --silent --no-ask-user
```

Persistent setting in `~/.copilot/config.json`:

```json
{ "reasoning_effort": "high" }
```

**Note:** `gpt-5-mini` and `gpt-4.1` (free tier) return a fixed-size reasoning blob regardless of effort — they do not appear to support extended thinking. Use `claude-*` or `gpt-5.*` models for effort to have effect.

## Available models (as of 2026-03)

| Model                  | Cost  | Notes                        |
| ---------------------- | ----- | ---------------------------- |
| `claude-sonnet-4.6`    | 1x    | Default, best Claude quality |
| `claude-sonnet-4.5`    | 1x    | Previous sonnet              |
| `claude-haiku-4.5`     | 0.33x | Fast Claude                  |
| `claude-opus-4.6`      | 3x    | Highest capability           |
| `claude-opus-4.5`      | 3x    | Previous opus                |
| `claude-sonnet-4`      | 1x    |                              |
| `gemini-3-pro-preview` | 1x    | Gemini via copilot           |
| `gpt-5.4`              | 1x    | OpenAI frontier              |
| `gpt-5.3-codex`        | 1x    |                              |
| `gpt-5.2-codex`        | 1x    |                              |
| `gpt-5.2`              | 1x    |                              |
| `gpt-5.1-codex-max`    | 1x    |                              |
| `gpt-5.1-codex`        | 1x    |                              |
| `gpt-5.1`              | 1x    |                              |
| `gpt-5.1-codex-mini`   | 0.33x |                              |
| `gpt-5-mini`           | 0x    | Free                         |
| `gpt-4.1`              | 0x    | Free                         |

## PATH resolution

copilot is at `~/.nvm/versions/node/v22.18.0/bin/copilot`.
If `copilot` is not found on PATH:

```bash
source ~/.nvm/nvm.sh
copilot -p "..." --allow-all-tools --silent
```

Or use full path directly: `~/.nvm/versions/node/v22.18.0/bin/copilot`

## Session state

Sessions are stored in `~/.copilot/session-state/<uuid>/`.
To retrieve output from a previous session:

```bash
python3 -c "
import json
with open('~/.copilot/session-state/<uuid>/events.jsonl') as f:
    for line in reversed(f.readlines()):
        obj = json.loads(line)
        if obj.get('type') == 'assistant.message':
            print(obj['data']['content'])
            break
"
```

## Usage policy (project-specific)

- **Max 2 copilot calls per task phase** — prefer gemini or codex for repeated calls
- Use `claude-sonnet-4.6` for quality-critical reviews only
- Use `gpt-5-mini` (0x cost) for validation/smoke-test

## Full example

```bash
COPILOT=~/.nvm/versions/node/v22.18.0/bin/copilot

# Write prompt to temp file first (never inline large prompts)
cat > /tmp/copilot-prompt.md << 'EOF'
Review this design and identify the top 3 issues:
...
EOF

# Run copilot
$COPILOT \
  -p "$(cat /tmp/copilot-prompt.md)" \
  --model claude-sonnet-4.6 \
  --allow-all-tools \
  --silent \
  --no-ask-user

# Output goes to stdout — capture if needed
$COPILOT -p "$(cat /tmp/copilot-prompt.md)" --model claude-haiku-4.5 --allow-all-tools --silent --no-ask-user > /tmp/result.txt
```

## Background execution

When using Bash tool with run_in_background=true:

- Do NOT chain commands after copilot invocation
- Use TaskOutput tool to wait for completion
