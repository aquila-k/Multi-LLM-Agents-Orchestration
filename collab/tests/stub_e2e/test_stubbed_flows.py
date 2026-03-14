from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collab.runtime.claude_code_skill import ClaudeCodeSkill
from collab.runtime.phase_runner import PhaseRunner

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
FLOW_CASES = [
    {
        "name": "plan",
        "phase": "plan",
        "fixture": "plan-task.md",
        "expected_phases": ["plan"],
        "expected_status": "partial",
        "strategy": "COLLAB_PLAN_FULL",
    },
    {
        "name": "impl",
        "phase": "impl",
        "fixture": "impl-task.md",
        "expected_phases": ["impl"],
        "expected_status": "running",
        "strategy": "COLLAB_IMPL_PATCH_FIRST",
        "target": "src/example.txt",
    },
    {
        "name": "review",
        "phase": "review",
        "fixture": "review-task.md",
        "expected_phases": ["review"],
        "expected_status": "partial",
        "strategy": "COLLAB_REVIEW_PRESET_STANDARD",
    },
    {
        "name": "harden",
        "phase": "harden",
        "fixture": "harden-task.md",
        "expected_phases": ["harden"],
        "expected_status": "partial",
        "strategy": "COLLAB_HARDEN_STANDARD",
    },
    {
        "name": "review_with_harden",
        "phase": "review",
        "fixture": "review-task.md",
        "expected_phases": ["review", "harden"],
        "expected_status": "partial",
        "strategy": "COLLAB_REVIEW_PRESET_STANDARD",
        "phase_options": {"with_harden": True},
    },
]
STRATEGY_CASES = [
    ("plan", "COLLAB_PLAN_QUESTIONS_ONLY", "plan-task.md"),
    ("plan", "COLLAB_PLAN_MINIMAL", "plan-task.md"),
    ("plan", "COLLAB_PLAN_FULL", "plan-task.md"),
    ("plan", "COLLAB_PLAN_THOROUGH", "plan-task.md"),
    ("impl", "COLLAB_IMPL_BATCH_SHOT", "impl-task.md"),
    ("impl", "COLLAB_IMPL_PATCH_FIRST", "impl-task.md"),
    ("impl", "COLLAB_IMPL_SPEC_PATCH", "impl-task.md"),
    ("impl", "COLLAB_IMPL_FILE_BY_FILE", "impl-task.md"),
    ("impl", "COLLAB_IMPL_SHIELD_FIX", "impl-task.md"),
    ("review", "COLLAB_REVIEW_MODE_A", "review-task.md"),
    ("review", "COLLAB_REVIEW_MODE_B", "review-task.md"),
    ("review", "COLLAB_REVIEW_PRESET_LITE", "review-task.md"),
    ("review", "COLLAB_REVIEW_PRESET_STANDARD", "review-task.md"),
    ("review", "COLLAB_REVIEW_PRESET_STRICT", "review-task.md"),
    ("harden", "COLLAB_HARDEN_LITE", "harden-task.md"),
    ("harden", "COLLAB_HARDEN_STANDARD", "harden-task.md"),
    ("harden", "COLLAB_HARDEN_FULL", "harden-task.md"),
]
BUDGET_CONFIRM_STRATEGIES = {
    "COLLAB_PLAN_THOROUGH",
    "COLLAB_IMPL_FILE_BY_FILE",
    "COLLAB_REVIEW_PRESET_STRICT",
    "COLLAB_HARDEN_FULL",
}


