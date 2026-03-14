## Context Management

Use `.contexts/` as persistent memory for this repo.

- Before work: `.contexts/run get-task-context --task-id <TASK_ID> --include-project --format markdown`
- After compression recovery: `.contexts/run render-context --scope task/<TASK_ID> --mode recency-weighted --max-bytes 8000 --format markdown`
- Log decisions: `.contexts/run log-decision --key <key> --scope task/<TASK_ID> --from-file decision.json`
- Search (keyword): `.contexts/run search-memory --query "<keyword>" --limit 10 --format markdown`
- Search (semantic/hybrid, when vector set up): `.contexts/run search-memory --query "<question>" --mode hybrid --limit 10`

Vector Search Setup (optional, enables semantic/hybrid modes):

```bash
.contexts/run setup-vector --dry-run   # preview requirements
.contexts/run setup-vector             # install (or --global to share across projects)
```

Environment:

- `CONTEXTS_ENABLED=0`
- `CONTEXTS_CURRENT_TASK_ID`
- `CONTEXTS_BYTE_BUDGET` (default: 8000)
