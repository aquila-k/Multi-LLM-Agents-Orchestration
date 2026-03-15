---
name: agentorch-collab
description: Run plan, impl, review, or harden tasks through the agentorch collab runtime. Use when the user asks to plan, implement, review, or harden code and you need to delegate to an external LLM provider (gemini, codex, copilot). Accepts a structured JSON task file or a freeform markdown goal.
compatibility: Requires agentorch CLI installed (pip install agentorch-ctx). At least one provider CLI (gemini/codex/copilot) must be available.
metadata:
  version: "1.0"
---

## Overview

This skill invokes `agentorch collab <intent> --source <file>` to dispatch work to external LLM provider CLIs (gemini, codex, copilot). The runtime is fully self-contained:

- **Root is auto-detected** from the current working directory — never pass `--root` unless running from outside the project tree.
- **All task artifacts** land under `.agentorch/artifacts/tasks/<task_id>/` within the project.
- **Structured options** are embedded in a JSON source file, not scattered across CLI flags.

## Invocation

Always use the **`agentorch collab`** command.
The CLI resolves the repo root from the current working directory automatically,
so it works correctly as long as you run from within the project tree.

```bash
agentorch collab <intent> --source /absolute/path/to/source.md
```

Use **absolute paths** for `--source` to avoid any CWD-dependent resolution.

## Step-by-step

### Step 1 — Create a task source file

For simple cases, write a markdown file:

```markdown
# Refactor the authentication module

Consolidate the three auth helpers in src/auth/ into a single AuthService class.
Keep backward compatibility with existing callers.
```

For structured cases (explicit strategy, targets, constraints), write a JSON file:

```json
{
  "summary": "Refactor the authentication module",
  "selectors": {
    "strategy": "COLLAB_IMPL_SAFE"
  },
  "targets": {
    "path": "src/auth/"
  },
  "constraints": {
    "disallowed_paths": ["src/auth/legacy/"]
  },
  "phase_options": {
    "with_harden": false
  }
}
```

Save the file anywhere on disk (e.g., `/tmp/task.json` or inside the project).

### Step 2 — Run the command

```bash
agentorch collab plan   --source /absolute/path/to/task.md
agentorch collab impl   --source /absolute/path/to/task.json
agentorch collab review --source /absolute/path/to/task.md
agentorch collab harden --source /absolute/path/to/task.md
agentorch collab review --source /absolute/path/to/task.md --with-harden
```

`--dry-run` skips actual provider calls (useful for verifying artifact layout):

```bash
agentorch collab plan --source /tmp/task.md --dry-run
```

### Step 3 — Read the output

A successful run prints:

```
task_id:   my-task-20260308T120000Z
phases:    plan
status:    partial
artifacts: /path/to/project/.agentorch/artifacts/tasks/my-task-20260308T120000Z
run_log:   /path/to/project/.agentorch/artifacts/tasks/my-task-20260308T120000Z/phase-runs/phase-run.json
```

`status: partial` is normal for plan/review/harden (no files applied). `status: blocked` means stop-and-confirm triggered.

To read what the provider produced:

```bash
# Shell digest (concise summary of what happened)
cat .agentorch/artifacts/tasks/<task_id>/shell-digests/shell-digest-<phase>-*.json

# Full provider response
cat .agentorch/artifacts/tasks/<task_id>/responses/response-<phase>-*.json

# Raw provider output text
cat .agentorch/artifacts/tasks/<task_id>/adapter/raw-output-<phase>-*.txt
```

## Source file options reference

| Field                              | Type   | Description                                                       |
| ---------------------------------- | ------ | ----------------------------------------------------------------- |
| `summary`                          | string | Task description (used as task ID seed)                           |
| `selectors.strategy`               | string | Routing strategy ID (e.g. `COLLAB_PLAN_FULL`, `COLLAB_IMPL_SAFE`) |
| `targets.path`                     | string | Primary target directory or file for impl/review                  |
| `constraints.disallowed_paths`     | list   | Paths the provider must not modify                                |
| `phase_options.with_harden`        | bool   | Compose review+harden in one run (review only)                    |
| `phase_options.budget_profile_ref` | string | Budget profile (default: `budget-bootstrap`)                      |

## Handling STOP_AND_CONFIRM

If the task has approval gates, the runtime prints:

```
STOP_AND_CONFIRM: operator approval required before execution proceeds.
task_id:   <id>
state:     .agentorch/state/tasks/<id>/controller-state.json
```

To resume after the user approves, create a JSON resume payload:

```json
{
  "task_id": "<the-blocked-task-id>",
  "summary": "Resuming after approval",
  "selectors": { "approval_continuation": "approved" }
}
```

Then run:

```bash
agentorch collab resume --source /tmp/resume.json
```

## Common strategy IDs

| Intent | Strategy              | Description                    |
| ------ | --------------------- | ------------------------------ |
| plan   | `COLLAB_PLAN_FULL`    | Full multi-agent plan pipeline |
| plan   | `COLLAB_PLAN_MINIMAL` | Single-agent quick plan        |
| impl   | `COLLAB_IMPL_SAFE`    | Analyze, implement, verify     |
| review | `COLLAB_REVIEW_FULL`  | Multi-lens review with signoff |
| harden | `COLLAB_HARDEN_FULL`  | Threat model + fix + AI review |

Omit `selectors.strategy` to let the runtime auto-select based on task complexity.

---

## Workflow Continuity Rules (MANDATORY)

### Rule 1 — plan, impl, review, harden must use the same task ID

`agentorch collab <intent> --source <file>` generates a new `task_id` each time.
After plan, continue to impl/review/harden using resume JSON with the same `task_id`.

### Rule 2 — Phase continuation uses resume JSON

After plan completes, start impl with a **resume JSON** targeting the same `task_id`:

```json
{
  "task_id": "<task_id from plan output>",
  "summary": "...",
  "selectors": {
    "approval_continuation": "approved",
    "strategy": "COLLAB_IMPL_PATCH_FIRST",
    "phase": "impl",
    "step": "I0_analyze"
  }
}
```

```bash
agentorch collab resume --source /tmp/resume-impl.json
```

The same pattern applies for impl to review to harden transitions.
