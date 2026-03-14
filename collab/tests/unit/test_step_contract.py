from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from collab.runtime.step_contract import (
    check_input_contract,
    check_output_contract,
    inject_artifact_refs,
)


class StepContractUnitTest(unittest.TestCase):
    def test_check_input_contract_allows_empty_required_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = check_input_contract(
                task_root=Path(tmp),
                step_def={
                    "inputContract": {
                        "requiredArtifacts": [],
                        "optionalArtifacts": [],
                        "onMissingRequired": "stop",
                    }
                },
                prior_step_records=[],
            )

        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_check_input_contract_accepts_existing_family_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_root = Path(tmp)
            plans_dir = task_root / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            (plans_dir / "plan.json").write_text("{}", encoding="utf-8")

            ok, reason = check_input_contract(
                task_root=task_root,
                step_def={
                    "inputContract": {
                        "requiredArtifacts": ["plans/"],
                        "optionalArtifacts": [],
                        "onMissingRequired": "stop",
                    }
                },
                prior_step_records=[],
            )

        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_check_input_contract_rejects_missing_family_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = check_input_contract(
                task_root=Path(tmp),
                step_def={
                    "inputContract": {
                        "requiredArtifacts": ["plans/"],
                        "optionalArtifacts": [],
                        "onMissingRequired": "stop",
                    }
                },
                prior_step_records=[],
            )

        self.assertFalse(ok)
        self.assertIn("missing_required_artifacts", reason)
        self.assertIn("plans/", reason)

    def test_check_input_contract_honors_ignore_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = check_input_contract(
                task_root=Path(tmp),
                step_def={
                    "inputContract": {
                        "requiredArtifacts": ["plans/"],
                        "optionalArtifacts": [],
                        "onMissingRequired": "ignore",
                    }
                },
                prior_step_records=[],
            )

        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_check_input_contract_accepts_prior_step_artifact_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref = "/tmp/response-impl-I0_analyze.json"
            ok, reason = check_input_contract(
                task_root=Path(tmp),
                step_def={
                    "inputContract": {
                        "requiredArtifacts": [ref],
                        "optionalArtifacts": [],
                        "onMissingRequired": "stop",
                    }
                },
                prior_step_records=[{"step": "I0_analyze", "responseRef": ref}],
            )

        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_inject_artifact_refs_adds_prior_step_artifact_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            updated = inject_artifact_refs(
                request={"summary": "task"},
                task_root=Path(tmp),
                step_def={},
                prior_step_records=[
                    {
                        "step": "I0_analyze",
                        "responseRef": "/tmp/r.json",
                        "validationRef": "/tmp/v.json",
                        "applyResultRef": "",
                    }
                ],
            )

        refs = updated.get("operator_context", {}).get("prior_step_artifact_refs", [])
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]["step"], "I0_analyze")
        self.assertEqual(refs[0]["refType"], "responseRef")
        self.assertEqual(refs[0]["ref"], "/tmp/r.json")
        self.assertEqual(refs[1]["refType"], "validationRef")

    def test_inject_artifact_refs_adds_plan_artifact_ref_from_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_root = Path(tmp)
            plans_dir = task_root / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            oldest = plans_dir / "plan-a.json"
            newest = plans_dir / "plan-z.json"
            oldest.write_text("{}", encoding="utf-8")
            newest.write_text("{}", encoding="utf-8")

            updated = inject_artifact_refs(
                request={"summary": "task"},
                task_root=task_root,
                step_def={},
                prior_step_records=[],
            )

        self.assertEqual(
            updated.get("operator_context", {}).get("plan_artifact_ref"),
            str(newest),
        )

    def test_inject_artifact_refs_adds_merge_input_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_root = Path(tmp)
            merge_dir = task_root / "merge-inputs"
            merge_dir.mkdir(parents=True, exist_ok=True)
            (merge_dir / "merge-plan-A.json").write_text("{}", encoding="utf-8")

            updated = inject_artifact_refs(
                request={"summary": "task"},
                task_root=task_root,
                step_def={},
                prior_step_records=[],
            )

        self.assertIn(
            "merge_input_ref",
            updated.get("operator_context", {}),
        )

    def test_check_output_contract_passes_on_empty_produced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = check_output_contract(
                task_root=Path(tmp),
                step_def={
                    "outputContract": {
                        "producedArtifacts": [],
                        "completionSignal": "controller_status:completed",
                    }
                },
                step_record={"controllerStatus": "completed"},
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_check_output_contract_fails_on_missing_produced_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = check_output_contract(
                task_root=Path(tmp),
                step_def={
                    "outputContract": {
                        "producedArtifacts": ["plans/"],
                        "completionSignal": "controller_status:completed",
                    }
                },
                step_record={"controllerStatus": "completed"},
            )
        self.assertFalse(ok)
        self.assertIn("missing_produced_artifacts", reason)

    def test_check_output_contract_detects_completion_signal_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = check_output_contract(
                task_root=Path(tmp),
                step_def={
                    "outputContract": {
                        "producedArtifacts": [],
                        "completionSignal": "controller_status:completed",
                    }
                },
                step_record={"controllerStatus": "blocked"},
            )
        self.assertFalse(ok)
        self.assertIn("completion_signal_mismatch", reason)

    def test_check_output_contract_passes_with_no_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = check_output_contract(
                task_root=Path(tmp),
                step_def={},
                step_record={"controllerStatus": "completed"},
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
