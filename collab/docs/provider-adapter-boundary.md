# Provider Adapter Boundary

## Status

1. Adapter boundary: fixed
2. Stub-first and live-later split: fixed
3. Exact CLI flags and resume behavior: live-validation gated

## Purpose

Define what provider adapters may own inside the standalone `collab/` runtime
and which decisions must stay outside the adapter layer.

## Core Rule

Provider-specific differences are absorbed inside adapters. Phase logic,
routing, prompt assembly, validation, and state management do not construct
provider CLI flags directly.

## Adapter Inputs

1. prompt bundle ref or payload
2. provider and model selection
3. provider option map
4. session mode request
5. timeout and retry settings
6. output contract expectation
7. artifact destination refs

## Adapter Outputs

1. adapter execution metadata
2. raw output ref or omission reason
3. parsed envelope or parseable payload
4. session token or session metadata if produced
5. exit status and timestamps

## Adapters May Own

1. provider-specific flag assembly
2. provider-specific resume invocation form
3. provider-specific command path lookup
4. provider-specific structured-output invocation style

## Adapters May Not Own

1. phase progression decisions
2. strategy selection
3. budget decisions
4. approval decisions
5. validation readiness
6. apply decisions

## Implemented Touchpoints

The current standalone runtime inserts adapters at:

1. `collab/runtime/providers/__init__.py`
2. `collab/runtime/providers/base.py`
3. `collab/runtime/providers/codex.py`
4. `collab/runtime/providers/gemini.py`
5. `collab/runtime/providers/copilot.py`
6. `collab/runtime/runtime_coordinator.py`

Live-validation corrections should first be written back to:

1. `collab/configs/providers/*.json` for command, model, timeout, or retry defaults
2. `collab/facts/verified-facts/*.json` for promoted or corrected capability evidence
3. `collab/facts/validation-debt.json` for unresolved provider claims
4. `collab/docs/release-gate-checklist.md` and `V10` for procedure updates

## Current Pre-Live Expectations

The current research digest does not widen the adapter boundary. It sharpens
the validation targets that still need live evidence.

1. adapter code owns provider-specific machine-output mode selection
2. `codex` is expected to validate on a headless `exec` path with possible
   `stderr` progress separation
3. `gemini` is expected to validate with `-p/--prompt` as the headless entry
   and JSON or stream-JSON paths where `stdout` must stay machine-readable
4. `copilot` currently advertises prompt-mode headless execution and JSONL
   output, but the runtime should stay fail-closed until that contract is
   validated live
5. CLI install, local auth, and trust-directory approval remain operator
   preconditions rather than runtime-owned setup steps
