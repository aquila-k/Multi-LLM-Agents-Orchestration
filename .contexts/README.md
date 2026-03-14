# .contexts/ — Agent Context Management

A self-contained, SQLite-backed context memory tool for AI coding agents.
Persistent memory across sessions. Zero external services required in the default configuration.

---

## Quick Start

```bash
# Initialize (first time only)
.contexts/run init

# Health check
.contexts/run doctor

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
}' | .contexts/run update-task-context --task-id my-task --expected-revision 0 --stdin

# Read it back
.contexts/run get-task-context --task-id my-task

# Keyword search
.contexts/run search-memory --query "implement" --limit 5
```

---

## Execution Profiles

`.contexts/run` is the single entry point for all commands. It automatically detects
which Python interpreter to use by checking (in order):

1. `CONTEXTS_VECTOR_PYTHON` environment variable
2. Path saved in `.contexts/local/vector_python_path` (written by `setup-vector`)
3. `.venv-vector/bin/python` (repo-local, legacy)
4. `~/.contexts-vector/bin/python` (global install)
5. System `python3` (FTS-only fallback)

When a vector-capable interpreter is found, semantic/hybrid search is available automatically.
Otherwise, all commands work in FTS-only mode.

---

## Checking Vector Search Availability

Before using vector search features, check which profile is active:

```bash
.contexts/run vector-doctor
```

Key fields in the JSON response:

| Field | Meaning |
| --- | --- |
| `stack.profile` | `"vector-enabled"` or `"core"` |
| `stack.sqlite_vec.ok` | `true` if sqlite-vec is loaded |
| `stack.fastembed.ok` | `true` if embedding model is ready |
| `index.enabled` | `true` if the vector index has been built |
| `vec_table.entry_count` | number of entries in the vector index |
| `queue.total` | entries waiting to be embedded |

If no vector-capable interpreter is configured yet, `vector-doctor` reports the core profile and `.contexts/run` continues to work in FTS-only mode.

To check in a script:

```bash
profile=$(.contexts/run vector-doctor 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['stack']['profile'])" 2>/dev/null \
  || echo "core")
echo "Profile: $profile"
```

---

## Setting Up the Vector-Enabled Profile

```bash
# See what will be installed (shows disk/time warnings, no changes made)
.contexts/run setup-vector --dry-run

# Install locally (in .venv-vector/ next to .contexts/)
.contexts/run setup-vector

# Install globally to share across projects (saves ~400 MB per project)
.contexts/run setup-vector --global

# Install to a custom location
.contexts/run setup-vector --venv-path /opt/myteam/contexts-venv

# Verify setup
.contexts/run vector-doctor
```

Warnings and notes:

- First run downloads ~90 MB embedding model to `~/.cache/huggingface/`
- Total disk: ~400 MB packages + ~90 MB model
- Initial index build: 1–3 minutes
- FTS is available immediately without setup
- Use `--global` to share the Python packages across multiple repos (index stays project-local)

### Shared model cache

The embedding model weights are shared across projects via the Hugging Face cache:

```bash
export HF_HOME="$HOME/.cache/huggingface"
```

Only the vector index itself (inside `.contexts/local/context.db`) is project-local.

---

## Commands Reference

### Agent-Facing Commands (use these during normal work)

All commands output JSON. Use `--format markdown` for human-readable output where supported.

#### `get-project-context`

Retrieve project profile, decisions, and policies.

```bash
.contexts/run get-project-context
.contexts/run get-project-context --format markdown
```

#### `get-task-context`

Retrieve task snapshot, session snapshot, and task-scoped decisions.

```bash
.contexts/run get-task-context --task-id <TASK_ID>
.contexts/run get-task-context --task-id <TASK_ID> --include-project
.contexts/run get-task-context --task-id <TASK_ID> --session-id <SESSION_ID>
```

Key response fields: `task_snapshot`, `session_snapshot`, `decisions`.

#### `update-task-context`

Write or update a task or session snapshot. Uses CAS (compare-and-swap) to prevent overwrites.

```bash
# From stdin (pass --stdin flag)
echo '<payload JSON>' | .contexts/run update-task-context \
  --task-id <TASK_ID> \
  --expected-revision <N> \
  --stdin

# From file
.contexts/run update-task-context \
  --task-id <TASK_ID> \
  --expected-revision <N> \
  --from-file snapshot.json
```

