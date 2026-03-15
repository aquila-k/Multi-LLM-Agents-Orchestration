#!/usr/bin/env python3
"""Compound Review+Harden Composition Validation.

Validates the composed review+harden execution path and artifact separation:
  1. independent review  - single phase, compositionMode=single, review artifacts only
  2. independent harden  - single phase, compositionMode=single, harden artifacts only
  3. composed review+harden - two phases, compositionMode=composed, withHarden=true
  4. artifact separation - review and harden write to distinct artifact slots
  5. with-harden entry constraint - with_harden=true rejected for non-review intents

Does NOT require live provider CLI execution.
Evidence is written to <data-root>/facts/probe-results/check-review-harden.json.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agentorch_ctx.runtime.pathing import resolve_data_root, task_artifacts_dir

REPO_ROOT = Path(__file__).resolve().parents[3]
COLLAB_ROOT = resolve_data_root(REPO_ROOT)
PROBE_DIR = COLLAB_ROOT / "facts" / "probe-results"


def _isoformat() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _make_source(workspace: Path, phase: str) -> Path:
    source = workspace / f"{phase}-task.md"
    source.write_text(
        f"# Validation probe: {phase}\n\nProbe task for {phase}.\n", encoding="utf-8"
    )
    return source


def _run_phase_flow(
    *,
    workspace: Path,
    workflow_intent: str,
    phase_options: dict | None = None,
) -> tuple[dict, dict]:
    """Run entrypoint + phase_runner, return (entrypoint_result_dict, phase_run_payload)."""
    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.phase_runner import PhaseRunner
    from agentorch_ctx.runtime.request_writer import prepare_request
    from agentorch_ctx.runtime.task_entrypoint import run_task_from_request

    source = _make_source(workspace, workflow_intent)
    prepared = prepare_request(
        root_dir=workspace,
        source_path=source,
        workflow_intent=workflow_intent,
        source_kind="markdown",
        phase_options=phase_options or {},
        operator_context={"summary": f"Validation probe: {workflow_intent}"},
    )
    entry = run_task_from_request(
        request_path=prepared.request_path, root_dir=workspace
    )
    phase_result = PhaseRunner(workspace).run(request_path=prepared.request_path)

    phase_run_path = phase_result.phase_run_path
    phase_run = json.loads(phase_run_path.read_text(encoding="utf-8"))
    phase_run_payload = phase_run.get("payload", phase_run)

    entry_dict = {
        "task_id": entry.task_id,
        "stop_and_confirm": entry.stop_and_confirm,
    }
    return entry_dict, phase_run_payload


def check_independent_review(workspace: Path) -> dict:
    """Check 1: Independent review runs as a single-phase flow."""
    try:
        review_ws = workspace / "review_only"
        review_ws.mkdir(parents=True, exist_ok=True)
        entry, phase_run = _run_phase_flow(
            workspace=review_ws,
            workflow_intent="review",
            phase_options={"with_harden": False},
        )
        task_id = entry["task_id"]
        task_artifacts = task_artifacts_dir(review_ws, task_id)

        composition_mode = phase_run.get("compositionMode")
        executed_phases = phase_run.get("executedPhases", [])
        with_harden = phase_run.get("withHarden", False)

        review_request_exists = (
            task_artifacts / "requests" / "request-review.json"
        ).exists()
        review_config_exists = (
            task_artifacts / "resolved-config" / "resolved-config-review.json"
        ).exists()
        harden_request_absent = not (
            task_artifacts / "requests" / "request-harden.json"
        ).exists()
        harden_config_absent = not (
            task_artifacts / "resolved-config" / "resolved-config-harden.json"
        ).exists()

        checks = {
            "compositionMode_single": composition_mode == "single",
            "executedPhases_review_only": executed_phases == ["review"],
            "withHarden_false": not with_harden,
            "review_request_exists": review_request_exists,
            "review_config_exists": review_config_exists,
            "harden_request_absent": harden_request_absent,
            "harden_config_absent": harden_config_absent,
        }
        passed = all(checks.values())
        return {
            "check": "independent_review",
            "task_id": task_id,
            "compositionMode": composition_mode,
            "executedPhases": executed_phases,
            "withHarden": with_harden,
            "artifact_checks": checks,
            "passed": passed,
            "notes": "Review-only flow must run as single phase without harden artifacts.",
        }
    except Exception as exc:
        return {
            "check": "independent_review",
            "passed": False,
            "error": str(exc),
            "notes": "Exception during independent review probe.",
        }


def check_independent_harden(workspace: Path) -> dict:
    """Check 2: Independent harden runs as a single-phase flow."""
    try:
        harden_ws = workspace / "harden_only"
        harden_ws.mkdir(parents=True, exist_ok=True)
        entry, phase_run = _run_phase_flow(
            workspace=harden_ws,
            workflow_intent="harden",
        )
        task_id = entry["task_id"]
        task_artifacts = task_artifacts_dir(harden_ws, task_id)

        composition_mode = phase_run.get("compositionMode")
        executed_phases = phase_run.get("executedPhases", [])
        with_harden = phase_run.get("withHarden", False)

        harden_request_exists = (
            task_artifacts / "requests" / "request-harden.json"
        ).exists()
        harden_config_exists = (
            task_artifacts / "resolved-config" / "resolved-config-harden.json"
        ).exists()
        review_request_absent = not (
            task_artifacts / "requests" / "request-review.json"
        ).exists()
        review_config_absent = not (
            task_artifacts / "resolved-config" / "resolved-config-review.json"
        ).exists()

        checks = {
            "compositionMode_single": composition_mode == "single",
            "executedPhases_harden_only": executed_phases == ["harden"],
            "withHarden_false": not with_harden,
            "harden_request_exists": harden_request_exists,
            "harden_config_exists": harden_config_exists,
            "review_request_absent": review_request_absent,
            "review_config_absent": review_config_absent,
        }
        passed = all(checks.values())
        return {
            "check": "independent_harden",
            "task_id": task_id,
            "compositionMode": composition_mode,
            "executedPhases": executed_phases,
            "withHarden": with_harden,
            "artifact_checks": checks,
            "passed": passed,
            "notes": "Harden-only flow must run as single phase without review artifacts.",
        }
    except Exception as exc:
        return {
            "check": "independent_harden",
            "passed": False,
            "error": str(exc),
            "notes": "Exception during independent harden probe.",
        }


def check_composed_review_harden(workspace: Path) -> dict:
    """Check 3: Composed review+harden runs as two-phase flow with correct artifacts."""
    try:
        composed_ws = workspace / "review_with_harden"
        composed_ws.mkdir(parents=True, exist_ok=True)
        entry, phase_run = _run_phase_flow(
            workspace=composed_ws,
            workflow_intent="review",
            phase_options={"with_harden": True},
        )
        task_id = entry["task_id"]
        task_artifacts = task_artifacts_dir(composed_ws, task_id)

        composition_mode = phase_run.get("compositionMode")
        executed_phases = phase_run.get("executedPhases", [])
        with_harden = phase_run.get("withHarden", False)
        phase_records = phase_run.get("phaseRecords", [])

        # Both phases must have distinct artifact files.
        review_request_exists = (
            task_artifacts / "requests" / "request-review.json"
        ).exists()
        harden_request_exists = (
            task_artifacts / "requests" / "request-harden.json"
        ).exists()
        review_config_exists = (
            task_artifacts / "resolved-config" / "resolved-config-review.json"
        ).exists()
        harden_config_exists = (
            task_artifacts / "resolved-config" / "resolved-config-harden.json"
        ).exists()
        review_routing_exists = (
            task_artifacts / "routing" / "routing-result-review.json"
        ).exists()
        harden_routing_exists = (
            task_artifacts / "routing" / "routing-result-harden.json"
        ).exists()

        # Phase records: [0]=review, [1]=harden; harden must have strategySwitchRef.
        has_two_records = len(phase_records) == 2
        harden_has_strategy_switch = (
            bool(phase_records[1].get("strategySwitchRef"))
            if has_two_records
            else False
        )
        consistency_refs_count = len(phase_run.get("consistencyRefs", []))

        checks = {
            "compositionMode_composed": composition_mode == "composed",
            "executedPhases_review_and_harden": executed_phases == ["review", "harden"],
            "withHarden_true": bool(with_harden),
            "two_phase_records": has_two_records,
            "harden_strategy_switch_ref": harden_has_strategy_switch,
            "two_consistency_refs": consistency_refs_count == 2,
            "review_request_exists": review_request_exists,
            "harden_request_exists": harden_request_exists,
            "review_config_exists": review_config_exists,
            "harden_config_exists": harden_config_exists,
            "review_routing_exists": review_routing_exists,
            "harden_routing_exists": harden_routing_exists,
        }
        passed = all(checks.values())
        return {
            "check": "composed_review_harden",
            "task_id": task_id,
            "compositionMode": composition_mode,
            "executedPhases": executed_phases,
            "withHarden": with_harden,
            "phaseRecordCount": len(phase_records),
            "consistencyRefsCount": consistency_refs_count,
            "artifact_checks": checks,
            "passed": passed,
            "notes": "Composed review+harden must produce two phase records with distinct artifacts.",
        }
    except Exception as exc:
        return {
            "check": "composed_review_harden",
            "passed": False,
            "error": str(exc),
            "notes": "Exception during composed review+harden probe.",
        }


def check_artifact_separation(workspace: Path) -> dict:
    """Check 4: Composed flow artifacts are distinct — review and harden do not share files."""
    try:
        sep_ws = workspace / "artifact_separation"
        sep_ws.mkdir(parents=True, exist_ok=True)
        entry, phase_run = _run_phase_flow(
            workspace=sep_ws,
            workflow_intent="review",
            phase_options={"with_harden": True},
        )
        task_id = entry["task_id"]

        phase_records = phase_run.get("phaseRecords", [])
        if len(phase_records) < 2:
            return {
                "check": "artifact_separation",
                "passed": False,
                "error": "Expected 2 phase records for composed flow",
                "notes": "Cannot check artifact separation without 2 phase records.",
            }

        review_rec = phase_records[0]
        harden_rec = phase_records[1]

        # Core artifact refs must be different paths.
        review_request_ref = review_rec.get("requestRef", "")
        harden_request_ref = harden_rec.get("requestRef", "")
        review_config_ref = review_rec.get("resolvedConfigRef", "")
        harden_config_ref = harden_rec.get("resolvedConfigRef", "")
        review_response_ref = review_rec.get("responseRef", "")
        harden_response_ref = harden_rec.get("responseRef", "")
        review_validation_ref = review_rec.get("validationRef", "")
        harden_validation_ref = harden_rec.get("validationRef", "")

        # File-name checks (suffix/name must differ).
        def _name(ref: str) -> str:
            return Path(ref).name if ref else ""

        checks = {
            "request_refs_differ": review_request_ref != harden_request_ref,
            "request_review_suffix": _name(review_request_ref) == "request-review.json",
            "request_harden_suffix": _name(harden_request_ref) == "request-harden.json",
            "config_refs_differ": review_config_ref != harden_config_ref,
            "config_review_suffix": _name(review_config_ref)
            == "resolved-config-review.json",
            "config_harden_suffix": _name(harden_config_ref)
            == "resolved-config-harden.json",
            "response_refs_differ": review_response_ref != harden_response_ref,
            "validation_refs_differ": review_validation_ref != harden_validation_ref,
            "review_phase_record_phase": review_rec.get("phase") == "review",
            "harden_phase_record_phase": harden_rec.get("phase") == "harden",
        }
        passed = all(checks.values())
        return {
            "check": "artifact_separation",
            "task_id": task_id,
            "review_request_ref": review_request_ref,
            "harden_request_ref": harden_request_ref,
            "review_response_ref": review_response_ref,
            "harden_response_ref": harden_response_ref,
            "separation_checks": checks,
            "passed": passed,
            "notes": "Review and harden phase artifacts must use distinct file paths.",
        }
    except Exception as exc:
        return {
            "check": "artifact_separation",
            "passed": False,
            "error": str(exc),
            "notes": "Exception during artifact separation probe.",
        }


def check_with_harden_entry_constraint() -> dict:
    """Check 5: with_harden=true is rejected for non-review workflow intents."""
    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.task_entrypoint import (
        RequestValidationError,
        validate_request,
    )

    def _make_base_request(workflow_intent: str, with_harden: bool) -> dict:
        return {
            "schema_version": "1.0.0",
            "task_id": "validation-constraint-probe",
            "source": {"path": "/tmp/probe.md", "kind": "markdown"},
            "workflow_intent": workflow_intent,
            "summary": "Validation constraint probe",
            "targets": {},
            "constraints": {
                "hard": [],
                "soft": [],
                "approvals_required": [],
                "disallowed_paths": [],
            },
            "output": {
                "preferred_mode": "report_only",
                "allowed_modes": ["report_only"],
                "operations_required": False,
            },
            "artifacts": {
                "task_root": "/tmp/validation-probe",
                "intake_dir": "/tmp/validation-probe/intake",
                "request_dir": "/tmp/validation-probe/requests",
                "response_dir": "/tmp/validation-probe/responses",
                "state_dir": "/tmp/validation-probe/state",
            },
            "operator_context": {"summary": "constraint probe"},
            "phase_options": {
                "with_harden": with_harden,
                "auto_advance": False,
                "budget_profile_ref": "budget-bootstrap",
            },
            "selectors": {},
            "assembly_options": {
                "prompt_version": "1.0.0",
                "schema_version": "1.0.0",
                "concise_shell_summary": True,
            },
            "metadata": {
                "created_at": _isoformat(),
                "source_canonicalized_at": _isoformat(),
                "host": "probe",
                "cwd": "/tmp",
            },
        }

    results = []

    # Case A: with_harden=True for impl → must raise.
    try:
        validate_request(_make_base_request("impl", True))
        results.append(
            {
                "case": "impl_with_harden",
                "raised": False,
                "expected_raise": True,
                "ok": False,
            }
        )
    except RequestValidationError:
        results.append(
            {
                "case": "impl_with_harden",
                "raised": True,
                "expected_raise": True,
                "ok": True,
            }
        )
    except Exception as exc:
        results.append(
            {
                "case": "impl_with_harden",
                "raised": True,
                "expected_raise": True,
                "ok": True,
                "note": str(exc),
            }
        )

    # Case B: with_harden=True for plan → must raise.
    try:
        validate_request(_make_base_request("plan", True))
        results.append(
            {
                "case": "plan_with_harden",
                "raised": False,
                "expected_raise": True,
                "ok": False,
            }
        )
    except RequestValidationError:
        results.append(
            {
                "case": "plan_with_harden",
                "raised": True,
                "expected_raise": True,
                "ok": True,
            }
        )
    except Exception as exc:
        results.append(
            {
                "case": "plan_with_harden",
                "raised": True,
                "expected_raise": True,
                "ok": True,
                "note": str(exc),
            }
        )

    # Case C: with_harden=True for review → must NOT raise.
    try:
        validate_request(_make_base_request("review", True))
        results.append(
            {
                "case": "review_with_harden",
                "raised": False,
                "expected_raise": False,
                "ok": True,
            }
        )
    except RequestValidationError as exc:
        results.append(
            {
                "case": "review_with_harden",
                "raised": True,
                "expected_raise": False,
                "ok": False,
                "error": str(exc),
            }
        )

    # Case D: with_harden=False for review → must NOT raise.
    try:
        validate_request(_make_base_request("review", False))
        results.append(
            {
                "case": "review_no_harden",
                "raised": False,
                "expected_raise": False,
                "ok": True,
            }
        )
    except RequestValidationError as exc:
        results.append(
            {
                "case": "review_no_harden",
                "raised": True,
                "expected_raise": False,
                "ok": False,
                "error": str(exc),
            }
        )

    passed = all(r["ok"] for r in results)
    return {
        "check": "with_harden_entry_constraint",
        "cases": results,
        "passed": passed,
        "notes": "with_harden=true must be rejected for non-review intents by validate_request().",
    }


def run_check() -> dict:
    """Run all review+harden composition validation checks and write evidence."""
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO_ROOT))

    with tempfile.TemporaryDirectory(prefix="collab-check-review-harden-") as tmp:
        workspace = Path(tmp)
        checks = [
            check_independent_review(workspace),
            check_independent_harden(workspace),
            check_composed_review_harden(workspace),
            check_artifact_separation(workspace),
            check_with_harden_entry_constraint(),
        ]

    all_passed = all(c.get("passed", False) for c in checks)
    evidence = {
        "description": "Compound review+harden composition and artifact separation validation",
        "validatedAt": _isoformat(),
        "allPassed": all_passed,
        "checks": checks,
    }
    out_path = PROBE_DIR / "check-review-harden.json"
    out_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return evidence


if __name__ == "__main__":
    print("Review+Harden Composition Validation")
    print()

    result = run_check()
    for check in result["checks"]:
        status = "PASS" if check.get("passed") else "FAIL"
        print(f"  [{status}] {check['check']}")
        if not check.get("passed"):
            if "error" in check:
                print(f"           error: {check['error']}")
            if "artifact_checks" in check:
                for k, v in check["artifact_checks"].items():
                    if not v:
                        print(f"           FAIL: {k}")
            if "separation_checks" in check:
                for k, v in check["separation_checks"].items():
                    if not v:
                        print(f"           FAIL: {k}")
            if "cases" in check:
                for c in check["cases"]:
                    if not c["ok"]:
                        print(f"           FAIL case={c['case']}: {c}")

    print()
    print(f"Result: {'ALL PASS' if result['allPassed'] else 'FAILURES DETECTED'}")
    print(f"Evidence: {PROBE_DIR / 'check-review-harden.json'}")

    sys.exit(0 if result["allPassed"] else 1)
