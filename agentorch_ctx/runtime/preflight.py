from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from agentorch_ctx.runtime.config_loader import load_config_bundle
from agentorch_ctx.runtime.pathing import RuntimePaths, augment_path_env


@dataclass(frozen=True)
class ProviderPreflightStatus:
    provider: str
    command: str
    discovered_path: str | None
    available: bool


@dataclass(frozen=True)
class PreflightResult:
    runtime_paths: RuntimePaths
    path_env: dict[str, str]
    providers: list[ProviderPreflightStatus]
    missing_providers: list[str]


def run_preflight(runtime_paths: RuntimePaths) -> PreflightResult:
    path_env = augment_path_env(runtime_paths.repo_root)
    bundle = load_config_bundle(runtime_paths.repo_root)
    providers: list[ProviderPreflightStatus] = []
    for provider_name, provider_config in sorted(bundle.providers.items()):
        command = provider_config["command"]
        discovered = shutil.which(command, path=path_env.get("PATH", os.defpath))
        providers.append(
            ProviderPreflightStatus(
                provider=provider_name,
                command=command,
                discovered_path=discovered,
                available=discovered is not None,
            )
        )
    missing = [provider.provider for provider in providers if not provider.available]
    return PreflightResult(
        runtime_paths=runtime_paths,
        path_env=path_env,
        providers=providers,
        missing_providers=missing,
    )
