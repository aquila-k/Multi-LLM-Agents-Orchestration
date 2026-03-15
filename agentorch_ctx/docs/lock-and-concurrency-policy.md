# Lock And Concurrency Policy

## Status

1. Single-writer rule: fixed
2. Current enforced lock inventory: fixed
3. Stale lock recovery timing: draft

## Purpose

Define how the standalone runtime protects mutable state, manifests, and apply
operations when multiple workers or resume attempts exist.

## Core Rules

1. Workers generate artifacts. They do not directly own workspace writes.
2. A single writer owns apply and mutable manifest or state updates.
3. Append-only logs remain authoritative audit records.

## Current Enforced Locks

1. `apply.lock`

## Current Execution Assumption

1. the standalone runtime currently assumes a single controller drives one task
   execution path at a time
2. append-only artifacts and state snapshots are updated sequentially by that
   controller path
3. wider multi-writer locking can be added later if the runtime grows real
   concurrent execution surfaces

## Worker Prohibitions

1. direct source workspace edits
2. writes to shared mutable state paths
3. direct manifest mutation
4. bypassing apply readiness or approval rules

## Recovery Rule

Stale lock handling is a controlled recovery path. It must emit an audit event
before takeover and must not silently discard lock ownership history.
