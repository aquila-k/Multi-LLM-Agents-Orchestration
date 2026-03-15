# Agentorch Facts

## Purpose

`agentorch_ctx/facts/` stores volatile runtime facts that must remain separate from
versioned design and policy documents.

## Fact Families

1. `verified-facts/`
2. `probe-results/`
3. `provider-market-facts/`
4. `environment-signature.json`
5. `validation-debt.json`

## Rule

1. Imported verified facts and unresolved validation debt must remain visibly
   separate.
2. Current pricing, model availability, and CLI behavior must not be frozen
   into runtime docs as stable design facts.
