---
applyTo: "**"
---

# agentorch ctx — Persistent Context Memory

This project uses `agentorch ctx` for persistent context management across sessions.
It is the Single Source of Truth for decisions, task state, and project knowledge.

## Required Workflow

### At session start:
1. `agentorch ctx get-project-context` — load project knowledge
2. `agentorch task current` — check for active task_id (exits 1 if none)
3. If resuming: `agentorch ctx get-task-context --task-id <ID>`
4. If new work: `agentorch task create --summary "..." --provider copilot`

### During work:
- **Before deciding**: `agentorch ctx search-memory --query "<topic>" --type decision`
- **After deciding**: `agentorch ctx log-decision --key <topic> --scope task/<ID> --stdin` with JSON payload
- **At milestones**: `agentorch ctx log-episode --task-id <ID> --stdin`
- **Periodically**: `agentorch ctx update-task-context --task-id <ID> --expected-revision <N> --stdin`

### At session end:
- Final `update-task-context` + `log-episode` summary

## Decision Conflict Rule

If `search-memory` returns an existing decision that contradicts your plan,
present both options to the user and let them choose. Never silently override.

## Notes
- All commands return JSON; include `semantic_hint` (English) in decision payloads for search
- Do NOT edit `agentorch_ctx/artifacts/` directly
- `agentorch ctx <command> --help` for details
