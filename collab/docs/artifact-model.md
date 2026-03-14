# Artifact Model

## Status

1. Canonical JSON rule: fixed
2. Artifact family inventory: fixed at the family level
3. Exact field schemas: draft and implementation-facing

## Purpose

Define the artifact families that the standalone `collab/` runtime persists and
clarify which records are canonical versus derived.

## Core Rules

1. Machine-readable runtime artifacts are canonical JSON.
2. Human-readable Markdown is derived from JSON artifacts and is not the source
   of truth.
3. Shell output may point to artifacts, but shell text does not replace stored
   audit records.

## Canonical Artifact Families

The runtime should standardize at least these families:

1. dispatcher request
2. resolved config
3. manifest snapshot
4. routing result
5. option decision
6. strategy switch
7. prompt bundle
8. adapter request
9. adapter result
10. response
11. normalized
12. validation
13. execution record
14. apply result
15. checkpoint
16. shell digest
17. pause confirm
18. phase run
19. artifact consistency checks
20. operator-facing Markdown summaries derived from the JSON records above

## Artifact Lineage

A normal execution path should remain reconstructible from:

```text
request
  -> option-decision / strategy-switch (if needed)
  -> resolved-config
  -> routing-result
  -> prompt-bundle
  -> adapter-request
  -> adapter-result
  -> response
  -> normalized
  -> validation
  -> execution-record
  -> apply-result
  -> manifest / events / decisions / consistency updates
```

## Ownership Rule

`collab/` owns artifact persistence, naming, and linkage. Controllers read
artifact outputs but do not replace them with shell-only summaries or
conversation memory.

## Markdown Derivation Rule

Markdown renderers should:

1. preserve artifact traceability
2. stay concise enough for operator follow-up
3. avoid introducing facts that are not present in the backing JSON