`--expected-revision 0` for a new entry; use the current `revision` value for updates.
On conflict (CAS mismatch), the command returns `ok: false` with a `ConflictError` — re-fetch and retry.

Payload schema (task_snapshot):

```json
{
  "task_goal": "string (required)",
  "current_plan": "string",
  "progress": "string",
  "open_questions": ["string"],
  "blockers": ["string"],
  "relevant_files": ["path/string"],
  "assumptions": ["string"],
  "next_actions": ["string"]
}
```

#### `log-decision`

Record a design or operational decision.

```bash
echo '{
  "decision": "Use SQLite for local storage",
  "context": "Need offline-first, zero-dependency storage",
  "reason": "Avoids network dependency; FTS5 built in",
  "alternatives_considered": ["PostgreSQL", "DuckDB"]
}' | .contexts/run log-decision \
  --key storage-engine \
  --scope task/<TASK_ID> \
  --stdin
```

#### `search-memory`

Search across all memory entries.

**FTS-only or exact-match usage:**

```bash
.contexts/run search-memory --query "authentication" --limit 10
.contexts/run search-memory --query "authentication" --scope task/<TASK_ID>
.contexts/run search-memory --query "authentication" --type decision
```

**Semantic and hybrid usage (available automatically when vector setup is present):**

```bash
# Auto: FTS for identifiers/short queries; hybrid for natural language when vector is available
.contexts/run search-memory \
  --query "why did we choose this database" --mode auto

# Semantic: meaning-based, finds paraphrases
.contexts/run search-memory \
  --query "authentication approach" --mode semantic --limit 10

# Hybrid: FTS + semantic merged (best for most queries)
.contexts/run search-memory \
  --query "schema migration strategy" --mode hybrid --limit 10

# FTS only (always available, fast)
.contexts/run search-memory \
  --query "migration" --mode fts --limit 10
```

Mode selection guide:

| Query type | Recommended mode |
| --- | --- |
| Exact identifier, filename, task-id | `fts` |
| Short keyword (1-2 words) | `fts` |
| Natural language question | `hybrid` or `semantic` |
| "Why / how / what" questions | `semantic` |
| Unknown query type | `auto` (safe default) |

If you request `semantic` or `hybrid` before vector setup is installed, `.contexts/run` falls back to FTS and returns a setup hint.

Response fields: `results[].entry_id`, `results[].type`, `results[].key`, `results[].score`, `results[].excerpt`, `mode_used`.

#### `log-episode`

Record a phase observation (auto-keyed by timestamp, always auto-activates).

```bash
echo '{
  "observation": "FTS5 tokenizer strips Japanese punctuation",
  "action": "Added unicode61 tokenizer config",
  "result": "Japanese search now works correctly",
  "lesson": "Always test tokenizer with target language samples"
}' | .contexts/run log-episode --task-id <TASK_ID> --stdin
```

#### `propose-change`

Submit a change proposal for operator review (always `status: pending`).

```bash
echo '<payload>' | .contexts/run propose-change \
  --entry-type decision \
  --key <key> \
  --scope project/<PROJECT_ID> \
  --change-reason "Updated based on new requirements" \
  --stdin
```

---

### Operator Commands

Run these for maintenance and diagnostics. Not for use during normal agent work.

| Command | Purpose |
| --- | --- |
| `init` | Initialize `.contexts/local/` with config and DB |
| `doctor` | Health check: WAL, FTS, projections, schema version |
| `migrate` | Apply pending SQL migration files |
| `inspect-entry` | Dump all fields for a given `entry_id` |
| `list-history` | List all revisions for a logical key |
| `resolve-conflict` | Approve or reject a `pending` entry |
| `render-context` | Render Markdown summary for a scope |
| `rebuild-projections` | Rebuild `active_entries`, FTS index |
| `setup-vector` | Install optional vector search dependencies and save the interpreter path |
| `vector-doctor` | Show vector stack health and the active runtime profile |
| `sync-vector-index` | Consume dirty queue, update vector embeddings |
| `rebuild-vector-index` | Full or partial rebuild of the vector index |

#### `setup-vector`

```bash
.contexts/run setup-vector --dry-run
.contexts/run setup-vector
.contexts/run setup-vector --global
```

#### `vector-doctor`

```bash
.contexts/run vector-doctor
```

#### `sync-vector-index`

Run after bulk writes to keep the vector index current:

```bash
.contexts/run sync-vector-index --max-items 64
```

