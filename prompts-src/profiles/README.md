# Profile Override Templates

This directory is active and used by runtime prompt resolution.

## Resolution Order

1. Task override: `.tmp/task/<task-name>/prompts/<phase>/<tool>/<role>.md`
2. Profile override: `prompts-src/profiles/<phase>/<profile>/<tool>/<role>.md`
3. Default: `prompts-src/<tool>/<role>.md` (plan `shared/*` uses `prompts-src/plan/<role>.md`)
4. Legacy fallback: phase-specific legacy prompts (plan pipeline only)

## Runtime Coverage

Implemented profile override sets:

1. `plan/standard/*`
2. `impl/safe_impl/*`
3. `impl/one_shot_impl/*`
4. `impl/design_only/*`
5. `review/review_only/*`
6. `review/review_cross/*`
7. `review/post_impl_review/*`
8. `review/codex_only/*`
9. `review/strict_review/*`

## Plan Pipeline Mapping

Plan pipeline uses these role mappings:

1. `copilot/draft` -> stage1 draft prompt
2. `shared/enrich` -> stage2 enrich prompt
3. `shared/cross_review` -> stage3 cross-review prompt
4. `copilot/consolidate` -> stage4 consolidate prompt

## Validation

Run this audit to ensure configured profiles have matching override templates:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/agent-cli/lib/prompt_profiles_audit.py --config-root configs-v2 --prompts-root prompts-src
```
