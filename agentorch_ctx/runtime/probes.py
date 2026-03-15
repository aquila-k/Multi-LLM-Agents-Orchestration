from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.capabilities import CapabilityRecord


@dataclass(frozen=True)
class ProbeResult:
    capability_key: str
    provider: str
    resulting_state: str
    path: Path


class ProbeStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()

    def record_probe(
        self,
        *,
        provider: str,
        capability_key: str,
        observed_result: str,
        resulting_state: str,
        environment_signature: dict[str, Any],
        risk_class: str = "high-impact",
    ) -> ProbeResult:
        from agentorch_ctx.runtime.pathing import artifacts_root

        directory = artifacts_root(self.root_dir) / "probe-results"
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = _isoformat(datetime.now(timezone.utc)).replace(":", "-")
        path = (
            directory
            / f"{provider}-{capability_key.replace('.', '-')}-{timestamp}.json"
        )
        payload = {
            "provider": provider,
            "capability_key": capability_key,
            "risk_class": risk_class,
            "observed_result": observed_result,
            "resulting_state": resulting_state,
            "environment_signature": environment_signature,
            "last_verified_at": _isoformat(datetime.now(timezone.utc)),
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        return ProbeResult(
            capability_key=capability_key,
            provider=provider,
            resulting_state=resulting_state,
            path=path,
        )

    def to_capability_record(
        self, result: ProbeResult, environment_signature: dict[str, Any]
    ) -> CapabilityRecord:
        return CapabilityRecord(
            provider=result.provider,
            capability_key=result.capability_key,
            state=result.resulting_state,
            source="probe",
            environment_signature=environment_signature,
            last_verified_at=_isoformat(datetime.now(timezone.utc)),
        )


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
