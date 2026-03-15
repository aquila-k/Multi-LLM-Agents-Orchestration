#!/usr/bin/env python3
"""Validation Suite Runner.

Orchestrates all validation checks in sequence and emits a final summary.
Checks that require live provider CLI execution are noted as such.

Usage:
    python3 agentorch_ctx/scripts/validation/run_checks.py [--skip-live] [--provider PROVIDER]

Options:
    --skip-live    Skip live provider execution check; run only stub-safe checks.
    --provider P   Run live check only for the named provider (repeatable).
    --timeout N    Timeout in seconds per provider for live check (default: 120).

Exit codes:
    0  All checks passed (required gates clear; deferred gates tolerated).
    1  One or more required gates failed.
    2  Script-level error.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from agentorch_ctx.runtime.pathing import resolve_data_root  # noqa: E402

COLLAB_ROOT = resolve_data_root(REPO_ROOT)
PROBE_DIR = COLLAB_ROOT / "facts" / "probe-results"
VALIDATION_DIR = Path(__file__).resolve().parent


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, VALIDATION_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validation suite runner")
    parser.add_argument(
        "--skip-live", action="store_true", help="Skip live provider execution check"
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=["codex", "gemini", "copilot"],
        help="Run live check only for the named provider (repeatable).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds per provider for live check (default: 120).",
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(REPO_ROOT))
    PROBE_DIR.mkdir(parents=True, exist_ok=True)

    # Stub-safe checks (no live provider required).
    checks: list[tuple[str, str, bool]] = [
        ("check_entrypoint", "Entrypoint & config resolution", False),
        ("check_resume", "Resume & stop-confirm", False),
        ("check_review_harden", "Compound review+harden composition", False),
        ("check_artifacts", "Artifact lineage & operator visibility", False),
    ]
    if not args.skip_live:
        checks.insert(1, ("check_live_providers", "Provider live execution", True))

    check_results: list[dict] = []
    all_required_pass = True

    for module_name, label, is_live in checks:
        print(f"\n--- {label} ---")
        try:
            mod = _load_module(module_name)
            if module_name == "check_live_providers":
                result = mod.run_check(
                    providers=args.provider,
                    timeout_sec=args.timeout,
                )
                any_run = result.get("anyProviderRun", False)
                all_run_passed = result.get("allRunProvidersPassed", False)
                phase_passed = any_run and all_run_passed
                for r in result.get("results", []):
                    provider = r["provider"]
                    outcome = r.get("outcome", "unknown")
                    model = r.get("model", "")
                    if outcome == "skipped":
                        print(f"  [SKIP] {provider}")
                    elif outcome == "passed":
                        print(f"  [PASS] {provider} model={model}")
                    else:
                        print(
                            f"  [FAIL] {provider} model={model} error={r.get('error', '')}"
                        )
            else:
                result = mod.run_check()
                phase_passed = result.get("allPassed", False)
                for check in result.get("checks", []):
                    status = "PASS" if check.get("passed") else "FAIL"
                    print(f"  [{status}] {check['check']}")

            check_results.append(
                {"check": module_name, "label": label, "passed": phase_passed}
            )
            if not phase_passed:
                all_required_pass = False

        except Exception as exc:
            print(f"  [ERROR] {exc}")
            check_results.append(
                {
                    "check": module_name,
                    "label": label,
                    "passed": False,
                    "error": str(exc),
                }
            )
            all_required_pass = False

    # Final release gate evaluation.
    print("\n--- Release Gate ---")
    try:
        gate_mod = _load_module("release_gate")
        gate_result = gate_mod.evaluate()
        for gate in gate_result.get("gates", []):
            g_name = gate["gate"]
            passed = gate.get("passed", False)
            deferred = gate.get("deferred", False)
            status = gate.get("status", "unknown")
            if deferred and status == "not_run":
                symbol = "[DEFER]"
            elif passed:
                symbol = "[PASS] "
            else:
                symbol = "[FAIL] "
            print(f"  {symbol} {g_name}: {status}")
        gate_blocked = gate_result.get("liveActivationBlocked", True)
        print(f"\n  Summary: {gate_result.get('summary', 'unknown')}")
    except Exception as exc:
        print(f"  [ERROR] Release gate evaluation failed: {exc}")
        gate_blocked = True

    print("\n" + "=" * 60)
    print("Validation Results")
    print("=" * 60)
    for cr in check_results:
        status = "PASS" if cr.get("passed") else "FAIL"
        print(f"  [{status}] {cr['label']}")
    print()
    if gate_blocked:
        print("OUTCOME: LIVE ACTIVATION BLOCKED")
    else:
        print("OUTCOME: LIVE ACTIVATION CLEAR")
    print(f"Evidence: {PROBE_DIR}")
    print("=" * 60)

    return 0 if not gate_blocked else 1


if __name__ == "__main__":
    sys.exit(main())
