# Budget Policy

## Status

1. Budget gate behavior: fixed
2. Numeric defaults: draft only
3. Production caps: requires user decision

## Purpose

Define budget as a runtime gate for the standalone `collab/` dispatcher rather
than passive metadata.

## Core Rules

1. Budget checks happen before and during phase execution.
2. Hard-cap risk requires `STOP_AND_CONFIRM`.
3. Soft-cap pressure may rerank toward cheaper safe candidates, but must not
   silently bypass safety rules.

## Minimum Budget Scopes

1. task budget
2. phase budget
3. provider budget
4. daily or rolling-window budget
5. optional parallel review budget

## Minimum Budget Fields

1. `taskSoftCap`
2. `taskHardCap`
3. `phaseCaps`
4. `providerCaps`
5. `parallelReviewCap`
6. `budgetMode`
7. `estimatedNextCostClass`

## Strategy Budget Fields

1. `estimatedCallsMin`
2. `estimatedCallsDefault`
3. `estimatedCallsMax`
4. `requiresBudgetConfirm`
5. `enabled`

## Facts Boundary

Exact pricing, rate, and quota values must come from fact stores or explicit
user overrides, not from this policy document.

## Live Validation Cost Discipline

1. CLI behavior checks should use the cheapest suitable model for the target
   provider.
2. Higher-cost models are for quality, consistency, or release-default model
   evaluation only.
3. Validation records should state when a scenario used a higher-cost model and
   why.
