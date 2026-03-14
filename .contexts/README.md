# .contexts/ — Agent-Facing Context Management Tool

A self-contained, SQLite-backed context memory tool for AI coding agents.

## Quick Start

```bash
# Initialize (first time only)
.contexts/run init

# Check health
.contexts/run doctor | jq .

# Write a task snapshot
echo '{"task_goal":"implement X","current_plan":"step 1","progress":"not started","open_questions":[],"blockers":[],"relevant_files":[],"assumptions":[],"next_actions":["step 1"]}' \
  | .contexts/run update-task-context --task-id my-task --expected-revision 0

# Read it back
.contexts/run get-task-context --task-id my-task | jq .task_snapshot

# Search
.contexts/run search-memory --query "implement" --limit 5 | jq .results
```

## Commands

### Agent-Facing (6)

| Command               | Purpose                                       |
| --------------------- | --------------------------------------------- |
| `get-project-context` | Retrieve project profile, decisions, policies |
| `get-task-context`    | Retrieve task/session snapshots and decisions |
| `search-memory`       | FTS search across all memory entries          |
| `update-task-context` | Write/update task or session snapshot (CAS)   |
| `log-decision`        | Record a design or operational decision       |
| `propose-change`      | Submit a change proposal (always pending)     |

### Operator (8)

| Command               | Purpose                                          |
| --------------------- | ------------------------------------------------ |
| `init`                | Initialize the local instance (config.json + DB) |
| `doctor`              | Check health: WAL, FTS, projections, lock        |
| `migrate`             | Apply pending SQL migration files                |
| `inspect-entry`       | Dump all fields for an entry_id                  |
| `list-history`        | List revisions for a logical key                 |
| `resolve-conflict`    | Approve or reject a pending entry                |
| `render-context`      | Render formatted context for a scope             |
| `rebuild-projections` | Rebuild active_entries, active_policies, FTS     |

## Environment Variables

| Variable                | Default       | Description                            |
| ----------------------- | ------------- | -------------------------------------- |
| `CONTEXTS_HOME`         | (auto-detect) | Override DB instance directory         |
| `CONTEXTS_DEBUG`        | `0`           | Verbose stderr output                  |
| `CONTEXTS_LOCK_TIMEOUT` | `30`          | Write lock timeout (seconds)           |
| `CONTEXTS_MAX_BYTES`    | `32000`       | Default byte budget for context render |

## Requirements

- Python 3.8+
- SQLite with FTS5 support (most OS builds include it)

## File Layout

```
.contexts/
  run                      ← entry point
  runtime/                 ← Python package
  sql/                     ← migration files
  schemas/                 ← payload validation schemas
  templates/               ← render templates
  local/                   ← gitignored; DB lives here
    config.json
    context.db
```
