# Config State Snapshot

> AUTO-GENERATED. DO NOT EDIT.

This document is a read-only view of current effective split configuration.
Runtime source of truth:

- `configs/servant/*.yaml`
- `configs/pipeline/*.yaml`

Snapshot files:

- `configs/config-state.yaml`
- `configs/config-state.md`

## Where To Change Settings

| What you want to change                   | Edit this file                                                                          |
| ----------------------------------------- | --------------------------------------------------------------------------------------- |
| Codex provider settings                   | [configs/servant/codex.yaml](servant/codex.yaml)                                        |
| Gemini provider settings                  | [configs/servant/gemini.yaml](servant/gemini.yaml)                                      |
| Copilot provider settings                 | [configs/servant/copilot.yaml](servant/copilot.yaml)                                    |
| Impl pipeline profiles/options            | [configs/pipeline/impl-pipeline.yaml](pipeline/impl-pipeline.yaml)                      |
| Review pipeline profiles/options          | [configs/pipeline/review-pipeline.yaml](pipeline/review-pipeline.yaml)                  |
| Plan pipeline profiles/options            | [configs/pipeline/plan-pipeline.yaml](pipeline/plan-pipeline.yaml)                      |
| Task-level one-off overrides              | `<task>/manifest.yaml` (`routing.model.*`, `routing.pipeline.*`)                        |
| Allowed option enums and validation rules | [scripts/agent-cli/lib/config_validate.py](../scripts/agent-cli/lib/config_validate.py) |

## Configurable Options (Current Allowed Values)

- `codex_effort`: `["high", "low", "medium", "xhigh"]`
- `gemini_approval_mode`: `["auto_edit", "default", "yolo"]`
- `timeout_mode`: `["enforce", "wait_done"]`

### Pipeline Options

- `impl`:
  - `impl_mode`: `["one_shot", "safe"]`
  - `timeout_mode`: `["enforce", "wait_done"]`
- `review`:
  - `review_mode`: `["codex_only", "cross"]`
  - `timeout_mode`: `["enforce", "wait_done"]`
- `plan`:
  - `consolidate_mode`: `["standard"]`
  - `timeout_mode`: `["enforce", "wait_done"]`

### Pipeline Flags

- `impl`: `["enable_brief", "enable_review", "enable_verify"]`
- `review`: `["enable_review", "enable_verify"]`
- `plan`: `["enable_codex_enrich", "enable_cross_review", "enable_gemini_enrich"]`

## Current Provider State

### `codex`

- Edit file: [configs/servant/codex.yaml](servant/codex.yaml)
- `default_model`: `gpt-5.3-codex`
- `wrapper_defaults`: `{"effort": "high", "timeout_ms": 600000, "timeout_mode": "wait_done"}`
- `allowed_models`:
  - `gpt-5.3-codex`
  - `gpt-5.2-codex`
  - `gpt-5-codex`
  - `gpt-5.3-codex-spark`
- `purpose_models`:
  - `impl` -> `gpt-5.3-codex`
  - `review` -> `gpt-5.2-codex`
  - `verify` -> `gpt-5.3-codex`
  - `plan` -> `gpt-5.3-codex`
  - `one_shot` -> `gpt-5.2-codex`
- `purpose_efforts`:
  - `impl` -> `high`
  - `review` -> `medium`
  - `verify` -> `high`
  - `plan` -> `medium`
  - `one_shot` -> `medium`

### `gemini`

- Edit file: [configs/servant/gemini.yaml](servant/gemini.yaml)
- `default_model`: `pro`
- `wrapper_defaults`: `{"approval_mode": "default", "sandbox": false, "timeout_ms": 600000, "timeout_mode": "wait_done"}`
- `allowed_models`:
  - `auto`
  - `pro`
  - `flash`
  - `flash-lite`
  - `gemini-2.5-pro`
  - `gemini-2.5-flash`
  - `gemini-2.5-flash-lite`
  - `gemini-3-pro-preview`
- `purpose_models`:
  - `impl` -> `pro`
  - `review` -> `pro`
  - `verify` -> `flash`
  - `plan` -> `pro`
  - `one_shot` -> `flash`

### `copilot`

- Edit file: [configs/servant/copilot.yaml](servant/copilot.yaml)
- `default_model`: `claude-sonnet-4.6`
- `wrapper_defaults`: `{"timeout_ms": 600000, "timeout_mode": "wait_done"}`
- `allowed_models`:
  - `auto`
  - `claude-haiku-4.5`
  - `claude-sonnet-4.6`
  - `claude-opus-4.6`
  - `claude-sonnet-4.5`
  - `claude-opus-4.5`
  - `gpt-5-codex`
  - `gpt-5.2-codex`
  - `gpt-5.1-codex`
  - `gpt-5.1-codex-mini`
- `purpose_models`:
  - `impl` -> `claude-sonnet-4.6`
  - `review` -> `claude-opus-4.6`
  - `verify` -> `claude-sonnet-4.6`
  - `plan` -> `claude-sonnet-4.6`
  - `one_shot` -> `claude-sonnet-4.6`

## Current Pipeline State

### `impl`

- Edit file: [configs/pipeline/impl-pipeline.yaml](pipeline/impl-pipeline.yaml)
- `default_profile`: `safe_impl`

#### `safe_impl`

