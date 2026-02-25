---
name: impl-pipeline
description: Manual implementation-phase skill for this repository. Activate only when the user explicitly invokes /impl-pipeline (or names impl-pipeline) to run impl dispatch.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
---

# Implementation Pipeline Skill

Run implementation through the canonical dispatcher.

## Activation Policy

1. Activate only when the user explicitly invokes `/impl-pipeline` or explicitly names `impl-pipeline`.
2. Do not auto-activate from inferred coding intent.
3. If called by `agent-collab`, treat it as explicit delegation only when `/agent-collab` was explicitly invoked.

## Execution Permission Header

Allowed script entrypoints for this skill:

1. `./scripts/agent-cli/dispatch_impl.sh`
2. `./scripts/agent-cli/dispatch.sh`
3. `./scripts/agent-cli/plan_to_task_packet.sh`
4. `./scripts/agent-cli/preflight.sh`

Before executing scripts outside this list, require explicit user confirmation.

## Prepare Task Packet

1. Require canonical task root `.tmp/task/<task-name>/`.
2. Bootstrap `impl/manifest.yaml` from `plan/final-plan.md` when missing.
3. Keep scope, acceptance commands, and budgets explicit.

## Execute Impl Phase

```bash
./scripts/agent-cli/dispatch_impl.sh \
  --task-root .tmp/task/<task-name> \
  --task-name <task-name> \
  --goal "<goal>"
```

## Follow Method-based Contract

1. Resolve step plan from `configs-v2/skills/impl.yaml`.
2. Respect resolved tool/model/mode mapping from `config_resolve_v2.py`.
3. Run gates per stage and stop on contract violations.

## Enforce Evidence and Scope Rules

1. Apply web evidence strict policy when a stage enables web mode.
2. Enforce manifest scope allow/deny for generated diffs.
3. Record failure reason codes and triage output when a stage fails.

## Validate Artifacts

1. Require `impl/outputs/_summary.md`.
2. Require stage `done` markers and updated `state/stats.json`.
3. Handoff to review only after verification stage success.
