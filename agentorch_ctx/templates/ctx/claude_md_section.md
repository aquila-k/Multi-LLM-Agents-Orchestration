
## agentorch ctx — Persistent Context Memory

This project uses `agentorch ctx` as its Single Source of Truth for decisions, task state,
and knowledge. **Use it proactively in every session.**

### Mandatory Workflow

1. **Session start**: `agentorch ctx get-project-context` + `agentorch task current`
2. **Before any decision**: `agentorch ctx search-memory --query "<topic>" --type decision`
3. **After each decision**: `agentorch ctx log-decision --key <key> --scope task/<ID> --stdin`
4. **At milestones/errors**: `agentorch ctx log-episode --task-id <ID> --stdin`
5. **After context compression**: `agentorch task current` to recover task_id, then `get-task-context`
6. **Session end**: Final `update-task-context` + `log-episode` + `agentorch task status <id> --set completed`

### Rules

- Every session MUST have a task_id: `agentorch task create --summary "..." --provider <name>`
- One active decision per key per scope — conflicting decisions require user resolution
- Include English `semantic_hint` in decision payloads for vector search
- Do NOT edit `agentorch_ctx/artifacts/` directly
