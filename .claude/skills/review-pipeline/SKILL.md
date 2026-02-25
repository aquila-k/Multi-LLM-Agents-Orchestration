---
name: review-pipeline
description: Manual review-phase skill for this repository. Activate only when the user explicitly invokes /review-pipeline (or names review-pipeline) to run review dispatch and lens flow.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
---

# Review Pipeline Skill

Run review with canonical parallel contracts and strict evidence handling.

## Activation Policy

1. Activate only when the user explicitly invokes `/review-pipeline` or explicitly names `review-pipeline`.
2. Do not auto-activate from generic review requests alone.
3. If called by `agent-collab`, treat it as explicit delegation only when `/agent-collab` was explicitly invoked.

## Execution Permission Header

Allowed script entrypoints for this skill:

1. `./scripts/agent-cli/dispatch_review.sh`
2. `./scripts/agent-cli/post_impl_review.sh`
3. `./scripts/agent-cli/dispatch.sh`
4. `./scripts/agent-cli/preflight.sh`

Before executing scripts outside this list, require explicit user confirmation.

## Execute Review Phase

```bash
./scripts/agent-cli/dispatch_review.sh \
  --task-root .tmp/task/<task-name> \
  --task-name <task-name> \
  --parallel-review
```

## Enforce Parallel Review Contract

1. Run workers as analysis-only lenses.
2. Enforce join barrier before merge/apply.
3. Generate `review_merged_findings.json`, `review_fix_queue.json`, and merge logs.
4. Apply fix queue sequentially only.

## Use Security Lens as Runtime Feature

1. Treat security as a review lens, not a standalone config profile.
2. Control with `--security-mode off|auto|always`.
3. Keep security prompt canonical at `prompts-src/security/security_review.md`.
4. Evaluate gate result from `review/security_gate_result.json`.

## Enforce Evidence Contract

1. Require evidence linkage when findings use external evidence.
2. Stop on strict evidence violations by policy.
3. Preserve reason codes in routing/review artifacts.

## Handle Stop Conditions

1. Stop immediately on `STOP_AND_CONFIRM`.
2. Request human confirmation for critical risks.
3. Resume only after explicit approval and updated artifacts.
