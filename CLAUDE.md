# CLAUDE

## agentorch collab — Multi-LLM Orchestration (Claude Code exclusive)

This project uses `agentorch collab` to orchestrate plan/impl/review/harden workflows
across external LLM providers (gemini, codex, copilot).

### Quick Reference

```bash
agentorch doctor                                    # Environment check (run first)
agentorch collab plan   --source /path/to/goal.md   # Plan
agentorch collab impl   --source /path/to/task.json # Implement
agentorch collab review --source /path/to/task.md   # Review
agentorch collab harden --source /path/to/task.md   # Harden
agentorch collab resume --source /path/to/resume.json # Resume blocked
```

### Rules

- Register task before starting: `agentorch task create --summary "..." --provider claude`
- Use absolute paths for `--source`
- Phase continuity (plan→impl→review→harden) uses resume JSON with same task_id
- `--dry-run` for provider-free test runs
- Mark task complete: `agentorch task status <id> --set completed`
- Do NOT edit `agentorch_ctx/artifacts/` directly


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
