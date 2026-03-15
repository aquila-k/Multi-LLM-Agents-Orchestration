## agentorch — Multi-LLM Agent Orchestration

This project uses [agentorch](https://github.com/aquila-k/Multi-LLM-Agents-Orchestration.git) for multi-LLM agent orchestration and context management.

### Available commands

```bash
# Orchestration workflows
agentorch collab plan   --source <file>   # Generate a plan
agentorch collab impl   --source <file>   # Implement changes
agentorch collab review --source <file>   # Review codebase
agentorch collab harden --source <file>   # Apply hardening

# Context management
agentorch ctx doctor                      # Health check
agentorch ctx search-memory --query <q>   # Search context
agentorch ctx get-task-context --task-id <id>

# Diagnostics
agentorch doctor                          # Check environment
agentorch version                         # Show version
```

### Project layout

- `.agentorch/configs/` — Project-specific orchestration configs (editable)
- `.agentorch/artifacts/` — Generated task artifacts (gitignored)
- `.contexts/local/` — Context database and config (gitignored)
- `.contexts/cache/` — Semantic search cache (gitignored)
- `.contexts/run` — Thin wrapper for backward compatibility
