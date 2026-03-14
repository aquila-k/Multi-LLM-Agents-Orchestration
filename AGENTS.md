# AGENTS.md

## Denied Commands

DO NOT use the following commands without explicit permission, as they may cause significant issues.
Moving unnecessary files or directories to `.archive/` is acceptable, but NO commands that delete any files or directories are allowed.

### Filesystem Commands

| Command          | Exceptions                                                       |
| ---------------- | ---------------------------------------------------------------- |
| `rm -rf`         | NEVER                                                            |
| `find * -delete` | NEVER                                                            |
| `shared -u -z`   | NEVER                                                            |
| `unlink`         | NEVER                                                            |
| `rmdir`          | NEVER                                                            |
| `mv`             | ONLY for moving files or directories within the same repository. |

### Git Commands

| Command                                             | Exceptions                                               |
| --------------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------- |
| `git reset --hard`                                  | NEVER                                                    |
| `git clean -fd` / `git clean -fxd` / `git clean -f` | NEVER                                                    |
| `git * --force` / `git * -f` / `git * --hard`       | NEVER                                                    |
| `git add` / `git commit`                            |                                                          | ONLY with explicit permission and after thorough review. |
| `git push`                                          | ONLY with explicit permission and after thorough review. |

### Permissions/System Commands

| Command | Exceptions                                               |
| ------- | -------------------------------------------------------- |
| `sudo`  | NEVER                                                    |
| `chmod` | ONLY with explicit permission and after thorough review. |

## Context Management

This project uses `.contexts/` (SQLite-backed context manager) to maintain
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
