from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.artifact_store import ArtifactStore


@dataclass(frozen=True)
class ArtifactConsistencyResult:
    path: Path
    payload: dict[str, Any]


class ArtifactConsistencyChecker:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.store = ArtifactStore(self.root_dir)

    def check(
        self,
        *,
        task_id: str,
        phase: str,
        step: str,
        filename: str | None = None,
    ) -> ArtifactConsistencyResult:
        task_root = self.store.task_root(task_id)
        from agentorch_ctx.runtime.pathing import task_state_dir

        state_root = task_state_dir(self.root_dir, task_id)
        manifest_envelope = self._load_json(task_root / "manifests" / "manifest.json")
        manifest = manifest_envelope.get("payload", manifest_envelope)
        controller = self._load_json(state_root / "controller-state.json")
        known_information = self._load_json(state_root / "known-information.json")
        approval_state = self._load_optional_json(state_root / "approval-state.json")
        resume_cursor = self._load_optional_json(state_root / "resume-cursor.json")
        session_state = self._load_optional_json(state_root / "session-state.json")

        checked_refs: list[str] = []
        errors: list[str] = []
        self._check_equal(errors, "manifest.taskId", manifest.get("taskId"), task_id)
        self._check_equal(
            errors, "controller.task_id", controller.get("task_id"), task_id
        )
        self._check_equal(
            errors,
            "manifest.activePhase",
            manifest.get("activePhase"),
            controller.get("active_phase"),
        )
        self._check_equal(
            errors,
            "manifest.activeStep",
            manifest.get("activeStep"),
            controller.get("active_step"),
        )
        self._check_equal(
            errors,
            "manifest.activeStrategyId",
            manifest.get("activeStrategyId"),
            controller.get("active_strategy"),
        )

        self._collect_existing_refs(
            checked_refs,
            errors,
            *manifest.get("artifactRefs", {}).values(),
            *manifest.get("lastSuccessfulArtifactRefs", []),
            *manifest.get("latestShellDigestRefs", []),
            *manifest.get("blockerRefs", []),
            known_information.get("latest_phase_summary", {}).get("artifact_ref", ""),
            known_information.get("latest_validation_apply_summary", {}).get(
                "validation_ref", ""
            ),
            known_information.get("latest_validation_apply_summary", {}).get(
                "apply_result_ref", ""
            ),
            resume_cursor.get("artifact_ref", ""),
        )

        manifest_cursor = manifest.get("resumeCursor", {})
        self._check_equal(
            errors,
            "resumeCursor.phase",
            manifest_cursor.get("phase"),
            resume_cursor.get("phase"),
        )
        self._check_equal(
            errors,
            "resumeCursor.strategy",
            manifest_cursor.get("strategy"),
            resume_cursor.get("strategy"),
        )
        self._check_equal(
            errors,
            "resumeCursor.step",
            manifest_cursor.get("step"),
            resume_cursor.get("step"),
        )
        self._check_equal(
            errors,
            "resumeCursor.resumeFrom",
            manifest_cursor.get("resumeFrom", ""),
            resume_cursor.get("resume_from", ""),
        )
        self._check_equal(
            errors,
            "approvalState.status",
            manifest.get("approvalState", {}).get("status"),
            approval_state.get("status"),
        )
        self._check_equal(
            errors,
            "approvalState.marker",
            manifest.get("approvalState", {}).get("marker", ""),
            approval_state.get("marker", ""),
        )
        self._check_equal(
            errors,
            "latestPhaseSummary.artifactRef",
            manifest.get("latestPhaseSummary", {}).get("artifactRef", ""),
            known_information.get("latest_phase_summary", {}).get("artifact_ref", ""),
        )
        self._check_equal(
            errors,
            "latestValidationApplySummary.validationRef",
            manifest.get("latestValidationApplySummary", {}).get("validationRef", ""),
            known_information.get("latest_validation_apply_summary", {}).get(
                "validation_ref", ""
            ),
        )
        self._check_equal(
            errors,
            "latestValidationApplySummary.applyResultRef",
            manifest.get("latestValidationApplySummary", {}).get("applyResultRef", ""),
            known_information.get("latest_validation_apply_summary", {}).get(
                "apply_result_ref", ""
            ),
        )
        if session_state:
            self._check_equal(
                errors,
                "sessionRefs.provider",
                manifest.get("sessionRefs", {}).get("provider"),
                session_state.get("provider"),
            )
            self._check_equal(
                errors,
                "sessionRefs.sessionRef",
                manifest.get("sessionRefs", {}).get("sessionRef"),
                session_state.get("sessionRef"),
            )

        payload = {
            "schemaVersion": "1.0.0",
            "taskId": task_id,
            "phase": phase,
            "step": step,
            "status": "passed" if not errors else "failed",
            "checkedRefs": checked_refs,
            "errors": errors,
            "summary": (
                "artifact references consistent" if not errors else "; ".join(errors)
            ),
        }
        record = self.store.write_json_artifact(
            task_id=task_id,
            family="consistency",
            artifact_type="artifact_consistency",
            payload=payload,
            filename=filename or f"artifact-consistency-{phase}-{step}.json",
            phase=phase,
            step=step,
        )
        return ArtifactConsistencyResult(path=record.path, payload=payload)

    def _collect_existing_refs(
        self, checked_refs: list[str], errors: list[str], *refs: str
    ) -> None:
        for ref in refs:
            if not ref:
                continue
            checked_refs.append(ref)
            if not Path(ref).exists():
                errors.append(f"missing artifact ref: {ref}")

    def _check_equal(
        self, errors: list[str], label: str, actual: Any, expected: Any
    ) -> None:
        if actual != expected:
            errors.append(f"{label} mismatch: {actual!r} != {expected!r}")

    def _load_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_optional_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return self._load_json(path)
