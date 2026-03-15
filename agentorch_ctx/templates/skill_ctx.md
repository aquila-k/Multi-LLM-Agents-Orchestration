---
name: agentorch-ctx
description: Manage project context memory (decisions, episodes, task snapshots) via agentorch ctx. Use when you need to persist, search, or retrieve task context, decisions, or knowledge across sessions.
compatibility: Requires agentorch CLI installed (pip install agentorch-ctx). Context DB is initialized by `agentorch init`.
metadata:
  version: "1.0"
---

## Overview

`agentorch ctx` provides SQLite-backed context management for AI agents. It stores decisions, episodes, task snapshots, and project knowledge with full-text search and optional vector (semantic) search.

The context DB lives at `.contexts/local/context.db` within the project. All commands operate on this DB automatically.

## Commands

### Agent-facing commands

```bash
# Get task-level context (decisions, snapshots for a specific task)
agentorch ctx get-task-context --task-id <task_id>

# Get project-level context (project profile, policies, decisions)
agentorch ctx get-project-context

# Search context memory (full-text search)
agentorch ctx search-memory --query "authentication refactor"

# Update task snapshot (with CAS protection)
echo '{"snapshot": {...}}' | agentorch ctx update-task-context --task-id <id> --expected-revision 0 --stdin

# Log a decision
echo '{"title": "Use JWT", "rationale": "..."}' | agentorch ctx log-decision --key "auth-method" --stdin

# Log an episode (phase observation)
echo '{"observation": "Tests passed", "phase": "impl"}' | agentorch ctx log-episode --task-id <id> --stdin
```

### Operator commands

```bash
# Initialize context DB in current repo
agentorch ctx init

# Run diagnostic checks (9-point health check)
agentorch ctx doctor

# Apply pending schema migrations
agentorch ctx migrate

# Inspect a single entry by ID
agentorch ctx inspect-entry --entry-id <id>

# View revision history for a logical key
agentorch ctx list-history --key <logical_key>

# Rebuild FTS projections
agentorch ctx rebuild-projections

# Render context as markdown
agentorch ctx render-context --scope "project"
```

### Vector search commands (optional)

```bash
# Check vector search availability
agentorch ctx vector-doctor

# Set up vector search dependencies
agentorch ctx setup-vector

# Sync pending entries to vector index
agentorch ctx sync-vector-index

# Full vector index rebuild
agentorch ctx rebuild-vector-index --full
```

## Output format

All commands return JSON to stdout by default. Errors also return JSON with `"ok": false`. Some commands support `--format markdown` for human-readable output.

```json
{
  "ok": true,
  "command": "search-memory",
  "results": [...],
  "generated_at": "2026-03-15T06:00:00Z"
}
```

## Search modes

The `search-memory` command supports multiple modes:

| Mode     | Flag              | Description                          |
| -------- | ----------------- | ------------------------------------ |
| auto     | (default)         | Auto-selects based on query          |
| fts      | `--mode fts`      | Keyword-based full-text search       |
| semantic | `--mode semantic` | Meaning-based (requires vector deps) |
| hybrid   | `--mode hybrid`   | Combined FTS + semantic ranking      |

## Key concepts

- **Entry types**: task_snapshot, session_snapshot, decision, episode, procedural_rule, project_profile, policy
- **Scopes**: project, branch, task, session (hierarchical inheritance)
- **CAS protection**: Updates use `--expected-revision` for optimistic locking
- **Load policies**: Entries can auto-load on task start, explicit search, or always
