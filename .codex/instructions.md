## Context Management

This Codex workflow uses `.contexts/` (SQLite-backed context manager) to maintain
persistent task state, decisions, and episode history across sessions and
after context compression.

### On Task Start

Before beginning work on any task, retrieve stored context:

```bash
.contexts/run get-task-context --task-id <TASK_ID> --include-project --format markdown
```

### After Compression

If context appears lost after compression, run:

```bash
.contexts/run render-context --scope task/<TASK_ID> --mode recency-weighted --max-bytes 8000 --format markdown
```

### Recording Decisions

When making significant decisions:

```bash
.contexts/run log-decision --key <key> --scope task/<TASK_ID> --from-file decision.json
```

### Search Memory

```bash
# Keyword search (always available)
.contexts/run search-memory --query "<keyword>" --limit 10 --format markdown

# Semantic / hybrid search (available when vector search is set up)
.contexts/run search-memory --query "<natural language question>" --mode hybrid --limit 10
```

If `semantic` or `hybrid` falls back to FTS, the response includes `vector_unavailable: true` and a `setup_hint`.

### Vector Search Setup (Optional)

Vector search enables semantic and hybrid search modes. To install:

```bash
.contexts/run setup-vector --dry-run   # preview disk/time requirements
.contexts/run setup-vector             # install (local)
.contexts/run setup-vector --global    # install shared across projects
```

Once installed, `.contexts/run` uses it automatically. No entry point change needed.

### Environment Variables

- `CONTEXTS_ENABLED=0` — disable context integration globally
- `CONTEXTS_CURRENT_TASK_ID` — set by dispatch scripts; hooks use this
- `CONTEXTS_BYTE_BUDGET` — max bytes for context injection (default: 8000)
