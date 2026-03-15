# Capability Probe Catalog

## Status

1. Capability state model: fixed
2. Initial probe targets: draft but actionable
3. Provider-specific outcomes: live-validation gated

## Purpose

Define which runtime capabilities require explicit probing and how probe results
feed the standalone runtime's safety decisions.

## Capability States

1. `verified`
2. `probed`
3. `declared`
4. `unknown`
5. `unsupported`

## Resolution Order

1. verified facts
2. local probe result
3. official provider declaration
4. explicit operator override
5. unknown

## High-Impact Rule

High-impact capabilities require `verified` evidence or explicit operator
approval before autonomous use.

## Initial Probe Targets

1. `session.resume`
2. `session.continue`
3. `output.json_schema`
4. `output.stream_json`
5. `execution.working_dir_persistence`
6. `execution.permission_mode`
7. `execution.sandbox_mode`
8. `safety.hook_exit_code_behavior`
9. `safety.skill_autoload`
10. `mcp.server_attach`

## Probe Rules

1. Probes must minimize side effects.
2. Probes are capability checks, not substitutes for real task execution.
3. Probe results must record provider, adapter, and environment signature.
