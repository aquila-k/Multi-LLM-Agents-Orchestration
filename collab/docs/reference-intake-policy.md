# Reference Intake Policy

## Purpose

Define the only allowed path for bringing knowledge from legacy
implementations or external references into the standalone `collab/` runtime.

## Policy

1. `collab/` is the only implementation namespace for the new runtime.
2. `.absolute-plan/collab-runtime-implementation/` remains the canonical
   implementation plan and phase-definition source.
3. Active runtime rules must be written back into `collab/docs/`,
   `collab/configs/`, `collab/facts/`, or executable code under `collab/`.
4. `collab/new-v1/` and `agent-collab/` are reference-only.
5. Reference-only paths may be inspected for facts, but must
   never become runtime dependencies.
6. Knowledge learned from references is not implementation-ready until it is
   written back into `collab/docs/`.

## Allowed Reference Sources

1. `.absolute-plan/collab-runtime-implementation/` planning material used as
   the active implementation plan.
2. `collab/new-v1/` design notes inspected for factual design context.
3. Legacy repository code and scripts inspected only for factual behavior.
4. External vendor or tool documentation when the runtime needs provider facts or capability clarification.

## Mandatory Workflow

1. Inspect the source and extract only concrete facts.
2. Write a note under `collab/docs/reference-notes/` or update an existing `collab/docs/` policy/design document.
3. Record which contract area is affected: `contract`, `state`, `apply`, `routing`, `validation`, or `knowledge`.
4. If the fact changes runtime rules, update the governing document before touching code.
5. Only after the write-back is complete may the fact influence implementation work.

## Reference Note Minimum Contents

1. Source path or source URL.
2. Inspection date.
3. Concrete fact summary.
4. Confidence level: `observed`, `inferred`, or `verified`.
5. Affected contract area.
6. Follow-up action, if any.

## Prohibited Behavior

1. Copying code or prompts from legacy paths into `collab/`.
2. Creating compatibility shims that call legacy scripts.
3. Carrying implementation details by memory without a write-back note.
4. Treating unverified market facts or capability claims as safe apply/routing inputs.
5. Treating reference-only documents as if they overrode active
   `collab/docs/` policy.

## Review Gate

Implementation work must stop when any of the following is true.

1. The only source for a claim is memory.
2. A referenced fact has not been written back into `collab/docs/`.
3. A contract change is required but the governing design document has not been updated.
4. The proposed implementation would introduce a dependency on a non-`collab/` runtime path.