class StubbedStandaloneE2ETest(unittest.TestCase):
    def test_supported_phase_flows_execute_in_stub_mode(self) -> None:
        for case in FLOW_CASES:
            with self.subTest(flow=case["name"]):
                root = self._create_workspace()
                source_path = self._copy_fixture(root, case["fixture"])
                target_path = None
                if case.get("target"):
                    target_path = self._prepare_impl_target(root, case["target"])
                dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                    source_path=source_path,
                    workflow_intent=case["phase"],
                    source_kind="markdown",
                    selectors={"strategy": case["strategy"]},
                    targets={"paths": [case["target"]]} if case.get("target") else None,
                    operator_context={"summary": f"stub-e2e {case['name']}"},
                    phase_options=case.get("phase_options"),
                )
                if case["phase"] == "impl":
                    self._seed_plan_artifact(root=root, task_id=dispatch.task_id)

                result = PhaseRunner(root).run(request_path=dispatch.request_path)
                phase_run = self._load_payload(result.phase_run_path)

                self.assertEqual(result.executed_phases, case["expected_phases"])
                self.assertEqual(result.controller_status, case["expected_status"])
                self.assertEqual(
                    phase_run["phaseRecords"][0]["strategy"],
                    case["strategy"],
                )
                self.assertEqual(
                    phase_run["controllerStatus"],
                    case["expected_status"],
                )
                self.assertEqual(
                    phase_run["compositionMode"],
                    "composed" if len(case["expected_phases"]) > 1 else "single",
                )
                self.assertEqual(
                    len(phase_run["consistencyRefs"]),
                    len(case["expected_phases"]),
                )
                for record in phase_run["phaseRecords"]:
                    self.assertTrue(Path(record["requestRef"]).exists())
                    self.assertTrue(Path(record["resolvedConfigRef"]).exists())
                    self.assertTrue(Path(record["routingResultRef"]).exists())
                    self.assertTrue(Path(record["promptBundleRef"]).exists())
                    self.assertTrue(Path(record["responseRef"]).exists())
                    self.assertTrue(Path(record["validationRef"]).exists())
                    self.assertTrue(Path(record["consistencyRef"]).exists())

                if target_path is not None:
                    self.assertIn(
                        "stub:codex:impl:", target_path.read_text(encoding="utf-8")
                    )
                    self.assertTrue(
                        Path(phase_run["phaseRecords"][0]["applyResultRef"]).exists()
                    )

                if case["name"] == "review_with_harden":
                    self.assertTrue(phase_run["withHarden"])
                    self.assertTrue(phase_run["phaseRecords"][1]["strategySwitchRef"])

    def test_stable_strategy_matrix_executes_each_strategy_in_stub_mode(self) -> None:
        for phase, strategy, fixture in STRATEGY_CASES:
            with self.subTest(strategy=strategy):
                root = self._create_workspace()
                source_path = self._copy_fixture(root, fixture)
                targets = None
                target_path = None
                if phase == "impl":
                    targets = {"paths": ["src/matrix-target.txt"]}
                    target_path = self._prepare_impl_target(
                        root, "src/matrix-target.txt"
                    )

                dispatch = ClaudeCodeSkill(root_dir=root).dispatch(
                    source_path=source_path,
                    workflow_intent=phase,
                    source_kind="markdown",
                    selectors={"strategy": strategy},
                    targets=targets,
                    operator_context={"summary": f"stub matrix {strategy}"},
                )
                if phase == "impl":
                    self._seed_plan_artifact(root=root, task_id=dispatch.task_id)

                result = PhaseRunner(root).run(request_path=dispatch.request_path)
                phase_run = self._load_payload(result.phase_run_path)
                first_record = phase_run["phaseRecords"][0]

                self.assertEqual(result.executed_phases, [phase])
                self.assertEqual(first_record["strategy"], strategy)
                self.assertEqual(first_record["phase"], phase)
                self.assertEqual(
                    first_record["controllerStatus"], result.controller_status
                )
                self.assertTrue(Path(first_record["requestRef"]).exists())
                self.assertTrue(Path(first_record["consistencyRef"]).exists())
                expects_budget_preflight = strategy in BUDGET_CONFIRM_STRATEGIES
                if expects_budget_preflight:
                    self.assertEqual(result.controller_status, "blocked")
                    self.assertEqual(
                        first_record["stepRecords"][0]["step"], "preflight"
                    )
                    self.assertEqual(
                        phase_run.get("blockedReason"), "strategy_budget_preflight"
                    )
                else:
                    self.assertTrue(Path(first_record["responseRef"]).exists())

                if phase == "impl":
                    if expects_budget_preflight:
                        self.assertEqual(result.controller_status, "blocked")
                    else:
                        self.assertEqual(result.controller_status, "running")
                    self.assertIsNotNone(target_path)
                    if expects_budget_preflight:
                        self.assertNotIn(
                            "stub:codex:impl:",
                            target_path.read_text(encoding="utf-8"),
                        )
                    else:
                        self.assertIn(
                            "stub:codex:impl:",
                            target_path.read_text(encoding="utf-8"),
                        )
                else:
                    if expects_budget_preflight:
                        self.assertEqual(result.controller_status, "blocked")
                    else:
                        self.assertEqual(result.controller_status, "partial")

    def _create_workspace(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        (root / "AGENTS.md").write_text("# stub workspace\n", encoding="utf-8")
        return root

    def _copy_fixture(self, root: Path, fixture_name: str) -> Path:
        destination = root / fixture_name
        destination.write_text(
            (FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return destination

    def _prepare_impl_target(self, root: Path, relative_path: str) -> Path:
        target_path = root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            (FIXTURE_ROOT / "sample-target.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return target_path

    def _seed_plan_artifact(self, *, root: Path, task_id: str) -> None:
        plan_path = (
            root
            / "collab"
            / "artifacts"
            / "tasks"
            / task_id
            / "plans"
            / "plan-plan-FINAL_plan.json"
        )
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(
                {
                    "summary": "seed plan artifact for impl precondition",
                    "implementationSteps": [],
                    "checklist": [],
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def _load_payload(self, path: Path) -> dict[str, object]:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        return envelope["payload"]


if __name__ == "__main__":
    unittest.main()
