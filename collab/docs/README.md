# Collab Docs

## Purpose

`collab/docs/` holds the active standalone runtime policies and design notes
that implementation work may rely on.

## Canonical Sources

The following are the active source of truth for the standalone runtime:

1. `collab/docs/`
2. `.absolute-plan/collab-runtime-implementation/` for implementation planning
   and phase boundaries
3. `collab/configs/`
4. `collab/facts/`
5. `collab/interfaces/`, `collab/runtime/`, and `collab/schemas/`

Release gate references live here as well:

1. `collab/docs/release-gate-checklist.md`
2. `collab/docs/strategy-coverage-matrix.md`

## Reference-Only Sources

The following may be inspected for facts, but do not define current runtime
behavior:

1. `collab/new-v1/`
2. `agent-collab/`
3. `.absolute-plan/_archived/`
4. `.absolute-plan/gpt-deep-research.md`
5. `.references/`

## Update Rule

1. If runtime behavior changes, update the governing `collab/docs/` document in
   the same change set.
2. If a design choice is still open or validation-gated, keep the document
   explicit about that status.
3. Do not treat plans, archived scripts, or reference docs as implicit
   approval to change runtime behavior.
