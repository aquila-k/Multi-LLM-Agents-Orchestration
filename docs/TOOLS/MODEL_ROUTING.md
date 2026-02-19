# Model Routing Policy

## Source of Truth

Routing and model selection are read from split config files:

- `configs/servant/*.yaml`
- `configs/pipeline/*.yaml`

Read-only snapshots (for humans) are auto-generated:

- `configs/config-state.yaml`
- `configs/config-state.md`

Resolution order:

1. Split config files
2. Task-level `manifest.yaml` overrides

## Tool Characteristics

| Tool    | Best For                                                   | Avoid For                                   |
| ------- | ---------------------------------------------------------- | ------------------------------------------- |
| Gemini  | Research, design review, broad analysis, test design       | Large diffs                                 |
| Codex   | Multi-file implementation, verification loops, test fixing | Narrow one-shot prose-only tasks            |
| Copilot | One-shot/runbook synthesis and concise rewrites            | Very large prompts (argument size pressure) |

## Provider-level Purpose Models

Each provider can tune models by purpose in `configs/servant/<tool>.yaml`:

- `impl`
- `review`
- `verify`
- `plan`
- `one_shot`

This allows flexible selection such as:

- heavier model for `impl`
- cheaper model for `review`
- dedicated model for `one_shot`

## Pipeline-level Stage Models

Each pipeline profile can override exact stage models in:

- `configs/pipeline/impl-pipeline.yaml`
- `configs/pipeline/review-pipeline.yaml`
- `configs/pipeline/plan-pipeline.yaml`

Stage-level override has highest priority and is ideal when a specific step must use a specific model.

## Effective Model Selection

For each stage:

1. Runtime override (`manifest routing.model.<tool>` for dispatch, CLI `--*-model` for plan)
2. `stage_models.<stage>`
3. provider `purpose_models.<purpose>`
4. provider `default_model`

## Codex Reasoning Effort

Codex reasoning effort can be tuned by purpose:

1. pipeline `stage_efforts.<stage>` (codex stages only)
2. `configs/servant/codex.yaml` `purpose_efforts.<purpose>`
3. `configs/servant/codex.yaml` `wrapper_defaults.effort`

This allows lighter effort for review/plan while keeping higher effort for impl/verify.

## Timeout and Wait Policy

Timeout behavior is configurable per provider and per pipeline:

- Provider baseline: `wrapper_defaults.timeout_ms`, `wrapper_defaults.timeout_mode`
- Pipeline override: `profiles.<name>.options.timeout_mode`

Modes:

- `enforce`: hard timeout
- `wait_done`: keep waiting until done-marker/process completion (no forced kill)

`timeout_ms: 0` is treated as no hard timeout.
Default behavior is `wait_done`.

## One-shot Implementation

For `impl_mode: one_shot`, model selection can be tuned in two ways:

1. `configs/pipeline/impl-pipeline.yaml` `profiles.one_shot_impl.stage_models.*`
2. `configs/servant/<tool>.yaml` `purpose_models.one_shot`

This makes one-shot execution model choice explicit and configurable.

## Cost Controls

- `manifest.yaml` `paid_call_budget` limits paid API calls
- Each wrapper invocation increments usage (even on failure)
- `retry_budget` limits retries per error signature

## Maintenance Mapping

When CLI specs change (new model IDs, option names):

- Update provider model lists in `configs/servant/*.yaml`
- Update pipeline-stage overrides in `configs/pipeline/*.yaml`
- Update enum/validation constants in `scripts/agent-cli/lib/config_validate.py`
- Re-run `python3 scripts/agent-cli/lib/config_validate.py --config-root configs --print-choices`
