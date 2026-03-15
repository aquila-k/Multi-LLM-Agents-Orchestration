---
name: agentorch-collab
description: >
  Run plan/impl/review/harden workflows via agentorch collab. Use when the user asks to
  plan, implement, review, or harden code by delegating to external LLM providers
  (gemini, codex, copilot). Claude Code exclusive — other agents do not use this skill.
compatibility: Requires agentorch CLI installed. At least one provider CLI (gemini/codex/copilot) available.
metadata:
  version: "2.0"
---

## Overview

`agentorch collab` orchestrates multi-LLM workflows. It dispatches work to external
provider CLIs (gemini, codex, copilot) through a structured phase pipeline.

**This skill is for Claude Code only.** Other agents (Codex, Copilot, Gemini) are workers
called by this orchestrator — they do not invoke collab directly.

## Pre-flight

```bash
agentorch doctor   # Verify environment (providers, Python, pyyaml)
```

## Task Registration

Before starting any collab workflow, register the task:

```bash
TASK_ID=$(agentorch task create --summary "Refactor auth module" --provider claude)
```

This creates a tracked task in the registry. The collab run will link to it via `--collab-ref`.

## Invocation

```bash
agentorch collab <intent> --source /absolute/path/to/source.md
```

**Always use absolute paths for `--source`.**

### Intents

| Intent | Command | Description |
|--------|---------|-------------|
| plan | `agentorch collab plan --source <file>` | Generate a multi-agent plan |
| impl | `agentorch collab impl --source <file>` | Implement changes |
| review | `agentorch collab review --source <file>` | Review codebase |
| harden | `agentorch collab harden --source <file>` | Security hardening |
| review+harden | `agentorch collab review --source <file> --with-harden` | Combined |
| resume | `agentorch collab resume --source <file>` | Resume blocked task |

### Source File Formats

**Markdown** (simple):
```markdown
# Refactor the authentication module
Consolidate auth helpers into a single AuthService class.
```

**JSON** (structured):
```json
{
  "summary": "Refactor authentication module",
  "selectors": { "strategy": "COLLAB_IMPL_SAFE" },
  "targets": { "path": "src/auth/" },
  "constraints": { "disallowed_paths": ["src/auth/legacy/"] }
}
```

## Reading Output

```bash
# Concise summary
cat .agentorch/artifacts/tasks/<task_id>/shell-digests/shell-digest-*.json

# Full provider response
cat .agentorch/artifacts/tasks/<task_id>/responses/response-*.json

# Raw output text
cat .agentorch/artifacts/tasks/<task_id>/adapter/raw-output-*.txt
```

## STOP_AND_CONFIRM Handling

When the runtime prints `STOP_AND_CONFIRM`:

1. Read the pause confirmation file
2. Present findings to the user
3. After user approval, create resume JSON:

```json
{
  "task_id": "<blocked-task-id>",
  "summary": "Resuming after approval",
  "selectors": { "approval_continuation": "approved" }
}
```

```bash
agentorch collab resume --source /tmp/resume.json
```

## Phase Continuity

Plan → impl → review → harden must use the same task_id via resume JSON:

```json
{
  "task_id": "<task_id from plan>",
  "summary": "Continue to impl",
  "selectors": {
    "approval_continuation": "approved",
    "strategy": "COLLAB_IMPL_PATCH_FIRST",
    "phase": "impl"
  }
}
```

## Task Completion

After all phases complete:

```bash
agentorch task status "$TASK_ID" --set completed
```

## Common Strategies

| Intent | Strategy | Description |
|--------|----------|-------------|
| plan | `COLLAB_PLAN_FULL` | Full multi-agent plan |
| plan | `COLLAB_PLAN_MINIMAL` | Single-agent quick plan |
| impl | `COLLAB_IMPL_SAFE` | Analyze → implement → verify |
| review | `COLLAB_REVIEW_FULL` | Multi-lens review with signoff |
| harden | `COLLAB_HARDEN_FULL` | Threat model + fix + AI review |

Omit `selectors.strategy` to let the runtime auto-select.

## Integration with ctx

All collab runs automatically interact with the context DB:
- Task context is loaded at phase start
- Decisions and episodes are logged during execution
- Final state is persisted at phase end

Use `agentorch ctx get-task-context --task-id <ID>` to inspect what was recorded.
