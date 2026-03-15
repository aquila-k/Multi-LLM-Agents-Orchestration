# Skill Validation

## Status

1. Dispatcher contract stability: fixed
2. Validation rules: draft but required
3. Packaging layout: partially open

## Purpose

Define the minimum validation rules for skill or playbook materials that invoke
the standalone agentorch dispatcher.

## Core Rules

1. Skills are playbooks, not the runtime source of truth.
2. Runtime correctness depends on contract conformance, not shell parsing.
3. Invalid skill content must be rejected before execution.

## Mandatory Validation

1. request contract version compatibility
2. response and artifact expectations
3. dispatcher entry shape validation
4. concise shell outcome declaration
5. selector-based resume declaration
6. dynamic-input-only assembly declaration
7. forbidden anti-pattern detection

## Forbidden Anti-Patterns

1. raw freeform argument passing as the primary runtime contract
2. shell parsing as the source of truth
3. verbose terminal output as a required control surface
4. provider-specific volatile facts written as verified truth
