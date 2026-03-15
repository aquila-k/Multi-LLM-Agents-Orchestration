---
applyTo: "**"
---

# agentorch ctx — Persistent Context Memory

This project uses `agentorch ctx` for persistent context management across sessions.
It is the Single Source of Truth for decisions, task state, and project knowledge.
These requirements only take effect when the agent actually executes the commands.
Describing the workflow is not sufficient.

## Required Workflow

### At session start:
1. `agentorch ctx get-project-context` — load project knowledge
2. `TASK_ID=$(agentorch task current 2>/dev/null)` — recover the active task if one exists
3. If `TASK_ID` is set: `agentorch ctx get-task-context --task-id "$TASK_ID" --include-project`
4. If `TASK_ID` is empty: `TASK_ID=$(agentorch task create --summary "..." --provider copilot)`
5. Keep using that same `TASK_ID` for all later `agentorch ctx` writes in the session

### During work:
- **Before deciding**: `agentorch ctx search-memory --query "<topic>" --type decision`
- **After deciding**: `agentorch ctx log-decision --key <topic> --scope task/<ID> --stdin` with JSON payload
- **At milestones**: `agentorch ctx log-episode --task-id <ID> --stdin`
- **Periodically**: `agentorch ctx update-task-context --task-id <ID> --expected-revision <N> --stdin`

### At session end:
- Final `update-task-context` + `log-episode` summary

## Execution Rule

- Run the commands, do not just mention them in prose.
- If a command fails, surface that failure instead of pretending the DB was updated.
- If `agentorch task current` returns nothing, create a new task before writing decisions or snapshots.

## Decision Conflict Rule

If `search-memory` returns an existing decision that contradicts your plan,
present both options to the user and let them choose. Never silently override.

## Notes
- All commands return JSON; include `semantic_hint` (English) in decision payloads for search
- Do NOT edit `agentorch_ctx/artifacts/` directly
- `agentorch ctx <command> --help` for details