from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentorch_ctx.runtime.budget_gate import BudgetGate
from agentorch_ctx.runtime.capabilities import CapabilityRecord, CapabilityRegistry
from agentorch_ctx.runtime.probes import ProbeStore
from agentorch_ctx.runtime.routing import RoutingEngine


class RoutingUnitTest(unittest.TestCase):
    def test_verified_high_impact_capability_beats_declared_candidate(self) -> None:
        registry = CapabilityRegistry()
        registry.register(
            CapabilityRecord(
                provider="provider-b",
                capability_key="session.resume",
                state="verified",
                source="verified-facts",
                environment_signature={},
            )
        )
        engine = RoutingEngine(registry)
        result = engine.route(
            phase="impl",
            candidates=[
                {
                    "provider": "provider-a",
                    "strategy": "cheap",
                    "capabilities": {"session.resume": "declared"},
                    "scores": {"contextDemand": "high", "applyRisk": "medium"},
                    "estimated_cost": 0.2,
                },
                {
                    "provider": "provider-b",
                    "strategy": "safe",
                    "capabilities": {"session.resume": "verified"},
                    "scores": {"contextDemand": "high", "applyRisk": "medium"},
                    "estimated_cost": 0.5,
                },
            ],
            metrics={"contextDemand": "high", "applyRisk": "medium"},
            required_capabilities=[{"key": "session.resume", "high_impact": True}],
            budget={
                "hardCap": 10,
                "softCap": 5,
                "consumed": 1,
                "estimatedNextCost": 0.5,
            },
        )
        self.assertEqual(result.selected["provider"], "provider-b")
        self.assertEqual(
            result.excluded[0]["reason"], "high_impact_not_verified:session.resume"
        )

    def test_hard_budget_stop_blocks_routing(self) -> None:
        engine = RoutingEngine(CapabilityRegistry())
        result = engine.route(
            phase="plan",
            candidates=[
                {"provider": "provider-a", "scores": {}, "estimated_cost": 1.0}
            ],
            metrics={},
            budget={
                "hardCap": 2,
                "softCap": 1,
                "consumed": 1.9,
                "estimatedNextCost": 0.3,
            },
        )
        self.assertIsNone(result.selected)
        self.assertTrue(result.stop_and_confirm)
        self.assertEqual(result.budget_state, "hard_limit_exceeded")

    def test_probe_record_can_be_promoted_into_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProbeStore(root)
            result = store.record_probe(
                provider="provider-c",
                capability_key="output.json_schema",
                observed_result="supports schema attachment",
                resulting_state="probed",
                environment_signature={"os": "macos"},
            )
            registry = CapabilityRegistry()
            registry.register(store.to_capability_record(result, {"os": "macos"}))
            self.assertEqual(
                registry.resolve("provider-c", "output.json_schema"), "probed"
            )
            self.assertTrue(result.path.exists())


if __name__ == "__main__":
    unittest.main()
