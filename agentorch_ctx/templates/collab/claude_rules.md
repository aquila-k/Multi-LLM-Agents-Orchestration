---
paths:
  - ".agentorch/**"
  - "agentorch_ctx/**"
---

# agentorch collab — Orchestration Rules

## Task Lifecycle

- Always register with `agentorch task create` before starting a collab workflow
- Link collab artifacts via `--collab-ref` when creating the task
- Update task status to `completed` or `failed` when all phases finish

## Phase Continuity

- Plan → impl → review → harden MUST use the same task_id
- Use resume JSON with `task_id` from the previous phase output
- Never start a new collab run with a fresh `--source` for continuation

## STOP_AND_CONFIRM

- When status is `blocked`, read the pause-confirm artifact
- Present the findings to the user for approval
- Resume only after explicit user approval

## Artifact Safety

- Do NOT edit files under `.agentorch/artifacts/` directly
- Do NOT modify `manifest.json` or `phase-run.json` manually
- Read artifacts through `cat` — the runtime manages their lifecycle

## Provider Selection

- Use `--strategy` only when the auto-routing makes a wrong choice
- Prefer embedding `selectors.strategy` in the JSON source file over CLI flags
