---
name: agentorch-ctx
description: >
  Manage persistent context memory via agentorch ctx. Save decisions, search past knowledge,
  and track task state. Use proactively during every work session.
---

## Purpose

`agentorch ctx` is the project's persistent memory and Single Source of Truth.
Use it to save important decisions and findings so they survive across sessions.

## Rules

1. **Every session needs a task_id.** `agentorch task current` to check, `agentorch task create` to register.
2. **Use parent/child tasks.** If you're working on a sub-goal, create a child: `--parent <parent_id>`.
3. **Before deciding**, search: `agentorch ctx search-memory --query "<topic>" --type decision`
4. **If a conflicting decision exists**, ask the user which to keep. Never silently override.
5. **Record every significant decision** with `agentorch ctx log-decision`.
6. **Include `semantic_hint` (English)** in payloads for vector search. Other fields can be any language.

## Session Start

```bash
agentorch ctx get-project-context
TASK_ID=$(agentorch task current 2>/dev/null) || \
  TASK_ID=$(agentorch task create --summary "Work session" --provider codex)
agentorch ctx get-task-context --task-id "$TASK_ID"
```

## During Work

```bash
# Record a decision
echo '{"decision": "...", "reason": "...", "semantic_hint": "English summary"}' \
  | agentorch ctx log-decision --key <topic> --scope task/<TASK_ID> --stdin

# Record a finding or milestone
echo '{"observation": "...", "result": "...", "semantic_hint": "English summary"}' \
  | agentorch ctx log-episode --task-id <TASK_ID> --stdin

# Save task progress
echo '{"task_goal": "...", "progress": "...", "next_actions": [...]}' \
  | agentorch ctx update-task-context --task-id <TASK_ID> --expected-revision <N> --stdin
```

## Session End

```bash
echo '<final state>' | agentorch ctx update-task-context --task-id <TASK_ID> --expected-revision <N> --stdin
echo '<summary>' | agentorch ctx log-episode --task-id <TASK_ID> --stdin
agentorch task status "$TASK_ID" --set completed  # child task only; parent stays active if more work remains
```

## Important

- Do NOT edit files under `agentorch_ctx/artifacts/` directly
- All ctx commands return JSON; check `ok` field for success
- `agentorch task list --parent <id>` to see sibling tasks
- `agentorch ctx <command> --help` for detailed argument reference
