# Operator Approval Policy

## Status

1. Stop categories: fixed
2. Exact UX wording: open
3. Operator decision schema: draft

## Purpose

Define when the standalone runtime must stop or pause for operator judgment and
which artifacts must exist at that boundary.

## Core Rules

1. The runtime proceeds autonomously where safe.
2. The runtime stops when approval, clarification, or unresolved safety
   judgment is required.
3. `autoAdvance` never bypasses first-class confirmation categories.

## First-Class Stop Categories

1. `approval_required`
2. `task_ambiguity`
3. `missing_tool_or_auth`
4. `provider_retry_exhausted`
5. `unsafe_apply`
6. `budget_stop`
7. `strategy_budget_preflight`
8. `resume_override_conflict`
9. `provider_capability_mismatch`
10. `artifact_consistency_failure`

## Required Operator Artifacts

1. stop reason
2. reason code
3. severity
4. recommended action
5. resume options
6. required artifact refs
7. operator decision record
