# GEMINI

## agentorch ctx — Persistent Context Memory

This project uses `agentorch ctx` for persistent context management.
Single Source of Truth for decisions, task state, and knowledge.

### Required Workflow

1. **Session start**: `agentorch ctx get-project-context` + `agentorch task current`
2. **Before deciding**: `agentorch ctx search-memory --query "<topic>" --type decision`
3. **After deciding**: `agentorch ctx log-decision --key <key> --scope task/<ID> --stdin`
4. **At milestones**: `agentorch ctx log-episode --task-id <ID> --stdin`
5. **Session end**: `agentorch ctx update-task-context` + `agentorch ctx log-episode`

### Commands

```bash
agentorch ctx get-project-context            # Load project knowledge
agentorch ctx get-task-context --task-id <ID> # Load task state
agentorch ctx search-memory --query "<q>"    # Search past decisions/episodes
agentorch ctx log-decision --key <k> --scope task/<ID> --stdin
agentorch ctx log-episode --task-id <ID> --stdin
agentorch ctx update-task-context --task-id <ID> --expected-revision <N> --stdin
```

### Rules

- Every session needs a task_id: `agentorch task create` / `agentorch task current`
- One active decision per key — conflicting decisions require user resolution
- Include English `semantic_hint` in decision payloads for vector search
- Do NOT edit `agentorch_ctx/artifacts/` directly
