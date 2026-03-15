# Agentorch Release Gate Checklist

## Purpose

This checklist records the standalone stub release candidate status and
which live validations have been completed.

## Release Status

**Live activation cleared on 2026-03-08.**

Evidence is recorded in `agentorch_ctx/facts/probe-results/`:

- `check-entrypoint.json` — all 6 checks passed
- `check-live-providers.json` — gemini, codex, copilot all passed (cheap models)
- `check-resume.json` — all 5 state-machine / pause-confirm checks passed
- `check-review-harden.json` — all 5 composition / artifact-separation checks passed
- `check-artifacts.json` — all 5 artifact lineage checks passed
- `check-release-gate.json` — LIVE ACTIVATION CLEAR (7/7 gates)

Stub e2e coverage: 2 tests, 22 subtests, all passing.
Total test coverage: 41 tests (stub_e2e 2, integration 18, unit 19, regression 2).

## Previously Open Live Obligations (now closed)

1. Entrypoint and config resolution evidence — **CLEARED**
2. Prompt assembly, manifest, and lineage reproducibility — **CLEARED**
3. Provider CLI request/response, timeout, and session behavior — **CLEARED**
4. Pause/resume, approval, and resume-override behavior — **CLEARED**
5. Composed `review+harden` artifact separation — **CLEARED**
6. Artifact lineage and operator-visible rendering consistency — **CLEARED**
7. Final activation gate — **CLEARED**

## Remaining Deferred Obligations

None. All validation obligations are cleared.

## Operator Preconditions

Before a live validation result is treated as release evidence:

1. `codex`, `gemini`, and `copilot` must already be installed and available on
   `PATH`
2. required provider auth must already be completed
3. first-run trust-directory or similar local approval prompts must already be
   handled for the workspace under test
4. failures caused only by missing install or auth must be recorded as
   environment-readiness failures, not adapter defects

## Validation Cost Rule

1. simple CLI behavior checks should use the cheapest suitable model for the
   provider under test
2. higher-cost models are reserved for quality, consistency, or release-default
   behavior evaluation
3. if a higher-cost model is used for a live-check scenario, the reason must be
   recorded in the validation evidence

## Resume Validation Input

The canonical pre-live resume path uses a JSON source payload that includes:

1. existing `task_id`
2. summary for the resumed action
3. any updated targets or output contract needed for the resumed phase

The generated dispatcher request must reuse the existing task root instead of
creating a new task lineage.

## Release Candidate Rule

1. Stub coverage is sufficient for local standalone replacement confidence.
2. Live activation is cleared as of 2026-03-08 (see `check-release-gate.json`).
3. Any live-only gap must be tracked as validation debt, not hidden as an
   assumed capability.
4. `codex`, `gemini`, and `copilot` stdout/stderr separation confirmed via
   Phase 4 live evidence. All three providers passed the behavior probe
   using cheap validation models (gpt-5.1-codex-mini, gemini-2.5-flash-lite,
   gpt-5-mini).
5. Routine live-check evidence must not use unnecessarily costly model tiers.
   The validation models above satisfy this rule.

## Re-validation Triggers

Re-run `python3 agentorch_ctx/scripts/validation/run_checks.py` when any of the following change:

1. Provider adapter command-line flags (`agentorch_ctx/configs/providers/*.json`)
2. `agentorch_ctx/runtime/providers/*.py` execution logic
3. `agentorch_ctx/runtime/manifest_store.py` or `artifact_consistency.py` contracts
4. Provider CLI major version update (check `--help` surface for flag changes)
