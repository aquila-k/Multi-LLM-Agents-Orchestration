---
name: security-lens-playbook
description: Manual security-lens operations skill for this repository. Activate only when the user explicitly invokes /security-lens-playbook (or names security-lens-playbook) for security lens triage and gate handling.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
---

# Security Lens Playbook

Use this skill to operate the security lens in review runs.

## Activation Policy

1. Activate only when the user explicitly invokes `/security-lens-playbook` or explicitly names `security-lens-playbook`.
2. Do not auto-activate from broad security-related text.
3. If called by `agent-collab` flow, require that root invocation was explicit.

## Execution Permission Header

Allowed script entrypoints for this skill:

1. `./scripts/agent-cli/dispatch_review.sh`
2. `./scripts/agent-cli/post_impl_review.sh`

Before executing scripts outside this list, require explicit user confirmation.

## Choose Lens Mode

1. Use `--security-mode off` to disable lens.
2. Use `--security-mode auto` to enable keyword/manifest based activation.
3. Use `--security-mode always` to force security lens.

## Run Review with Security Lens

```bash
./scripts/agent-cli/dispatch_review.sh \
  --task-root .tmp/task/<task-name> \
  --task-name <task-name> \
  --parallel-review \
  --security-mode always
```

## Verify Security Artifacts

1. Check `review/findings/security.md`.
2. Check `review/review_merged_findings.json` for `lens=security` findings.
3. Check `review/security_gate_result.json` for final severity and stop action.
4. Check `review/security_fix_rounds/` when high-severity fix loop was executed.

## Handle STOP_AND_CONFIRM

1. Stop automated progression.
2. Surface critical findings and impact.
3. Require explicit human sign-off before resuming.

## Respect Responsibility Boundary

Do not treat this skill as the runtime controller.

Runtime-owned responsibilities:

1. Mode resolution precedence
2. Auto-trigger keyword scanning
3. Gate action mapping and fix loop control

These are implemented in:

1. `scripts/agent-cli/dispatch_review.sh`
2. `scripts/agent-cli/lib/review_parallel.sh`
