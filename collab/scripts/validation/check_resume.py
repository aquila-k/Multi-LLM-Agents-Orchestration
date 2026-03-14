#!/usr/bin/env python3
"""Resume and Stop-Confirm Validation.

Validates the pause/resume state-machine mechanics:
  1. manifest snapshot shows controllerStatus=blocked on stop-and-confirm
  2. state machine allows blocked -> running (resume) transition
  3. resume cursor is written with correct phase/strategy/step refs
  4. budget-gate preflight produces a stop artifact when budget exceeded
  5. approval continuation clears the blocked state on resume

Does NOT require live provider CLI execution.
Evidence is written to collab/facts/probe-results/check-resume.json.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COLLAB_ROOT = REPO_ROOT / "collab"
PROBE_DIR = COLLAB_ROOT / "facts" / "probe-results"


def _isoformat() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def check_state_machine_resume_transition() -> dict:
    """Verify state machine allows blocked -> running (resume)."""
    sys.path.insert(0, str(REPO_ROOT))
    from collab.runtime.state_machine import StateMachine

    sm = StateMachine()
    transitions = [
        ("pending", "running", True),
        ("running", "blocked", True),
        ("blocked", "running", True),  # resume path
        ("blocked", "canceled", True),
        ("running", "succeeded", True),
        ("succeeded", "running", False),  # terminal, no further transition
    ]
    results = []
    all_ok = True
    for before, after, expected_allowed in transitions:
        result = sm.transition_task(before, after)
        ok = result.allowed == expected_allowed
        if not ok:
            all_ok = False
        results.append(
            {
                "before": before,
                "after": after,
                "expected_allowed": expected_allowed,
                "actual_allowed": result.allowed,
                "ok": ok,
            }
        )
    return {
        "check": "state_machine_resume_transition",
        "transitions": results,
        "passed": all_ok,
        "notes": "State machine must allow blocked->running (resume) and block terminal->running.",
    }


def check_manifest_blocked_status(workspace: Path) -> dict:
    """Verify manifest snapshot shows controllerStatus=blocked on stop-and-confirm."""
    sys.path.insert(0, str(REPO_ROOT))
    from collab.runtime.config_loader import resolve_runtime_config
    from collab.runtime.manifest_store import build_manifest_snapshot

    sample_request = {
        "task_id": "validation-resume-probe",
        "workflow_intent": "plan",
        "phase": "plan",
        "output": {
            "preferred_mode": "report_only",
            "allowed_modes": ["report_only"],
            "operations_required": False,
        },
        "selectors": {"strategy": "COLLAB_PLAN_FULL"},
        "targets": {},
        "phase_options": {},
        "constraints": {"approvals_required": True},
        "summary": "Resume validation probe",
    }
    try:
        resolution = resolve_runtime_config(root_dir=workspace, request=sample_request)
        rc = resolution.resolved_config

        blocked_manifest = build_manifest_snapshot(
            request=sample_request,
            resolved_config=rc,
            routing_result={"budgetState": "healthy"},
            artifact_refs={},
            stop_and_confirm=True,
            blocked_reason="approval_required: operator confirmation needed before live execution",
        )
        resumed_manifest = build_manifest_snapshot(
            request={
                **sample_request,
                "selectors": {
                    **sample_request["selectors"],
                    "approval_continuation": "validation-approval-token",
                },
            },
            resolved_config=rc,
            routing_result={"budgetState": "healthy"},
            artifact_refs={},
            stop_and_confirm=False,
            blocked_reason="",
        )

        blocked_ok = blocked_manifest.get("controllerStatus") == "blocked"
        running_ok = resumed_manifest.get("controllerStatus") == "running"
        blockers_ok = len(blocked_manifest.get("blockers", [])) > 0
        approval_ok = (
            resumed_manifest.get("approvalState", {}).get("status") == "approved"
        )

        return {
            "check": "manifest_blocked_status",
            "blocked_controller_status": blocked_manifest.get("controllerStatus"),
            "resumed_controller_status": resumed_manifest.get("controllerStatus"),
            "blockers_present_when_blocked": blockers_ok,
            "approval_status_on_resume": resumed_manifest.get("approvalState", {}).get(
                "status"
            ),
            "passed": blocked_ok and running_ok and blockers_ok and approval_ok,
            "notes": "Blocked manifest must show controllerStatus=blocked; resumed must show running.",
        }
    except Exception as exc:
        return {
            "check": "manifest_blocked_status",
            "passed": False,
            "error": str(exc),
            "notes": "build_manifest_snapshot raised an exception.",
        }


def check_resume_cursor_structure(workspace: Path) -> dict:
    """Verify resume cursor fields are populated after stop-and-confirm."""
    sys.path.insert(0, str(REPO_ROOT))
    from collab.runtime.config_loader import resolve_runtime_config
    from collab.runtime.manifest_store import build_manifest_snapshot

    sample_request = {
        "task_id": "validation-cursor-probe",
        "workflow_intent": "impl",
        "phase": "impl",
        "output": {
            "preferred_mode": "apply_and_report",
            "allowed_modes": ["apply_and_report"],
            "operations_required": True,
        },
        "selectors": {"strategy": "COLLAB_IMPL_SAFE", "step": "analyze"},
        "targets": {"path": "src/"},
        "phase_options": {},
        "constraints": {},
        "summary": "Resume cursor validation probe",
    }
    try:
        resolution = resolve_runtime_config(root_dir=workspace, request=sample_request)
        rc = resolution.resolved_config

        manifest = build_manifest_snapshot(
            request=sample_request,
            resolved_config=rc,
            routing_result={"budgetState": "healthy"},
            artifact_refs={"manifest": "/tmp/probe/manifest.json"},
            stop_and_confirm=True,
            blocked_reason="budget_preflight_exceeded",
        )

        cursor = manifest.get("resumeCursor", {})
        has_phase = bool(cursor.get("phase"))
        has_step = bool(cursor.get("step"))
        has_strategy = bool(cursor.get("strategy"))

        return {
            "check": "resume_cursor_structure",
            "cursor": cursor,
            "has_phase": has_phase,
            "has_step": has_step,
            "has_strategy": has_strategy,
            "passed": has_phase and has_strategy,
            "notes": "Resume cursor must include at least phase and strategy references.",
        }
    except Exception as exc:
        return {
            "check": "resume_cursor_structure",
            "passed": False,
            "error": str(exc),
            "notes": "Resume cursor check raised an exception.",
        }


def check_budget_gate_stop(_workspace: Path) -> dict:
    """Verify BudgetGate.evaluate() correctly classifies budget states."""
    sys.path.insert(0, str(REPO_ROOT))
    from collab.runtime.budget_gate import BudgetGate

    try:
        gate = BudgetGate()

        exceeded = gate.evaluate(
            {
                "hardCap": 10.0,
                "consumed": 9.5,
                "estimatedNextCost": 1.0,
            }
        )
        stop_on_exceeded = exceeded.stop_required

        near_cap = gate.evaluate(
            {
                "hardCap": 10.0,
                "consumed": 9.0,
                "estimatedNextCost": 0.1,
            }
        )
        stop_on_near = near_cap.stop_required

        healthy = gate.evaluate(
            {
                "hardCap": 100.0,
                "consumed": 5.0,
                "estimatedNextCost": 1.0,
            }
        )
        pass_on_healthy = not healthy.stop_required

        all_ok = stop_on_exceeded and stop_on_near and pass_on_healthy
        return {
            "check": "budget_gate_stop",
            "exceeded_budget_state": exceeded.budget_state,
            "exceeded_stop_required": exceeded.stop_required,
            "near_cap_budget_state": near_cap.budget_state,
            "near_cap_stop_required": near_cap.stop_required,
            "healthy_budget_state": healthy.budget_state,
            "healthy_stop_required": healthy.stop_required,
            "stop_triggered_on_exceeded": stop_on_exceeded,
            "stop_triggered_on_near_cap": stop_on_near,
            "no_stop_on_healthy": pass_on_healthy,
            "passed": all_ok,
            "notes": "BudgetGate must stop on exceeded/near-cap budget and pass on healthy budget.",
        }
    except Exception as exc:
        return {
            "check": "budget_gate_stop",
            "passed": False,
            "error": str(exc),
            "notes": "BudgetGate.evaluate() raised an exception.",
        }


def check_pause_confirm_artifact(workspace: Path) -> dict:
    """Verify pause-confirm artifact is built with correct fields."""
    sys.path.insert(0, str(REPO_ROOT))
    from collab.runtime.config_loader import resolve_runtime_config
    from collab.runtime.manifest_store import build_pause_confirm

    sample_request = {
        "task_id": "validation-pause-probe",
        "workflow_intent": "review",
        "phase": "review",
        "output": {
            "preferred_mode": "report_only",
            "allowed_modes": ["report_only"],
            "operations_required": False,
        },
        "selectors": {},
        "targets": {},
        "phase_options": {},
        "constraints": {"approvals_required": True},
        "summary": "Pause confirm validation probe",
    }
    try:
        resolution = resolve_runtime_config(root_dir=workspace, request=sample_request)
        rc = resolution.resolved_config

        probe_refs = {
            "request": "/tmp/probe/request.json",
            "resolvedConfig": "/tmp/probe/resolved-config.json",
            "routingResult": "/tmp/probe/routing-result.json",
            "manifest": "/tmp/probe/manifest.json",
        }
        pause_artifact = build_pause_confirm(
            request=sample_request,
            resolved_config=rc,
            routing_result={"budgetState": "healthy"},
            blocked_reason="blocked_for_approval",
            artifact_refs=probe_refs,
        )
        has_stop_reason = bool(pause_artifact.get("stopReason"))
        has_reason_code = bool(pause_artifact.get("reasonCode"))
        has_resume_options = bool(pause_artifact.get("resumeOptions"))

        return {
            "check": "pause_confirm_artifact",
            "artifact_keys": list(pause_artifact.keys()),
            "has_stop_reason": has_stop_reason,
            "has_reason_code": has_reason_code,
            "has_resume_options": has_resume_options,
            "stop_reason": pause_artifact.get("stopReason"),
            "passed": has_stop_reason and has_reason_code and has_resume_options,
            "notes": "Pause-confirm artifact must include stopReason, reasonCode, and resumeOptions.",
        }
    except Exception as exc:
        return {
            "check": "pause_confirm_artifact",
            "passed": False,
            "error": str(exc),
            "notes": "build_pause_confirm raised an exception.",
        }


def run_check() -> dict:
    """Run all resume and stop-confirm checks and write evidence."""
    PROBE_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="collab-check-resume-") as tmp:
        workspace = Path(tmp)
        (workspace / "AGENTS.md").write_text("# validation probe\n", encoding="utf-8")

        checks = [
            check_state_machine_resume_transition(),
            check_manifest_blocked_status(workspace),
            check_resume_cursor_structure(workspace),
            check_budget_gate_stop(workspace),
            check_pause_confirm_artifact(workspace),
        ]

    all_passed = all(c.get("passed", False) for c in checks)
    evidence = {
        "description": "Resume and stop-confirm validation (stub-mode, no live provider required)",
        "validatedAt": _isoformat(),
        "allPassed": all_passed,
        "checks": checks,
    }
    out_path = PROBE_DIR / "check-resume.json"
    out_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return evidence


if __name__ == "__main__":
    print("Resume and Stop-Confirm Validation")
    print()

    result = run_check()
    for check in result["checks"]:
        status = "PASS" if check.get("passed") else "FAIL"
        print(f"  [{status}] {check['check']}")
        if not check.get("passed"):
            print(f"         {check.get('error') or check.get('notes', '')}")

    print()
    print(f"Result: {'ALL PASS' if result['allPassed'] else 'FAILURES DETECTED'}")
    print(f"Evidence: {PROBE_DIR / 'check-resume.json'}")
    sys.exit(0 if result["allPassed"] else 1)
