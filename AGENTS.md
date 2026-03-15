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
# Keyword search (always available)
.contexts/run search-memory --query "<keyword>" --limit 10 --format markdown

# Semantic / hybrid search (when vector search is set up)
.contexts/run search-memory --query "<natural language question>" --mode hybrid --limit 10
```

### Vector Search (Optional)

Enables semantic and hybrid search modes. FTS works without it.

```bash
.contexts/run setup-vector --dry-run   # preview disk/time requirements
.contexts/run setup-vector             # install locally
.contexts/run setup-vector --global    # install shared across projects
```

Once set up, `.contexts/run` uses vector search automatically. No entry point change required.

### Environment Variables

- `CONTEXTS_ENABLED=0` — disable context integration globally
- `CONTEXTS_CURRENT_TASK_ID` — set by dispatch scripts; hooks use this
- `CONTEXTS_BYTE_BUDGET` — max bytes for context injection (default: 8000)


## agentorch ctx — Persistent Context Memory

This project uses `agentorch ctx` for persistent context management.
It is the Single Source of Truth for decisions, task state, and project knowledge.

### Required Workflow

1. **Session start**: `agentorch ctx get-project-context` + `agentorch task current`
2. **Before deciding**: `agentorch ctx search-memory --query "<topic>" --type decision`
3. **After deciding**: record with `agentorch ctx log-decision --key <key> --scope task/<ID> --stdin`
4. **At milestones**: `agentorch ctx log-episode --task-id <ID> --stdin`
5. **Session end**: `agentorch ctx update-task-context` + `agentorch ctx log-episode`

### Commands

```bash
agentorch ctx get-project-context            # Load project knowledge
agentorch ctx get-task-context --task-id <ID> # Load task state
agentorch ctx search-memory --query "<q>"    # Search past decisions/episodes
agentorch ctx log-decision --key <k> --scope task/<ID> --stdin   # Record decision
agentorch ctx log-episode --task-id <ID> --stdin                 # Record milestone
agentorch ctx update-task-context --task-id <ID> --expected-revision <N> --stdin
```

### Rules

- Every session needs a task_id: `agentorch task create` / `agentorch task current`
- One active decision per key per scope — ask user to resolve conflicts
- Include English `semantic_hint` in decision payloads
- Do NOT edit `agentorch_ctx/artifacts/` directly
