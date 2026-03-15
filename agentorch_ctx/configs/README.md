# Agentorch Configs

## Purpose

`agentorch_ctx/configs/` stores the standalone runtime's versioned configuration for
providers, agents, strategies, phases, and policies.

## Merge Order

The runtime resolves config in this order:

1. provider defaults
2. agent defaults
3. phase default
4. strategy default
5. step override
6. user provider defaults (fill only)

## Rule

1. Config files describe stable runtime defaults and selection policy.
2. Volatile provider and market facts belong in `agentorch_ctx/facts/`, not here.
3. Stable strategy IDs remain `COLLAB_*` even when human-friendly slugs exist.
