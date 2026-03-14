# Verified Facts Governance

## Status

1. Fact separation rule: fixed
2. Promotion and invalidation logic: draft but actionable
3. Refresh automation: deferred

## Purpose

Define how volatile runtime facts are tracked without polluting standalone
runtime architecture and policy documents.

## Fact Families

1. `verified-facts/`
2. `probe-results/`
3. `provider-market-facts/`
4. `environment-signature.json`

## Core Rules

1. Architecture and policy documents define stable rules.
2. Volatile provider and environment facts live in fact stores.
3. Official documentation alone is not local verification.

## Promotion Rule

1. `declared -> probed` after local probe success
2. `probed -> verified` after repeated stable confirmation in the same or an
   equivalent environment signature
3. `verified -> stale` after TTL expiry or meaningful environment drift

## Invalidation Triggers

1. provider CLI version change
2. model alias or mapping change
3. adapter version change
4. shell or operating system change that affects execution semantics
5. explicit operator invalidation after a defect

## Facts Boundary

Current pricing, rate limits, model availability, and resume behavior must not
be written into architecture prose as if they were stable design facts.
