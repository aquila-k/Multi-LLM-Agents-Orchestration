# Config Schema

## Purpose

Configuration is split by domain and stored under `configs/`:

- Provider config: `configs/servant/*.yaml`
- Pipeline config: `configs/pipeline/*.yaml`

These files are the runtime source of truth used by:

- `scripts/agent-cli/dispatch.sh`
- `scripts/agent-cli/run_plan_pipeline.sh`

Human-facing read-only snapshots are auto-generated at:

- `configs/config-state.yaml`
- `configs/config-state.md`

Validation is fail-closed: unknown keys, invalid enums, and invalid model names stop execution before paid calls.

## Precedence

1. Split config files under `configs/servant` and `configs/pipeline`
2. Task-level `manifest.yaml` overrides (`routing.model.*`, `routing.pipeline.*`)

## Required Files

- `configs/servant/codex.yaml`
- `configs/servant/gemini.yaml`
- `configs/servant/copilot.yaml`
- `configs/pipeline/impl-pipeline.yaml`
- `configs/pipeline/review-pipeline.yaml`
- `configs/pipeline/plan-pipeline.yaml`

## Read-only Snapshot Files

- `configs/config-state.yaml`: machine-readable snapshot for quick inspection
- `configs/config-state.md`: human-friendly snapshot with edit-map and allowed options

These are generated automatically by config load/validate flows and should not be edited manually.
Manual refresh command:

```bash
python3 scripts/agent-cli/lib/config_snapshot.py --config-root configs
```

## Servant File Schema (`configs/servant/*.yaml`)

```yaml
version: 1
tool: codex|gemini|copilot

default_model: <string>
allowed_models: [<string>, ...]

wrapper_defaults: {}
purpose_models:
  impl: <string>
  review: <string>
  verify: <string>
  plan: <string>
  one_shot: <string>
purpose_efforts: # codex only
  impl: low|medium|high|xhigh
  review: low|medium|high|xhigh
  verify: low|medium|high|xhigh
  plan: low|medium|high|xhigh
  one_shot: low|medium|high|xhigh
```

Rules:

- `default_model` must be in `allowed_models`
- `purpose_models.*` must be in `allowed_models`
- `purpose_efforts` is supported only for codex
- `wrapper_defaults` must contain all allowed keys for that tool
- Unknown keys are rejected
- `wrapper_defaults` allowed keys:
  - codex: `effort`, `timeout_ms`, `timeout_mode`
  - gemini: `approval_mode`, `sandbox`, `timeout_ms`, `timeout_mode`
  - copilot: `timeout_ms`, `timeout_mode`
  - `timeout_mode`: `enforce | wait_done`
  - `timeout_ms`: non-negative integer (`0` means no hard timeout)

## Pipeline File Schema (`configs/pipeline/*.yaml`)

```yaml
version: 1
pipeline: impl|review|plan

default_profile: <name>
profiles:
  <name>:
    stages: [<tool_role>, ...] # required for impl/review
    flags: {}
    options: {}
    stage_models: {}
    stage_efforts: {} # codex stages only (optional)
```

### `impl` options

- `impl_mode`: `safe | one_shot`
- `timeout_mode`: `enforce | wait_done`

### `review` options

- `review_mode`: `codex_only | cross`
- `timeout_mode`: `enforce | wait_done`

### `plan` options

- `consolidate_mode`: `standard`
- `timeout_mode`: `enforce | wait_done`

Rules:

- `default_profile` must exist in `profiles`
- `stage_models.<stage>` model must be valid for that stage tool
- `stage_efforts.<stage>` is only for codex stages and must be `low|medium|high|xhigh`
- Unknown keys are rejected

## Model Resolution Priority

### Dispatch (`impl/review`)

For each stage:

1. `manifest.yaml` `routing.model.<tool>` (task-level override)
2. `profiles.<profile>.stage_models.<stage>`
3. `servants.<tool>.purpose_models.<purpose>`
4. `servants.<tool>.default_model`

This enables purpose-based tuning (e.g. `codex.review` with a lighter model) and one-shot tuning (`purpose_models.one_shot`).

### Codex Effort Resolution

For codex stages:

1. `profiles.<profile>.stage_efforts.<stage>`
2. `servants.codex.purpose_efforts.<purpose>`
3. `servants.codex.wrapper_defaults.effort`

### Timeout Resolution

For each stage:

1. Pipeline `options.timeout_mode` (if set)
2. `servants.<tool>.wrapper_defaults.timeout_mode`

Timeout duration (`timeout_ms`) is taken from `servants.<tool>.wrapper_defaults.timeout_ms`.
For dispatch, `manifest.yaml` `budgets.max_wallclock_sec` still overrides timeout duration.
`timeout_ms: 0` or `timeout_mode: wait_done` means wait for completion without hard kill.
Default behavior is `wait_done` when no override is set.

### Plan pipeline

For each plan stage (`stage1..stage4`):

1. CLI override `--copilot-model|--gemini-model|--codex-model`
2. `pipelines.plan.profiles.<profile>.stage_models.<stage>`
3. `servants.<tool>.purpose_models.<purpose>`
4. `servants.<tool>.default_model`

## Manifest Extensions (Optional)

```yaml
routing:
  intent: safe_impl
  model:
    codex: gpt-5.2-codex
  pipeline:
    profile: one_shot_impl
    flags:
      enable_review: false
    options:
      impl_mode: one_shot
      timeout_mode: wait_done
```

Rules:

- `routing.model.<tool>` must be in `allowed_models`
- `routing.pipeline.flags.*` must be boolean
- `routing.pipeline.options.*` must satisfy enum constraints

## Validation Commands

```bash
python3 scripts/agent-cli/lib/config_validate.py --config-root configs
python3 scripts/agent-cli/lib/config_validate.py --config-root configs --manifest .tmp/task/<task-id>/manifest.yaml
python3 scripts/agent-cli/lib/config_validate.py --config-root configs --print-choices
```

`--print-choices` prints the current allowed options (including `codex_effort: low|medium|high|xhigh`,
pipeline option enums, and per-provider `allowed_models`) as JSON.

## When CLI Specs Change

When provider CLIs add/remove models or options, reflect updates here:

1. Provider model names and defaults:
   - `configs/servant/codex.yaml`
   - `configs/servant/gemini.yaml`
   - `configs/servant/copilot.yaml`
2. Pipeline profiles/stage mapping and per-stage overrides:
   - `configs/pipeline/impl-pipeline.yaml`
   - `configs/pipeline/review-pipeline.yaml`
   - `configs/pipeline/plan-pipeline.yaml`
3. Allowed option enums and strict validation rules:
   - `scripts/agent-cli/lib/config_validate.py` (`PIPELINE_OPTIONS`, `WRAPPER_DEFAULT_KEYS`, `CODEX_EFFORT_VALUES`, `GEMINI_APPROVAL_VALUES`, `TIMEOUT_MODE_VALUES`)
4. Resolution behavior (priority and fail-closed checks):
   - `scripts/agent-cli/lib/config_resolve.py`
5. Wrapper option compatibility:
   - `scripts/agent-cli/wrappers/run_codex.sh`
   - `scripts/agent-cli/wrappers/gemini_headless.sh`
   - `scripts/agent-cli/wrappers/copilot_tool.sh`

## Resolution Commands

```bash
python3 scripts/agent-cli/lib/config_resolve.py dispatch --config-root configs --manifest .tmp/task/<task-id>/manifest.yaml
python3 scripts/agent-cli/lib/config_resolve.py plan --config-root configs
```
