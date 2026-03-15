"""Mutation authority resolution for step execution."""

from __future__ import annotations

from typing import Any

VALID_AUTHORITIES = frozenset(
    {"read_only", "runtime_apply_only", "provider_sandboxed_write"}
)

# Providers that are NEVER allowed provider_sandboxed_write
DIRECT_WRITE_DENIED_PROVIDERS = frozenset(
    {"gemini", "gemini-primary", "review-gemini-primary", "harden-gemini-primary"}
)


def resolve_mutation_authority(
    step_config: dict[str, Any],
    provider: str,
) -> str:
    """
    Resolve the effective mutation authority for a step.

    Rules:
    1. If step_config has no "mutationAuthority" field → "runtime_apply_only" (default)
    2. If authority would be "provider_sandboxed_write" but provider is in DIRECT_WRITE_DENIED_PROVIDERS
       → return "runtime_apply_only" (silently downgrade)
    3. If authority value is not in VALID_AUTHORITIES → "runtime_apply_only" (safe fallback)
    4. Otherwise return the declared authority
    """
    declared = step_config.get("mutationAuthority", "runtime_apply_only")
    if declared not in VALID_AUTHORITIES:
        return "runtime_apply_only"
    if declared == "provider_sandboxed_write":
        provider_lower = provider.lower()
        if provider_lower in DIRECT_WRITE_DENIED_PROVIDERS:
            return "runtime_apply_only"
    return declared


def authority_allows_direct_write(authority: str) -> bool:
    """Returns True if the authority permits provider direct-write to workspace."""
    return authority == "provider_sandboxed_write"


def authority_requires_apply_executor(authority: str) -> bool:
    """Returns True if changes must go through the apply executor (not direct-write)."""
    return authority in {"runtime_apply_only", "read_only"}
