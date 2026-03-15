# Routing Evaluation

## Status

1. Selection method: fixed
2. Exact weights and thresholds: draft
3. Exact provider and model ranking outcomes: fact-driven

## Purpose

Define how the standalone runtime selects strategy, provider, and model without
freezing volatile market outcomes into policy prose.

## Core Rule

Routing fixes the method, not the market result.

1. hard safety filters are deterministic
2. ranking uses explicit metrics and penalties
3. current provider or model rankings come from facts plus current task inputs

## Hard Filters

Candidates are excluded before ranking when:

1. a required capability is `unsupported`
2. a high-impact required capability is `unknown`
3. only `declared` evidence exists for a high-impact path without operator
   approval
4. budget hard cap would be exceeded
5. required fallback or stop behavior is unavailable
6. a security or policy guardrail fails

## Minimum Metrics

1. `capabilityFit`
2. `contextFit`
3. `toolFit`
4. `sessionFit`
5. `outputDisciplineFit`
6. `evidenceFit`
7. `reliabilityFit`
8. `costFit`
9. `latencyFit`
10. `mergeFit`

## Penalties

1. `normalizationBurden`
2. `providerUncertainty`
3. `knownBadPenalty`

## Required Trace

Automatic routing must persist:

1. candidates considered
2. hard filters applied
3. metric snapshots for selected and rejected top candidates
4. selected strategy, provider, and model
5. confidence and reason codes
