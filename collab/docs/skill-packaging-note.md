# Skill Packaging Note

## Status

1. Dispatcher entry contract: fixed
2. Exact skill directory naming: still open
3. Phase companion documentation: allowed

## Rule

1. The standalone runtime is invoked through one canonical dispatcher entry:
   `collab/scripts/run`.
2. Phase-specific companion documents may exist, but they do not create
   separate runtime entrypoints.
3. `review` with `with_harden=true` is composed behavior on the dispatcher
   contract, not a separate skill.

## Operator Surface

The intended operator-facing shape is:

1. one dispatcher-oriented entry
2. optional phase-specific companion notes or playbooks
3. concise shell output that points to stored artifacts

## Open Point

The exact skill folder layout for the eventual operator package remains an open
packaging decision and should not block runtime implementation.
