# .contexts/ — Agent Context Management

A self-contained, SQLite-backed context memory tool for AI coding agents.
Persistent memory across sessions. Zero external services required in the default configuration.

**Note:** This directory contains only project-specific data. The runtime code is
bundled in the `agentorch_ctx` package (installed via `pip install agentorch-ctx`).

---

## Quick Start

```bash
# Initialize (first time only)
agentorch ctx init

# Health check
agentorch ctx doctor

# Write a task snapshot
echo '{
  "task_goal": "implement feature X",
  "current_plan": "step 1 → step 2",
  "progress": "not started",
  "open_questions": [],
  "blockers": [],
  "relevant_files": [],
  "assumptions": [],
  "next_actions": ["step 1"]
}' | agentorch ctx update-task-context --task-id my-task --expected-revision 0 --stdin

# Read it back
agentorch ctx get-task-context --task-id my-task

# Keyword search
agentorch ctx search-memory --query "implement" --limit 5
```

---

## Backward Compatibility

`.contexts/run` is a thin wrapper script maintained for backward compatibility with tools
and skill definitions that invoke it directly. It delegates to the installed `agentorch ctx`
command, falling back to vector-enabled Python interpreters and then to the development
source tree.

Resolution order:
1. Installed `agentorch` CLI (pip / uv)
2. `CONTEXTS_VECTOR_PYTHON` env var
3. `.contexts/local/vector_python_path` (written by `setup-vector`)
4. `.venv-vector/bin/python` (repo-local)
5. `~/.contexts-vector/bin/python` (global)
6. Development fallback (source repo PYTHONPATH)

---

## Commands Reference

### Agent-Facing Commands

All commands output JSON. Use `--format markdown` for human-readable output where supported.

| Command | Purpose |
|---------|---------|
| `get-project-context` | Retrieve project profile, decisions, and policies |
| `get-task-context` | Retrieve task snapshot, session snapshot, and task-scoped decisions |
| `update-task-context` | Write or update a task/session snapshot (CAS-protected) |
| `log-decision` | Record a design or operational decision |
| `log-episode` | Record a phase observation |
| `propose-change` | Submit a change proposal for operator review |
| `search-memory` | Search across all memory entries (FTS / semantic / hybrid) |

### Operator Commands

| Command | Purpose |
|---------|---------|
| `init` | Initialize context database |
| `doctor` | Health check (WAL, FTS, schema, projections, locks, config) |
| `migrate` | Apply pending SQL migrations |
| `inspect-entry` | Dump all fields for a given entry_id |
| `list-history` | List all revisions for a logical key |
| `resolve-conflict` | Approve or reject a pending entry |
| `render-context` | Render Markdown summary for a scope |
| `rebuild-projections` | Rebuild FTS index |
| `setup-vector` | Install optional vector search dependencies |
| `vector-doctor` | Show vector stack health |
| `sync-vector-index` | Process dirty queue, update embeddings |
| `rebuild-vector-index` | Full or partial vector index rebuild |

---

## Vector Search (Optional)

| Profile | Requirements | Search modes |
|---------|-------------|--------------|
| **core** (default) | Python 3.11+, SQLite | `fts` only |
| **vector-enabled** | Python 3.12+, `sqlite-vec`, `fastembed` | `fts`, `semantic`, `hybrid`, `auto` |

```bash
pip install agentorch-ctx[vector]    # Install vector dependencies
agentorch ctx setup-vector           # Build the vector index
agentorch ctx vector-doctor          # Verify setup
```

---

## File Layout

```
.contexts/
  run                      ← backward-compatible wrapper (delegates to agentorch ctx)
  README.md                ← this file
  local/                   ← gitignored; instance data lives here
    config.json
    context.db
    tasks.db               ← task registry
    vector_python_path     ← saved interpreter path (written by setup-vector)
```

Runtime code (Python modules, SQL migrations, schemas, templates) is bundled in the
`agentorch_ctx` package and is NOT stored in this directory.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTEXTS_HOME` | (auto-detect) | Override DB instance directory |
| `CONTEXTS_DEBUG` | `0` | Verbose stderr output |
| `CONTEXTS_LOCK_TIMEOUT` | `30` | Write lock timeout (seconds) |
| `CONTEXTS_MAX_BYTES` | `32000` | Byte budget for context render |
| `CONTEXTS_VECTOR_PYTHON` | unset | Force a specific vector-capable Python interpreter |

---

## Requirements

| Profile | Python | Packages |
|---------|--------|----------|
| core | 3.11+ | `pyyaml` (via agentorch-ctx) |
| vector-enabled | 3.12+ | `sqlite-vec>=0.1.6`, `fastembed>=0.4.0` |
