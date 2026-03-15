from __future__ import annotations

from pathlib import Path

from agentorch_ctx.runtime.providers.base import ProviderAdapter
from agentorch_ctx.runtime.providers.codex import CodexAdapter
from agentorch_ctx.runtime.providers.copilot import CopilotAdapter
from agentorch_ctx.runtime.providers.gemini import GeminiAdapter

_ADAPTERS: dict[str, type[ProviderAdapter]] = {
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
    "copilot": CopilotAdapter,
}


class ProviderNotFoundError(ValueError):
    """Raised when a configured provider has no registered adapter."""


def get_provider_adapter(
    provider: str, *, root_dir: Path, live_mode: bool = False
) -> ProviderAdapter:
    adapter_cls = _ADAPTERS.get(provider)
    if adapter_cls is None:
        raise ProviderNotFoundError(f"unsupported provider adapter: {provider}")
    return adapter_cls(root_dir=root_dir, live_mode=live_mode)


__all__ = [
    "ProviderAdapter",
    "ProviderNotFoundError",
    "get_provider_adapter",
]