- `stages`: `["gemini_brief", "codex_impl", "codex_verify", "gemini_review"]`
- `flags`: `{"enable_brief": true, "enable_verify": true, "enable_review": true}`
- `options`: `{"impl_mode": "safe", "timeout_mode": "wait_done"}`
- `stage_models`:
  - `gemini_brief` -> `pro`
  - `codex_impl` -> `gpt-5.3-codex`
  - `codex_verify` -> `gpt-5.3-codex`
  - `gemini_review` -> `pro`
- `stage_efforts`:
  - `codex_impl` -> `high`
  - `codex_verify` -> `high`

#### `one_shot_impl`

- `stages`: `["gemini_brief", "copilot_runbook", "codex_verify"]`
- `flags`: `{"enable_brief": true, "enable_verify": true, "enable_review": false}`
- `options`: `{"impl_mode": "one_shot", "timeout_mode": "wait_done"}`
- `stage_models`:
  - `gemini_brief` -> `flash`
  - `copilot_runbook` -> `claude-opus-4.6`
  - `codex_verify` -> `gpt-5.3-codex`
- `stage_efforts`:
  - `codex_verify` -> `medium`

#### `design_only`

- `stages`: `["gemini_brief", "gemini_test_design", "gemini_review"]`
- `flags`: `{"enable_brief": true, "enable_verify": false, "enable_review": true}`
- `options`: `{"impl_mode": "safe", "timeout_mode": "wait_done"}`
- `stage_models`:
  - `gemini_brief` -> `pro`
  - `gemini_test_design` -> `pro`
  - `gemini_review` -> `pro`

### `review`

- Edit file: [configs/pipeline/review-pipeline.yaml](pipeline/review-pipeline.yaml)
- `default_profile`: `review_cross`

#### `review_only`

- `stages`: `["gemini_review"]`
- `flags`: `{"enable_verify": false, "enable_review": true}`
- `options`: `{"review_mode": "cross", "timeout_mode": "wait_done"}`
- `stage_models`:
  - `gemini_review` -> `pro`

#### `review_cross`

- `stages`: `["gemini_review", "codex_review", "copilot_review_consolidate"]`
- `flags`: `{"enable_verify": true, "enable_review": true}`
- `options`: `{"review_mode": "cross", "timeout_mode": "wait_done"}`
- `stage_models`:
  - `gemini_review` -> `pro`
  - `codex_review` -> `gpt-5.3-codex`
  - `copilot_review_consolidate` -> `claude-sonnet-4.6`
- `stage_efforts`:
  - `codex_review` -> `high`

#### `post_impl_review`

- `stages`: `["gemini_review", "gemini_test_design", "gemini_static_verify", "codex_review", "codex_test_impl", "codex_verify"]`
- `flags`: `{"enable_verify": true, "enable_review": true}`
- `options`: `{"review_mode": "cross", "timeout_mode": "wait_done"}`
- `stage_models`:
  - `gemini_review` -> `pro`
  - `gemini_test_design` -> `pro`
  - `gemini_static_verify` -> `flash`
  - `codex_review` -> `gpt-5.2-codex`
  - `codex_test_impl` -> `gpt-5.3-codex`
  - `codex_verify` -> `gpt-5.3-codex`
- `stage_efforts`:
  - `codex_review` -> `medium`
  - `codex_test_impl` -> `high`
  - `codex_verify` -> `high`

#### `codex_only`

- `stages`: `["codex_review", "codex_verify"]`
- `flags`: `{"enable_verify": true, "enable_review": true}`
- `options`: `{"review_mode": "codex_only", "timeout_mode": "wait_done"}`
- `stage_models`:
  - `codex_review` -> `gpt-5.2-codex`
  - `codex_verify` -> `gpt-5.3-codex`
- `stage_efforts`:
  - `codex_review` -> `medium`
  - `codex_verify` -> `high`

#### `strict_review`

- `stages`: `["gemini_review", "codex_review", "copilot_review_consolidate"]`
- `flags`: `{"enable_verify": true, "enable_review": true}`
- `options`: `{"review_mode": "cross", "timeout_mode": "wait_done"}`
- `stage_models`:
  - `gemini_review` -> `pro`
  - `codex_review` -> `gpt-5.3-codex`
  - `copilot_review_consolidate` -> `claude-sonnet-4.6`
- `stage_efforts`:
  - `codex_review` -> `high`

### `plan`

- Edit file: [configs/pipeline/plan-pipeline.yaml](pipeline/plan-pipeline.yaml)
- `default_profile`: `standard`

#### `standard`

- `flags`: `{"enable_codex_enrich": true, "enable_gemini_enrich": true, "enable_cross_review": true}`
- `options`: `{"consolidate_mode": "standard", "timeout_mode": "wait_done"}`
- `stage_models`:
  - `copilot_draft` -> `claude-sonnet-4.6`
  - `codex_enrich` -> `gpt-5.3-codex`
  - `gemini_enrich` -> `pro`
  - `codex_cross_review` -> `gpt-5.2-codex`
  - `gemini_cross_review` -> `pro`
  - `copilot_consolidate` -> `claude-sonnet-4.6`
- `stage_efforts`:
  - `codex_enrich` -> `medium`
  - `codex_cross_review` -> `medium`

## Validation Command

```bash
python3 scripts/agent-cli/lib/config_validate.py --config-root configs
python3 scripts/agent-cli/lib/config_validate.py --config-root configs --print-choices
```
