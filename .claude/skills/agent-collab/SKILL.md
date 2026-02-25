---
name: agent-collab
description: Manual-entry orchestration skill for this repository. Activate only when the user explicitly invokes /agent-collab (or names agent-collab), then route to plan/impl/review execution.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
---

# Agent Collab Router

Use this skill as the explicit entrypoint router.

## Activation Policy

1. Activate only when the user explicitly invokes `/agent-collab` or explicitly names `agent-collab`.
2. Do not auto-activate from inferred intent alone.
3. Delegation to phase skills is allowed only after explicit `agent-collab` activation.

## Execution Permission Header

Allowed script entrypoints for this skill:

1. `./scripts/agent-cli/run_agent_collab.sh`
2. `./scripts/agent-cli/dispatch_plan.sh`
3. `./scripts/agent-cli/dispatch_impl.sh`
4. `./scripts/agent-cli/dispatch_review.sh`

Before executing scripts outside this list, require explicit user confirmation.

## Route Intent

1. Infer one mode: `plan`, `impl`, `review`, or `all`.
2. Prioritize explicit user wording over defaults.
3. Ask one short clarification question only when intent remains ambiguous.
4. Route to the phase skill and execute its command path.

## Delegate by Mode

1. `plan` -> `.claude/skills/plan-ping-pong/SKILL.md`
2. `impl` -> `.claude/skills/impl-pipeline/SKILL.md`
3. `review` -> `.claude/skills/review-pipeline/SKILL.md`
4. `all` -> run `plan -> impl -> review` in sequence with `run_agent_collab.sh`

## Enforce V2 Contracts

1. Use canonical task root `.tmp/task/<task-name>/`.
2. Keep method-based execution aligned with `configs-v2/skills/*.yaml`.
3. Preserve review contracts: finding-first, join barrier, sequential fix queue.
4. Preserve web evidence strict behavior when web mode is enabled.

## Run Commands

Use these commands as canonical entrypoints:

```bash
./scripts/agent-cli/run_agent_collab.sh --mode plan --task-name <task-name> --preflight <file>
./scripts/agent-cli/run_agent_collab.sh --mode impl --task-name <task-name> --goal "<goal>"
./scripts/agent-cli/run_agent_collab.sh --mode review --task-name <task-name>
./scripts/agent-cli/run_agent_collab.sh --mode all --task-name <task-name> --preflight <file> --goal "<goal>"
```

## Validate Outputs

1. Confirm phase summary artifact exists after each mode.
2. Confirm `state/` metadata is updated.
3. Stop on `STOP_AND_CONFIRM` and request human confirmation.
