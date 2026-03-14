from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CAPABILITY_STATES = {"verified", "probed", "declared", "unknown", "unsupported"}
RESOLUTION_PRIORITY = {
    "verified": 5,
    "probed": 4,
    "declared": 3,
    "unknown": 2,
    "unsupported": 1,
}


@dataclass(frozen=True)
class CapabilityRecord:
    provider: str
    capability_key: str
    state: str
    source: str
    environment_signature: dict[str, Any]
    last_verified_at: str | None = None


class CapabilityRegistry:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], CapabilityRecord] = {}

    def register(self, record: CapabilityRecord) -> None:
        if record.state not in CAPABILITY_STATES:
            raise ValueError(f"unknown capability state: {record.state}")
        self._records[(record.provider, record.capability_key)] = record

    def resolve(
        self, provider: str, capability_key: str, default_state: str = "unknown"
    ) -> str:
        record = self._records.get((provider, capability_key))
        return record.state if record else default_state

    def merge_declared(self, provider: str, capabilities: dict[str, str]) -> None:
        for capability_key, state in capabilities.items():
            if (provider, capability_key) in self._records:
                continue
            self.register(
                CapabilityRecord(
                    provider=provider,
                    capability_key=capability_key,
                    state=state,
                    source="declared",
                    environment_signature={},
                )
            )