#### `rebuild-vector-index`

Use when changing the embedding model or after major data changes:

```bash
# Dry run (shows what would be processed, no writes)
.contexts/run rebuild-vector-index --dry-run

# Full rebuild
.contexts/run rebuild-vector-index --full

# Partial (entries updated since timestamp)
.contexts/run rebuild-vector-index --since 2026-01-01T00:00:00Z
```

---

## Typical Agent Workflow

### Session start

```bash
# 1. Get project-level context
.contexts/run get-project-context --format markdown

# 2. Get task-specific context
.contexts/run get-task-context --task-id <TASK_ID> --include-project --format markdown

# 3. Search for relevant past decisions (use hybrid if vector is available)
.contexts/run search-memory --query "<topic>" --limit 5
```

### During work

```bash
# Save progress checkpoint (increment expected-revision each time)
echo '<updated snapshot JSON>' | .contexts/run update-task-context \
  --task-id <TASK_ID> --expected-revision <CURRENT_REVISION> --stdin

# Record significant decisions as they are made
echo '<decision JSON>' | .contexts/run log-decision \
  --key <decision-key> --scope task/<TASK_ID> --stdin
```

### Session end

```bash
# Final snapshot with completed status
echo '<final snapshot JSON>' | .contexts/run update-task-context \
  --task-id <TASK_ID> --expected-revision <CURRENT_REVISION> --stdin

# Record episode summary
echo '<episode JSON>' | .contexts/run log-episode --task-id <TASK_ID> --stdin
```

---

## Entry Types and Payloads

### `task_snapshot` — current task state

```json
{
  "task_goal": "string (required)",
  "current_plan": "string",
  "progress": "string",
  "open_questions": ["string"],
  "blockers": ["string"],
  "relevant_files": ["string"],
  "assumptions": ["string"],
  "next_actions": ["string"]
}
```

### `session_snapshot` — current session state

```json
{
  "session_goal": "string (required)",
  "working_notes": "string",
  "recent_actions": ["string"],
  "pending_items": ["string"]
}
```

### `decision` — design or operational decision

```json
{
  "decision": "string (required)",
  "context": "string",
  "reason": "string",
  "alternatives_considered": ["string"],
  "impact": "string",
  "follow_up": "string"
}
```

### `episode` — phase observation

```json
{
  "observation": "string (required)",
  "thoughts": "string",
  "action": "string",
  "result": "string",
  "lesson": "string"
}
```

### `procedural_rule` — reusable process rule

```json
{
  "name": "string (required)",
  "instructions": "string",
  "when_to_use": "string",
  "checklist": ["string"],
  "examples": ["string"]
}
```

---

## Scope Reference

```
project/<PROJECT_ID>    — project-wide, requires operator approval to activate
branch/<BRANCH_REF>     — branch-scoped, requires operator approval
task/<TASK_ID>          — task-scoped, auto-activates
session/<SESSION_ID>    — session-scoped, auto-activates
```

More specific scopes inherit from broader ones. Use `task/<TASK_ID>` for most agent writes.

---

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `CONTEXTS_HOME` | (auto-detect) | Override DB instance directory |
| `CONTEXTS_DEBUG` | `0` | Verbose stderr output |
| `CONTEXTS_LOCK_TIMEOUT` | `30` | Write lock timeout (seconds) |
| `CONTEXTS_MAX_BYTES` | `32000` | Byte budget for context render |
| `CONTEXTS_VECTOR_PYTHON` | unset | Force `.contexts/run` to use a specific vector-capable Python interpreter |

---

## File Layout

```
.contexts/
  run                      ← unified entry point (auto-detects venv python, falls back to system python3)
  runtime/                 ← Python package
    vector/                ← vector search extension
  sql/
    0001_initial_schema.sql
    0002_fts_setup.sql
    0003_vector_tables.sql
    ext/
      vec_virtual_table.sql  ← applied only when vector-enabled
  schemas/                 ← payload validation schemas
  local/                   ← gitignored; instance data lives here
    config.json
    context.db
    vector_python_path     ← saved interpreter path written by setup-vector

.venv-vector/              ← gitignored; optional repo-local vector profile venv
```

---

## Requirements

| Profile | Python | Packages |
| --- | --- | --- |
| core | 3.8+ | stdlib only (sqlite3, json, hashlib) |
| vector-enabled | 3.12 | `sqlite-vec==0.1.6`, `fastembed==0.7.4` |
