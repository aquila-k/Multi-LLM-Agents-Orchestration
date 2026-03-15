---
paths:
  - ".agentorch/**"
  - ".contexts/**"
  - "agentorch_ctx/**"
---

# agentorch ctx — Context Management Rules

## Task ID Management

- Register task at session start: `agentorch task create --summary "..." --provider claude`
- Recover task_id after context compression: `agentorch task current`
- Mark task complete when done: `agentorch task status <id> --set completed`
- Check for stale tasks periodically: `agentorch task check`

## Decision Integrity

- Before recording a decision, search: `agentorch ctx search-memory --query "<topic>" --type decision`
- If a conflicting active decision exists for the same key, ask the user to resolve
- Never create two active decisions on the same key in the same scope
- Use `--change-reason` when superseding an existing decision

## Context Persistence

- Call `agentorch ctx update-task-context` at every significant milestone
- Call `agentorch ctx log-episode` when completing a phase or encountering an error
- Call `agentorch ctx log-decision` for every design/technical/operational decision
- Include `semantic_hint` (English) in payloads for vector search discoverability

## Prohibited Actions

- Do NOT edit files under `agentorch_ctx/artifacts/` or `.contexts/local/` directly
- Do NOT modify `context.db` with raw SQL — always use agentorch ctx commands
- Do NOT delete `.agentorch/state/current-task` during an active session
