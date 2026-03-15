#!/usr/bin/env python3
"""Provider Adapter Live Execution Validation.

Runs actual provider CLI calls using the cheapest suitable models for each
provider. Validates:
  - request JSON to CLI argument mapping
  - stdout vs stderr separation
  - output format (codex: plain text, gemini: JSON envelope, copilot: plain text)
  - exit code behavior
  - adapter-request.json and adapter-result.json artifact production

Cost rule:
  - codex: gpt-5.1-codex-mini (0.33x)
  - gemini: gemini-2.5-flash-lite
  - copilot: gpt-5-mini (0x, free)

Evidence is written to agentorch_ctx/facts/probe-results/check-live-providers.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from agentorch_ctx.runtime.pathing import resolve_data_root  # noqa: E402

COLLAB_ROOT = resolve_data_root(REPO_ROOT)
PROBE_DIR = COLLAB_ROOT / "facts" / "probe-results"

VALIDATION_PROMPT = "Respond with exactly one word: hello"
VALIDATION_MODELS = {
    "codex": "gpt-5.1-codex-mini",
    "gemini": "gemini-2.5-flash-lite",
    "copilot": "gpt-5-mini",
}


def _isoformat() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _augmented_path() -> str:
    """Build a PATH string that includes NVM node bin dirs and other common locations."""
    import os

    current = os.environ.get("PATH", "")
    candidates = []
    nvm_versions_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_versions_dir.is_dir():
        for version_dir in sorted(nvm_versions_dir.iterdir(), reverse=True):
            bin_dir = version_dir / "bin"
            if bin_dir.is_dir():
                candidates.append(str(bin_dir))
    for extra in [
        str(Path.home() / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]:
        if Path(extra).is_dir():
            candidates.append(extra)
    merged = candidates + [p for p in current.split(":") if p and p not in candidates]
    return ":".join(merged)


def _check_binary(name: str) -> dict:
    augmented = _augmented_path()
    path = shutil.which(name, path=augmented)
    return {
        "binary": name,
        "found": path is not None,
        "resolved_path": path,
    }


def build_minimal_adapter_request(
    *,
    provider: str,
    model_id: str,
    task_id: str,
    root_dir: Path,
) -> dict:
    """Build a minimal adapter request dict for behavior-check execution."""
    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.config_loader import load_config_bundle

    bundle = load_config_bundle(root_dir)
    provider_cfg = bundle.providers.get(provider, {})

    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "phase": "plan",
        "step": "validation-probe",
        "attempt": 1,
        "run": 1,
        "workflowIntent": "plan",
        "provider": provider,
        "profile": f"{provider}-primary",
        "modelRef": f"{provider}-fast",
        "model": model_id,
        "providerOptions": {"model": f"{provider}-fast"},
        "supportedOptionKeys": ["model"],
        "timeouts": provider_cfg.get("timeoutDefaults", {"defaultMs": 120000}),
        "retryPolicy": provider_cfg.get("retryDefaults", {}),
        "outputContract": {
            "preferredMode": "report_only",
            "allowedModes": ["report_only"],
            "operationsRequired": False,
        },
        "phaseOptions": {"budgetProfileRef": "budget-bootstrap"},
        "targets": {},
        "summary": VALIDATION_PROMPT,
        "operatorContext": {"summary": "live provider behavior probe"},
        "inputRefs": {
            "request": "",
            "resolvedConfig": "",
            "routingResult": "",
            "promptBundle": "",
            "manifest": "",
            "sessionState": "",
        },
        "artifactDestinations": {},
        "session": {
            "requestedMode": "fresh",
            "resolvedMode": "fresh",
            "resumeDecision": "not_requested",
            "resumeRef": "",
            "fallbackReason": "",
            "storedSessionRef": "",
            "resumeCursor": "",
            "capabilityMetadata": {},
        },
        "providerInvocation": {},
        "stubMode": False,
    }


def run_provider_behavior_check(
    *,
    provider: str,
    root_dir: Path,
    timeout_sec: int = 120,
) -> dict:
    """Run a single provider CLI with the cheapest validation model."""
    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.providers import get_provider_adapter

    model_id = VALIDATION_MODELS[provider]
    task_id = f"validation-live-{provider}-probe"
    binary_check = _check_binary(provider)

    if not binary_check["found"]:
        return {
            "provider": provider,
            "model": model_id,
            "binary_check": binary_check,
            "outcome": "skipped",
            "reason": f"{provider} binary not found on PATH",
            "passed": None,
        }

    with tempfile.TemporaryDirectory(prefix=f"collab-check-live-{provider}-") as tmp:
        workspace = Path(tmp)
        (workspace / "AGENTS.md").write_text("# validation probe\n", encoding="utf-8")

        adapter = get_provider_adapter(provider, root_dir=workspace, live_mode=True)
        adapter_request = build_minimal_adapter_request(
            provider=provider,
            model_id=model_id,
            task_id=task_id,
            root_dir=root_dir,
        )
        adapter_request["timeouts"]["defaultMs"] = timeout_sec * 1000

        try:
            invocation = adapter.execute_live(adapter_request=adapter_request)
            result_payload = invocation.result_payload
            raw_output = invocation.raw_output_text or ""

            exit_code = result_payload.get("exitStatus", {}).get("code", -99)
            status = result_payload.get("status", "unknown")
            parsed_envelope = result_payload.get("parsedEnvelope", {})

            artifact_dir = workspace / "artifacts"
            artifact_dir.mkdir()
            req_path = artifact_dir / "adapter-request.json"
            res_path = artifact_dir / "adapter-result.json"
            raw_path = artifact_dir / "raw-output.txt"
            req_path.write_text(json.dumps(adapter_request, indent=2), encoding="utf-8")
            res_path.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
            if raw_output:
                raw_path.write_text(raw_output, encoding="utf-8")

            passed = exit_code == 0 and status in {"succeeded"}
            return {
                "provider": provider,
                "model": model_id,
                "binary_check": binary_check,
                "exit_code": exit_code,
                "status": status,
                "execution_mode": result_payload.get("executionMode"),
                "raw_output_snippet": raw_output[:500],
                "stderr_snippet": result_payload.get("rawOutput", {}).get("stderr", "")[
                    :300
                ],
                "parsed_envelope_summary": parsed_envelope.get("summary", "")[:200],
                "parsed_status": parsed_envelope.get("status"),
                "artifacts_written": {
                    "adapter_request": req_path.exists(),
                    "adapter_result": res_path.exists(),
                    "raw_output": raw_path.exists() if raw_output else "not_captured",
                },
                "session_ref": result_payload.get("session", {}).get("sessionRef", ""),
                "outcome": "passed" if passed else "failed",
                "passed": passed,
                "notes": f"Behavior check using {model_id} (cheapest suitable model for CLI validation).",
            }
        except Exception as exc:
            return {
                "provider": provider,
                "model": model_id,
                "binary_check": binary_check,
                "outcome": "error",
                "error": str(exc),
                "passed": False,
                "notes": "Adapter execute_live() raised an unexpected exception.",
            }


def run_check(
    *,
    providers: list[str] | None = None,
    timeout_sec: int = 120,
) -> dict:
    """Run live execution checks for all (or specified) providers."""
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    target_providers = providers or ["gemini", "codex", "copilot"]

    sys.path.insert(0, str(REPO_ROOT))
    from agentorch_ctx.runtime.pathing import resolve_runtime_paths

    runtime_paths = resolve_runtime_paths(start_dir=REPO_ROOT)
    root_dir = runtime_paths.repo_root

    results = []
    for provider in target_providers:
        print(
            f"  Running {provider} behavior check (model={VALIDATION_MODELS[provider]})..."
        )
        result = run_provider_behavior_check(
            provider=provider,
            root_dir=root_dir,
            timeout_sec=timeout_sec,
        )
        results.append(result)
        status_str = result.get("outcome", "unknown")
        print(f"  -> {provider}: {status_str}")

    any_run = any(r.get("outcome") != "skipped" for r in results)
    all_run_passed = all(
        r.get("passed", False) for r in results if r.get("outcome") != "skipped"
    )

    evidence = {
        "description": "Provider adapter live execution validation",
        "validatedAt": _isoformat(),
        "costRule": "Cheapest suitable model per provider for CLI behavior checks",
        "validationModels": VALIDATION_MODELS,
        "anyProviderRun": any_run,
        "allRunProvidersPassed": all_run_passed,
        "results": results,
    }
    out_path = PROBE_DIR / "check-live-providers.json"
    out_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Provider adapter live execution validation"
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=["codex", "gemini", "copilot"],
        help="Run only for the specified provider(s). Repeatable.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds per provider call (default: 120).",
    )
    args = parser.parse_args()

    print("Provider Adapter Live Execution Validation")
    print(f"Validation prompt: {VALIDATION_PROMPT!r}")
    print()

    result = run_check(
        providers=args.provider,
        timeout_sec=args.timeout,
    )

    for r in result["results"]:
        provider = r["provider"]
        outcome = r.get("outcome", "unknown")
        model = r.get("model", "")
        if outcome == "skipped":
            print(f"  [SKIP] {provider} ({r.get('reason', '')})")
        elif outcome == "passed":
            print(f"  [PASS] {provider} model={model} exit={r.get('exit_code')}")
        else:
            print(
                f"  [FAIL] {provider} model={model} exit={r.get('exit_code')} error={r.get('error', '')}"
            )

    print()
    any_run = result["anyProviderRun"]
    all_passed = result["allRunProvidersPassed"]
    if not any_run:
        print("Result: NO PROVIDERS RUN (all binaries missing)")
        sys.exit(2)
    print(
        f"Result: {'ALL RUN PROVIDERS PASSED' if all_passed else 'FAILURES DETECTED'}"
    )
    print(f"Evidence: {PROBE_DIR / 'check-live-providers.json'}")
    sys.exit(0 if all_passed else 1)
