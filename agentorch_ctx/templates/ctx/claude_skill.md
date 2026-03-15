---
name: agentorch-ctx
description: >
  Manage persistent context memory via agentorch ctx. Use PROACTIVELY to save decisions,
  track task state, and recover context after compression. This skill should be invoked
  continuously throughout every work session — not just when explicitly asked.
compatibility: Requires agentorch CLI installed (pip install agentorch-ctx).
metadata:
  version: "2.0"
---

## Purpose

`agentorch ctx` is the project's Single Source of Truth for decisions, task state, and
knowledge. Context windows compress — this database does not. Every important piece of
information must be persisted here so it can be recovered.

## Critical Rules

1. **Every work session MUST have a task_id.** Register with `agentorch task create`.
2. **If you forget your task_id** (context compressed), run `agentorch task current`.
3. **Use parent/child tasks** for multi-step or delegated work (see Task Hierarchy below).
4. **Before making a decision**, search for existing decisions on the same topic.
   If a conflicting decision exists, ask the user which one to keep.
5. **One active decision per key per scope.** Never create contradictory parallel decisions.
6. **Include `semantic_hint` in English** in decision/episode payloads for vector search.
   Other fields may be in any language.

## Task Hierarchy

```
Parent task: overall goal (e.g., "Refactor auth module")
  ├── Child: sub-goal or phase (e.g., "Plan: refactor auth", collab plan)
  ├── Child: sub-goal or phase (e.g., "Impl: refactor auth", collab impl)
  └── Child: delegated work   (e.g., "Analyze DB queries", delegated to codex)
```

**Rules:**
- Create a **parent task** for the user's top-level request
- Create **child tasks** (with `--parent`) for each phase, delegation, or sub-goal
- Mark child tasks `completed`/`failed` as they finish
- Mark the parent task `completed` only when ALL children are done
- `agentorch task list --parent <id>` shows progress of all children

## Lifecycle

### Session Start (ALWAYS do this first)

```bash
# 1. Load project knowledge
agentorch ctx get-project-context

# 2. Check for active task
TASK_ID=$(agentorch task current 2>/dev/null) || TASK_ID=""

# 3. If resuming, load task context
if [ -n "$TASK_ID" ]; then
  agentorch ctx get-task-context --task-id "$TASK_ID" --include-project
fi

# 4. If starting new work, register a parent task
TASK_ID=$(agentorch task create --summary "Refactor auth module" --provider claude)
```

### When Delegating Work (collab or sub-agents)

```bash
# Create a child task for each delegation
CHILD=$(agentorch task create \
  --summary "Plan: refactor auth" \
  --parent "$TASK_ID" \
  --provider claude \
  --collab-ref "$COLLAB_ARTIFACT_ID")

# Run the delegated work
agentorch collab plan --source goal.md

# Mark the child completed when done
agentorch task status "$CHILD" --set completed

# Create next child for next phase
CHILD=$(agentorch task create \
  --summary "Impl: refactor auth" \
  --parent "$TASK_ID" \
  --provider claude)
```

### During Work (do these as events occur)

#### When you make a decision:
```bash
# First check for existing decisions on this topic
agentorch ctx search-memory --query "<topic>" --type decision

# Record the decision (include semantic_hint in English for vector search)
echo '{
  "decision": "Use React for the UI framework",
  "context": "SPA required, team has React experience",
  "reason": "Lower learning curve, rich ecosystem",
  "alternatives_considered": ["Vue", "Svelte"],
  "semantic_hint": "UI framework selection: chose React over Vue and Svelte"
}' | agentorch ctx log-decision --key ui-framework --scope task/<TASK_ID> --stdin
```

#### When you complete a milestone or encounter an error:
```bash
echo '{
  "observation": "Authentication module refactored to use JWT",
  "action": "Replaced session-based auth with stateless JWT tokens",
  "result": "All 42 tests pass",
  "lesson": "JWT refresh token rotation needs explicit test coverage",
  "semantic_hint": "JWT auth refactoring completed successfully, all tests pass"
}' | agentorch ctx log-episode --task-id <TASK_ID> --stdin
```

#### Periodically save task state:
```bash
echo '{
  "task_goal": "Refactor authentication module",
  "current_plan": "1. Replace session auth → 2. Add JWT → 3. Update tests",
  "progress": "Step 2 complete, starting step 3",
  "open_questions": ["Should refresh tokens expire after 7 or 30 days?"],
  "blockers": [],
  "relevant_files": ["src/auth/jwt.ts", "tests/auth/"],
  "assumptions": ["Backend supports RS256 signing"],
  "next_actions": ["Write JWT refresh token tests"]
}' | agentorch ctx update-task-context --task-id <TASK_ID> --expected-revision <N> --stdin
```

### After Context Compression (CRITICAL)

If you notice you've lost context (can't remember earlier details):

```bash
# 1. Recover task_id
TASK_ID=$(agentorch task current)

# 2. Reload full task context
agentorch ctx get-task-context --task-id "$TASK_ID" --include-project

# 3. Check child tasks for progress overview
agentorch task list --parent "$TASK_ID"

# 4. Search for specific lost information
agentorch ctx search-memory --query "<what you're trying to remember>"
```

### Session End

```bash
# Final task snapshot
echo '<final state JSON>' | agentorch ctx update-task-context \
  --task-id <TASK_ID> --expected-revision <N> --stdin

# Session summary episode
echo '{
  "observation": "Session complete: auth refactoring finished",
  "action": "Implemented JWT auth, updated 42 tests",
  "result": "All tests pass, ready for review",
  "lesson": "Start with integration tests when refactoring auth",
  "semantic_hint": "Auth refactoring session completed: JWT implementation done"
}' | agentorch ctx log-episode --task-id <TASK_ID> --stdin

# Mark current child task completed (NOT the parent, unless all work is done)
agentorch task status "$CHILD_TASK_ID" --set completed

# If ALL work is truly done, mark the parent completed too
agentorch task status "$PARENT_TASK_ID" --set completed
```

## Decision Conflict Resolution

When `search-memory` returns an existing decision that contradicts your planned decision:

1. **Do NOT silently overwrite.** Present both decisions to the user.
2. Ask: "Existing decision for `<key>`: `<old>`. I want to decide `<new>`. Which should we keep?"
3. If the user chooses the new one, log it with `--change-reason` explaining the override.
4. The old decision is automatically superseded (revision history preserved).

## Search Tips

| Query type | Recommended mode |
|---|---|
| Exact keyword, filename, task-id | `--mode fts` |
| Natural language question | `--mode hybrid` or `--mode semantic` |
| Unknown | `--mode auto` (default) |
