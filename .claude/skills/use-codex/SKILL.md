# use-codex skill

Invoke the codex CLI non-interactively. Use this skill whenever you need to call codex directly.

## Quick reference

```bash
# Basic: pipe prompt from file, capture output to file
cat <prompt-file> | codex exec - --output-last-message <output-file>

# Override model (default is gpt-5.4 from ~/.codex/config.toml)
cat <prompt-file> | codex exec - --model gpt-5.1-codex-mini --output-last-message <output-file>

# Override reasoning effort (default is high from ~/.codex/config.toml)
cat <prompt-file> | codex exec - -c model_reasoning_effort=low --output-last-message <output-file>

# Override both
cat <prompt-file> | codex exec - --model gpt-5.1-codex-mini -c model_reasoning_effort=low --output-last-message <output-file>
```

## Rules

- **Always use stdin pipe** (`cat file | codex exec -`). Never use positional prompt arg — avoids ARG_MAX issues.
- **Always use `--output-last-message <file>`** for scripted use. Avoids parsing JSONL.
- **Never use `--reasoning-effort`** — that flag does NOT exist. Use `-c model_reasoning_effort=<level>` instead.
- **Never run `echo "..." | codex exec -`** for multiline prompts — always write to a temp file first.
- Separate codex invocation from other shell commands — do NOT chain with `&&` or `;` in the same Bash call.

## Available models (as of 2026-03)

| Model                | Use case              | Relative cost |
| -------------------- | --------------------- | ------------- |
| `gpt-5.4`            | Best quality, default | 1x            |
| `gpt-5.3-codex`      | Strong code work      | 1x            |
| `gpt-5.1-codex`      | Balanced              | 0.5x          |
| `gpt-5.1-codex-mini` | Fast gate/verify      | 0.33x         |

## Effort levels (via `-c model_reasoning_effort=`)

`low` | `mid` | `high` | `xhigh` — default is `high` (from `~/.codex/config.toml`)

## Default config (`~/.codex/config.toml`)

```toml
model = "gpt-5.4"
model_reasoning_effort = "high"
```

These are used when `--model` and `-c model_reasoning_effort=` are not specified.

## PATH resolution

codex is at `~/.nvm/versions/node/v22.18.0/bin/codex`.
If `codex` is not found on PATH, source NVM first:

```bash
source ~/.nvm/nvm.sh && codex exec ...
```

Or use full path: `~/.nvm/versions/node/v22.18.0/bin/codex exec ...`

## Background execution pattern

```bash
# Run in background and wait
cat /tmp/prompt.md | codex exec - --output-last-message /tmp/result.txt
# Then read result:
cat /tmp/result.txt
```

When using Bash tool with run_in_background=true:

- Do NOT chain commands after codex (no `&&`, no `;`, no `echo "EXIT:$?"`)
- Use TaskOutput to wait for completion

## Full example

```bash
# 1. Write prompt
cat > /tmp/myreview.md << 'EOF'
Review the following code for issues:
...
EOF

# 2. Run codex
cat /tmp/myreview.md | codex exec - --model gpt-5.1-codex-mini -c model_reasoning_effort=low --output-last-message /tmp/result.txt

# 3. Read result
cat /tmp/result.txt
```
