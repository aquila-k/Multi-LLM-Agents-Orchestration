---
name: plan-ping-pong
description: Manual plan-phase skill for this repository. Activate only when the user explicitly invokes /plan-ping-pong (or names plan-ping-pong) to run plan artifacts generation.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
---

# Plan Pipeline Skill

Execute planning with V2 config contracts.

## Activation Policy

1. Activate only when the user explicitly invokes `/plan-ping-pong` or explicitly names `plan-ping-pong`.
2. Do not auto-activate from semantic matching.
3. If called by `agent-collab`, treat it as explicit delegation only when `/agent-collab` was explicitly invoked.

## Execution Permission Header

Allowed script entrypoints for this skill:

1. `./scripts/agent-cli/dispatch_plan.sh`
2. `./scripts/agent-cli/run_plan_pipeline.sh`
3. `./scripts/agent-cli/preflight.sh`

Before executing scripts outside this list, require explicit user confirmation.

## Prepare Inputs

1. Require `.tmp/task/<task-name>/plan/preflight.md`.
2. Ensure goal, scope, constraints, acceptance, and risks are explicit.
3. Keep preflight specific enough for deterministic routing.

## Execute Plan Phase

```bash
./scripts/agent-cli/dispatch_plan.sh \
  --task-root .tmp/task/<task-name> \
  --task-name <task-name> \
  --preflight .tmp/task/<task-name>/plan/preflight.md
```

## Follow Method-based Contract

1. Resolve behavior from `configs-v2/skills/plan.yaml`.
2. Treat `default_method_ids` and `methods.*.steps` as source of truth.
3. Keep routing output aligned to V2 schema (`selected_method_ids`, alternatives, signals, reason codes).

## Enforce Prompt Contract

1. Use template resolution order: task override -> profile override -> default -> legacy fallback.
2. Track `prompt_template_path` and `prompt_sha256` in stage metadata.

## Validate Artifacts

1. Require `plan/final-plan.md`.
2. Keep compatibility alias `plan/final.md`.
3. Verify routing decision and summary artifacts exist before handoff to impl.
