# Knowledge Persistence Policy

## Purpose

Define how the standalone `collab/` runtime persists task state, known
information, and immutable execution artifacts so long-running work can pause
and resume safely.

## Persistence Zones

### Mutable State

Mutable task state lives under `collab/state/tasks/<task_id>/`.

Required state files:

1. `controller-state.json`
2. `known-information.json`
3. `environment-signature.json`
4. `approval-state.json`
5. `resume-cursor.json`

### Immutable Artifacts

Append-only execution artifacts live under `collab/artifacts/tasks/<task_id>/`.

Required artifact families:

1. `intake/`
2. `requests/`
3. `resolved-config/`
4. `routing/`
5. `prompts/`
6. `adapter/`
7. `responses/`
8. `normalized/`
9. `validation/`
10. `execution-records/`
11. `apply-results/`
12. `checkpoints/`
13. `shell-digests/`
14. `summaries/`
15. `manifests/`
16. `pause-confirm/`
17. `phase-runs/`
18. `option-decisions/`
19. `strategy-switches/`
20. `consistency/`
21. `events.jsonl`
22. `decisions.jsonl`

## Ownership Rules

1. `state/` is runtime-owned mutable task data.
2. Controllers such as `Claude Code` may read summaries and stop reasons, but
   do not redefine `collab/` persistence semantics.
3. `artifacts/` is append-only and must preserve run history.
4. A retry creates a new attempt or run record and must not overwrite closed
   artifacts.
5. Human-readable summaries may be added, but the JSON canonical records remain
   source of truth.

## Known Information Rules

`known-information.json` stores task-local facts that the runtime may rely on during later steps or resume.

Each entry should capture at least:

1. `key`
2. `value`
3. `status`
4. `source`
5. `updated_at`
6. `affects`

Recommended `status` values:

1. `declared`
2. `observed`
3. `verified`
4. `superseded`

## Update Triggers

Update task-local knowledge when:

1. the user clarifies constraints or targets
2. operator approval changes the allowed path
3. validation returns a meaningful failure or warning
4. apply becomes blocked
5. a capability is newly probed or verified
6. shell digest re-ingestion yields a stable fact
7. a reference-derived rule is accepted into runtime policy

## Safety Rules

1. High-impact routing or apply decisions must rely on `verified` facts or explicit operator approval.
2. `declared` facts may inform analysis but must not authorize destructive or approval-sensitive actions.
3. Resume logic must prefer persisted state over conversational memory.
4. Missing state must fail closed rather than silently fabricating defaults.

## Merge Rules

1. Mutable state files may be replaced atomically by the runtime.
2. Artifact records are immutable once written.
3. New knowledge that supersedes older knowledge must preserve traceability to the prior entry.
4. Resume cursors and approval markers must always point to materialized artifacts or state snapshots.

## Deferred Items

The following are intentionally left for later phases:

1. retention windows
2. garbage collection policy
3. cross-task deduplication
4. renderer formats for human-facing dashboards
