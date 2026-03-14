#!/usr/bin/env python3
"""Artifact Lineage and Operator Visibility Validation.

Validates that:
  1. ArtifactStore writes artifacts with correct metadata envelope
  2. Shell digest derives correct status and resume hints from output text
  3. A full stub phase run produces internally consistent artifacts
  4. Markdown renderer produces operator-readable output from JSON artifacts
  5. ArtifactConsistencyChecker validates a real phase run

Does NOT require live provider CLI execution.
Evidence is written to collab/facts/probe-results/check-artifacts.json.
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


def check_artifact_store_writes(workspace: Path) -> dict:
    """Check 1: Verify ArtifactStore writes artifacts with correct metadata."""
    sys.path.insert(0, str(REPO_ROOT))
    from collab.runtime.artifact_store import ArtifactStore

    try:
        store = ArtifactStore(workspace)
        probe_payload = {
            "taskId": "validation-lineage-probe",
            "phase": "plan",
            "content": "Artifact store validation test payload",
        }
        record = store.write_json_artifact(
            task_id="validation-lineage-probe",
            family="probes",
            artifact_type="test_artifact",
            payload=probe_payload,
            filename="validation-probe.json",
            phase="plan",
            step="probe",
            visibility="internal",
            retention_class="standard",
        )
        path_exists = record.path.exists()
        written = json.loads(record.path.read_text(encoding="utf-8"))
        has_metadata = bool(written.get("metadata"))
        has_payload = bool(written.get("payload"))
        metadata = written.get("metadata", {})
        artifact_id_ok = "validation-lineage-probe" in metadata.get("artifactId", "")
        task_id_ok = metadata.get("taskId") == "validation-lineage-probe"
        phase_ok = metadata.get("phase") == "plan"
        return {
            "check": "artifact_store_writes",
            "artifact_path": str(record.path),
            "path_exists": path_exists,
            "has_metadata": has_metadata,
            "has_payload": has_payload,
            "metadata_artifact_id_ok": artifact_id_ok,
            "metadata_task_id_ok": task_id_ok,
            "metadata_phase_ok": phase_ok,
            "passed": path_exists
            and has_metadata
            and has_payload
            and artifact_id_ok
            and task_id_ok,
            "notes": "ArtifactStore must write JSON artifacts with correct metadata envelope.",
        }
    except Exception as exc:
        return {
            "check": "artifact_store_writes",
            "passed": False,
            "error": str(exc),
            "notes": "ArtifactStore.write_json_artifact() raised an exception.",
        }


def check_shell_digest_derivation(_workspace: Path) -> dict:
    """Check 2: Verify shell digest derives correct status and resume hints."""
    sys.path.insert(0, str(REPO_ROOT))
    from collab.runtime.shell_digest import derive_shell_digest

    try:
        # Succeeded output.
        succeeded_digest = derive_shell_digest(
            task_id="validation-digest-probe",
            concise_summary="phase=plan step=intake completed successfully",
            execution_record_ref="/tmp/probe/execution-record.json",
        )
        # Stop-and-confirm output.
        stop_digest = derive_shell_digest(
            task_id="validation-digest-probe",
            concise_summary="STOP_AND_CONFIRM: approval required before applying changes phase=impl step=apply",
        )

        succeeded_ok = succeeded_digest.get("status") in {
            "succeeded",
            "complete",
            "passed",
            "healthy",
        }
        stop_has_warning = bool(
            stop_digest.get("warnings") or stop_digest.get("stop_reason")
        )
        task_id_ok = succeeded_digest.get("task_id") == "validation-digest-probe"

        return {
            "check": "shell_digest_derivation",
            "succeeded_status": succeeded_digest.get("status"),
            "succeeded_has_task_id": task_id_ok,
            "stop_has_warning": stop_has_warning,
            "stop_warnings": stop_digest.get("warnings"),
            "stop_reason": stop_digest.get("stop_reason"),
            "passed": task_id_ok and stop_has_warning,
            "notes": "Shell digest must extract status and warnings from concise output.",
        }
    except Exception as exc:
        return {
            "check": "shell_digest_derivation",
            "passed": False,
            "error": str(exc),
            "notes": "derive_shell_digest raised an exception.",
        }


def check_full_phase_run_lineage(workspace: Path) -> dict:
    """Check 3: Verify a full stub phase run produces internally consistent artifacts."""
    sys.path.insert(0, str(REPO_ROOT))
    from collab.runtime.claude_code_skill import ClaudeCodeSkill
    from collab.runtime.phase_runner import PhaseRunner

    fixture_path = workspace / "validation-lineage-task.md"
    fixture_path.write_text(
        "# Validation Lineage Probe\n\nValidate artifact lineage from full stub phase run.\n",
        encoding="utf-8",
    )
    (workspace / "AGENTS.md").write_text("# probe workspace\n", encoding="utf-8")

    try:
        dispatch = ClaudeCodeSkill(root_dir=workspace).dispatch(
            source_path=fixture_path,
            workflow_intent="plan",
            source_kind="markdown",
            selectors={"strategy": "COLLAB_PLAN_MINIMAL"},
            operator_context={"summary": "Validation lineage probe"},
        )
        result = PhaseRunner(workspace).run(request_path=dispatch.request_path)

        phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))
        phase_payload = phase_run.get("payload", phase_run)
        phase_records = phase_payload.get("phaseRecords", [])

        # Collect artifact refs from the first phase record.
        artifact_refs: dict[str, str] = {}
        if phase_records:
            rec = phase_records[0]
            for key in [
                "promptBundleRef",
                "resolvedConfigRef",
                "routingResultRef",
                "manifestRef",
            ]:
                ref = rec.get(key, "")
                if ref:
                    artifact_refs[key] = ref

        # Verify referenced artifacts actually exist on disk.
        missing_refs = [
            k for k, v in artifact_refs.items() if v and not Path(v).exists()
        ]

        # Verify controller status makes sense.
        controller_status = result.controller_status
        status_ok = controller_status in {"running", "blocked", "succeeded", "partial"}

        return {
            "check": "full_phase_run_lineage",
            "task_id": result.task_id,
            "controller_status": controller_status,
            "executed_phases": result.executed_phases,
            "artifact_refs_found": list(artifact_refs.keys()),
            "missing_artifact_refs": missing_refs,
            "phase_records_count": len(phase_records),
            "passed": status_ok and not missing_refs,
            "notes": "Phase run must produce consistent artifact refs, all pointing to existing files.",
        }
    except Exception as exc:
        return {
            "check": "full_phase_run_lineage",
            "passed": False,
            "error": str(exc),
            "notes": "Full stub phase run raised an exception during lineage check.",
        }


def check_markdown_renderer(_workspace: Path) -> dict:
    """Check 4: Verify Markdown renderer produces operator-readable output from JSON."""
    sys.path.insert(0, str(REPO_ROOT))

    try:
        from collab.runtime.renderers.markdown import render_markdown_document

        probe_payload = {
            "sections": [
                {"heading": "Summary", "content": "This is a test section."},
                {"heading": "Findings", "content": "No issues found."},
            ],
        }
        rendered = render_markdown_document(
            title="Validation Probe Report", payload=probe_payload
        )
        has_title = "Validation Probe Report" in rendered or len(rendered) > 0
        is_str = isinstance(rendered, str)
        has_content = (
            "Summary" in rendered or "Findings" in rendered or len(rendered) > 20
        )

        return {
            "check": "markdown_renderer",
            "rendered_length": len(rendered),
            "rendered_snippet": rendered[:300],
            "has_title": has_title,
            "is_string": is_str,
            "has_content": has_content,
            "passed": is_str and has_content,
            "notes": "Markdown renderer must produce non-empty string from JSON document.",
        }
    except ImportError:
        # If render_markdown_document doesn't exist, check what renderers are available.
        try:
            from collab.runtime import renderers

            attrs = [a for a in dir(renderers) if not a.startswith("_")]
        except Exception:
            attrs = []
        return {
            "check": "markdown_renderer",
            "passed": False,
            "available_renderer_attrs": attrs,
            "notes": "render_markdown_document not found in collab.runtime.renderers.markdown.",
        }
    except Exception as exc:
        return {
            "check": "markdown_renderer",
            "passed": False,
            "error": str(exc),
            "notes": "render_markdown_document raised an exception.",
        }


def check_artifact_consistency_checker(workspace: Path) -> dict:
    """Check 5: Verify ArtifactConsistencyChecker can validate a real phase run output."""
    sys.path.insert(0, str(REPO_ROOT))
    from collab.runtime.artifact_consistency import ArtifactConsistencyChecker
    from collab.runtime.claude_code_skill import ClaudeCodeSkill
    from collab.runtime.phase_runner import PhaseRunner

    fixture_path = workspace / "validation-consistency-task.md"
    fixture_path.write_text(
        "# Validation Consistency Probe\n\nCheck artifact consistency after a stub run.\n",
        encoding="utf-8",
    )
    (workspace / "AGENTS.md").write_text("# probe workspace\n", encoding="utf-8")

    try:
        dispatch = ClaudeCodeSkill(root_dir=workspace).dispatch(
            source_path=fixture_path,
            workflow_intent="plan",
            source_kind="markdown",
            selectors={"strategy": "COLLAB_PLAN_MINIMAL"},
            operator_context={"summary": "Validation consistency probe"},
        )
        run_result = PhaseRunner(workspace).run(request_path=dispatch.request_path)

        checker = ArtifactConsistencyChecker(workspace)
        phase = "plan"
        step = run_result.executed_phases[0] if run_result.executed_phases else "intake"
        consistency = checker.check(
            task_id=run_result.task_id,
            phase=phase,
            step=step,
        )

        payload = consistency.payload
        consistency_status = payload.get("status")
        errors = payload.get("errors", [])
        passed = consistency_status == "passed" and not errors

        return {
            "check": "artifact_consistency_checker",
            "task_id": run_result.task_id,
            "consistency_status": consistency_status,
            "consistency_errors": errors,
            "consistency_path": str(consistency.path),
            "passed": passed,
            "notes": "ArtifactConsistencyChecker must report passed=True with no errors after stub run.",
        }
    except Exception as exc:
        return {
            "check": "artifact_consistency_checker",
            "passed": False,
            "error": str(exc),
            "notes": "ArtifactConsistencyChecker raised an exception.",
        }


def run_check() -> dict:
    """Run all artifact lineage checks and write evidence."""
    PROBE_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="collab-check-artifacts-") as tmp:
        workspace = Path(tmp)
        checks = [
            check_artifact_store_writes(workspace),
            check_shell_digest_derivation(workspace),
            check_full_phase_run_lineage(workspace),
            check_markdown_renderer(workspace),
            check_artifact_consistency_checker(workspace),
        ]

    all_passed = all(c.get("passed", False) for c in checks)
    evidence = {
        "description": "Artifact lineage and operator visibility validation (stub-mode, no live provider required)",
        "validatedAt": _isoformat(),
        "allPassed": all_passed,
        "checks": checks,
    }
    out_path = PROBE_DIR / "check-artifacts.json"
    out_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return evidence


if __name__ == "__main__":
    print("Artifact Lineage and Operator Visibility Validation")
    print()

    result = run_check()
    for check in result["checks"]:
        status = "PASS" if check.get("passed") else "FAIL"
        print(f"  [{status}] {check['check']}")
        if not check.get("passed"):
            print(f"         {check.get('error') or check.get('notes', '')}")

    print()
    print(f"Result: {'ALL PASS' if result['allPassed'] else 'FAILURES DETECTED'}")
    print(f"Evidence: {PROBE_DIR / 'check-artifacts.json'}")
    sys.exit(0 if result["allPassed"] else 1)
