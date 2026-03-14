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
.contexts/run search-memory --query "<keyword>" --limit 10 --format markdown
```

### Environment Variables

- `CONTEXTS_ENABLED=0` — disable context integration globally
- `CONTEXTS_CURRENT_TASK_ID` — set by dispatch scripts; hooks use this
- `CONTEXTS_BYTE_BUDGET` — max bytes for context injection (default: 8000)
