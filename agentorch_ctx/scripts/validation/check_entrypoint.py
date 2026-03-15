#!/usr/bin/env python3
"""Entrypoint and Config Resolution Validation.

Validates that the packaged ``agentorch_ctx/scripts/run`` entrypoint works
without any legacy layout dependency, that standalone config loads correctly,
and that PATH/preflight detection works as expected.

Does NOT require live provider CLI execution.
Evidence is written to <data-root>/facts/probe-results/check-entrypoint.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from agentorch_ctx.runtime.pathing import package_root, resolve_data_root  # noqa: E402

COLLAB_ROOT = resolve_data_root(REPO_ROOT)
PROBE_DIR = COLLAB_ROOT / "facts" / "probe-results"
RUN_SCRIPT = package_root() / "scripts" / "run"


def _isoformat() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def validate_entrypoint_help() -> dict:
    """Verify the bundled run helper responds to --help."""
    result = subprocess.run(
        [sys.executable, str(RUN_SCRIPT), "--help"],
        capture_output=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    return {
        "check": "entrypoint_help",
        "command": f"python3 {RUN_SCRIPT} --help",
        "exit_code": result.returncode,
        "stdout_snippet": result.stdout.decode("utf-8", errors="replace")[:1000],
        "stderr_snippet": result.stderr.decode("utf-8", errors="replace")[:500],
        "passed": result.returncode == 0,
        "notes": "agentorch_ctx/scripts/run --help should exit 0 with usage info.",
    }


def validate_config_resolution(workspace_root: Path) -> dict:
    """Verify standalone config loads without legacy layout paths."""
    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.config_loader import load_config_bundle
    from agentorch_ctx.runtime.pathing import resolve_runtime_paths

    try:
        runtime_paths = resolve_runtime_paths(start_dir=workspace_root)
        bundle = load_config_bundle(runtime_paths.repo_root)
        provider_keys = list(bundle.providers.keys())
        strategy_count = len(bundle.strategies)
        fact_refs = [str(p) for p in bundle.verified_fact_refs]
        agent_collab_leak = any("agent-collab" in ref for ref in fact_refs)
        config_root_str = str(bundle.config_root)
        return {
            "check": "config_resolution",
            "config_root": config_root_str,
            "providers_loaded": provider_keys,
            "strategy_count": strategy_count,
            "verified_fact_refs": fact_refs,
            "agent_collab_dependency_detected": agent_collab_leak,
            "passed": (
                len(provider_keys) >= 3
                and not agent_collab_leak
                and "agent-collab" not in config_root_str
            ),
            "notes": "Config must load from agentorch_ctx/ (or .agentorch/), never from a removed legacy layout.",
        }
    except Exception as exc:
        return {
            "check": "config_resolution",
            "passed": False,
            "error": str(exc),
            "notes": "Config resolution raised an exception.",
        }


def validate_resolved_config_snapshot(workspace_root: Path) -> dict:
    """Verify resolved-config snapshot includes all required fields."""
    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.config_loader import resolve_runtime_config

    sample_request = {
        "task_id": "validation-entrypoint-probe",
        "workflow_intent": "plan",
        "phase": "plan",
        "output": {
            "preferred_mode": "report_only",
            "allowed_modes": ["report_only"],
            "operations_required": False,
        },
        "selectors": {},
        "targets": {},
        "phase_options": {},
    }
    try:
        resolution = resolve_runtime_config(
            root_dir=workspace_root, request=sample_request
        )
        rc = resolution.resolved_config
        required_top_keys = [
            "schemaVersion",
            "taskId",
            "phase",
            "provider",
            "strategy",
            "facts",
            "mergeOrder",
        ]
        missing = [k for k in required_top_keys if k not in rc]
        provider_section = rc.get("provider", {})
        provider_has_model = bool(provider_section.get("model"))
        provider_has_command = bool(provider_section.get("command"))
        return {
            "check": "resolved_config_snapshot",
            "missing_required_keys": missing,
            "selected_provider": provider_section.get("provider"),
            "selected_model": provider_section.get("model"),
            "selected_model_ref": provider_section.get("modelRef"),
            "command": provider_section.get("command"),
            "strategy_id": rc.get("strategy", {}).get("selectedStrategyId"),
            "provider_has_model": provider_has_model,
            "provider_has_command": provider_has_command,
            "passed": not missing and provider_has_model and provider_has_command,
            "notes": "resolved-config must include provider.model (actual model ID) not just modelRef.",
        }
    except Exception as exc:
        return {
            "check": "resolved_config_snapshot",
            "passed": False,
            "error": str(exc),
            "notes": "resolve_runtime_config raised an exception.",
        }


def validate_preflight(workspace_root: Path) -> dict:
    """Verify preflight detects CLI binary presence."""
    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.pathing import resolve_runtime_paths
    from agentorch_ctx.runtime.preflight import run_preflight

    try:
        runtime_paths = resolve_runtime_paths(start_dir=workspace_root)
        result = run_preflight(runtime_paths)
        return {
            "check": "preflight",
            "result_type": type(result).__name__,
            "result_repr": str(result)[:500],
            "passed": result is not None,
            "notes": "Preflight must return a result without raising.",
        }
    except Exception as exc:
        return {
            "check": "preflight",
            "passed": False,
            "error": str(exc),
            "notes": "Preflight raised an exception.",
        }


def validate_dispatch_request_write(workspace_root: Path) -> dict:
    """Verify ClaudeCodeSkill.dispatch() writes a valid request artifact."""
    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.claude_code_skill import ClaudeCodeSkill

    fixture_path = workspace_root / "probe-task.md"
    fixture_path.write_text(
        "# Entrypoint Probe\n\nValidate entrypoint dispatch writes correct artifacts.\n",
        encoding="utf-8",
    )
    (workspace_root / "AGENTS.md").write_text("# probe workspace\n", encoding="utf-8")

    try:
        dispatch = ClaudeCodeSkill(root_dir=workspace_root).dispatch(
            source_path=fixture_path,
            workflow_intent="plan",
            source_kind="markdown",
            selectors={"strategy": "COLLAB_PLAN_MINIMAL"},
            operator_context={"summary": "entrypoint validation probe"},
        )
        request_exists = dispatch.request_path.exists()
        request_data = (
            json.loads(dispatch.request_path.read_text(encoding="utf-8"))
            if request_exists
            else {}
        )
        has_task_id = bool(request_data.get("task_id"))
        has_phase = bool(request_data.get("workflow_intent"))
        return {
            "check": "dispatch_request_write",
            "request_path": str(dispatch.request_path),
            "request_exists": request_exists,
            "task_id": request_data.get("task_id"),
            "workflow_intent": request_data.get("workflow_intent"),
            "controller_state_path": str(dispatch.controller_state_path),
            "passed": request_exists and has_task_id and has_phase,
            "notes": "Dispatch must write a valid request JSON artifact.",
        }
    except Exception as exc:
        return {
            "check": "dispatch_request_write",
            "passed": False,
            "error": str(exc),
            "notes": "ClaudeCodeSkill.dispatch() raised an exception.",
        }


def validate_prompt_bundle(workspace_root: Path) -> dict:
    """Verify prompt assembly produces a valid bundle artifact."""
    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.claude_code_skill import ClaudeCodeSkill
    from agentorch_ctx.runtime.phase_runner import PhaseRunner

    fixture_path = workspace_root / "probe-plan-task.md"
    fixture_path.write_text(
        "# Prompt Bundle Probe\n\nValidate prompt bundle is written with correct fields.\n",
        encoding="utf-8",
    )
    (workspace_root / "AGENTS.md").write_text("# probe workspace\n", encoding="utf-8")

    try:
        dispatch = ClaudeCodeSkill(root_dir=workspace_root).dispatch(
            source_path=fixture_path,
            workflow_intent="plan",
            source_kind="markdown",
            selectors={"strategy": "COLLAB_PLAN_MINIMAL"},
            operator_context={"summary": "prompt bundle validation probe"},
        )
        result = PhaseRunner(workspace_root).run(request_path=dispatch.request_path)
        phase_run = json.loads(result.phase_run_path.read_text(encoding="utf-8"))[
            "payload"
        ]
        first_record = phase_run.get("phaseRecords", [{}])[0]
        prompt_bundle_ref = first_record.get("promptBundleRef")
        resolved_config_ref = first_record.get("resolvedConfigRef")
        routing_result_ref = first_record.get("routingResultRef")
        prompt_bundle_exists = (
            Path(prompt_bundle_ref).exists() if prompt_bundle_ref else False
        )
        resolved_config_exists = (
            Path(resolved_config_ref).exists() if resolved_config_ref else False
        )
        routing_result_exists = (
            Path(routing_result_ref).exists() if routing_result_ref else False
        )
        return {
            "check": "prompt_bundle",
            "prompt_bundle_ref": prompt_bundle_ref,
            "resolved_config_ref": resolved_config_ref,
            "routing_result_ref": routing_result_ref,
            "prompt_bundle_exists": prompt_bundle_exists,
            "resolved_config_exists": resolved_config_exists,
            "routing_result_exists": routing_result_exists,
            "passed": prompt_bundle_exists
            and resolved_config_exists
            and routing_result_exists,
            "notes": "Phase runner must write prompt-bundle, resolved-config, and routing-result artifacts.",
        }
    except Exception as exc:
        return {
            "check": "prompt_bundle",
            "passed": False,
            "error": str(exc),
            "notes": "PhaseRunner raised an exception during prompt bundle validation.",
        }


def run_check() -> dict:
    """Run all entrypoint and config resolution checks and write evidence."""
    PROBE_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="agentorch-check-entrypoint-") as tmp:
        workspace = Path(tmp)
        checks = [
            validate_entrypoint_help(),
            validate_config_resolution(workspace),
            validate_resolved_config_snapshot(workspace),
            validate_preflight(workspace),
            validate_dispatch_request_write(workspace),
            validate_prompt_bundle(workspace),
        ]

    all_passed = all(c.get("passed", False) for c in checks)
    evidence = {
        "description": "Entrypoint, config resolution, and prompt assembly validation",
        "validatedAt": _isoformat(),
        "allPassed": all_passed,
        "checks": checks,
    }
    out_path = PROBE_DIR / "check-entrypoint.json"
    out_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return evidence


if __name__ == "__main__":
    print("Entrypoint and Config Resolution Validation")
    print()
    result = run_check()
    for check in result["checks"]:
        status = "PASS" if check.get("passed") else "FAIL"
        print(f"  [{status}] {check['check']}")
        if not check.get("passed"):
            print(f"         {check.get('error') or check.get('notes', '')}")
    print()
    print(f"Result: {'ALL PASS' if result['allPassed'] else 'FAILURES DETECTED'}")
    print(f"Evidence: {PROBE_DIR / 'check-entrypoint.json'}")
    sys.exit(0 if result["allPassed"] else 1)
