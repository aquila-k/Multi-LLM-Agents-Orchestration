
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
