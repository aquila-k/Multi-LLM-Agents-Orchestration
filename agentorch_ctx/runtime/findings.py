"""Severity model for review/harden findings."""

from __future__ import annotations

from typing import Any

SEVERITY_ORDER = ("Critical", "High", "Mid", "Low", "Nitpick")
BLOCKING_SEVERITIES = frozenset({"Critical", "High"})


def extract_findings(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract findings list from a normalized artifact payload."""
    payload = normalized.get("payload", normalized)
    if not isinstance(payload, dict):
        return []
    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        return []
    result: list[dict[str, Any]] = []
    for index, finding in enumerate(findings):
        if isinstance(finding, str):
            result.append(
                {
                    "id": f"F{index + 1:03d}",
                    "severity": "Mid",
                    "description": finding,
                    "fixable": False,
                    "iteration": 0,
                    "sourceRef": "",
                }
            )
            continue
        if not isinstance(finding, dict):
            continue
        extracted = {
            "id": finding.get("id", f"F{index + 1:03d}"),
            "severity": _normalize_severity(finding.get("severity", "Mid")),
            "description": finding.get(
                "description", finding.get("desc", str(finding))
            ),
            "fixable": bool(
                finding.get("fixable", finding.get("fix_available", False))
            ),
            "fix_operations": finding.get(
                "fix_operations", finding.get("operations", [])
            ),
            "location": finding.get("location", finding.get("file", "")),
            "iteration": _coerce_iteration(finding.get("iteration", 0)),
            "sourceRef": str(finding.get("sourceRef", "")),
        }
        if "status" in finding:
            extracted["status"] = finding["status"]
        result.append(extracted)
    return result


def merge_findings_across_iterations(
    iterations: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Merge findings from multiple iterations, marking missing findings as resolved."""
    merged: dict[str, dict[str, Any]] = {}
    previous_iteration_ids: set[str] = set()

    for iteration_index, findings in enumerate(iterations):
        current_iteration_ids: set[str] = set()
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            finding_id = str(finding.get("id", "")).strip()
            if not finding_id:
                continue
            current_iteration_ids.add(finding_id)
            merged[finding_id] = _finding_with_defaults(
                finding, default_iteration=iteration_index
            )

        for finding_id in previous_iteration_ids - current_iteration_ids:
            resolved = dict(merged[finding_id])
            resolved["status"] = "resolved"
            resolved["iteration"] = iteration_index
            merged[finding_id] = resolved

        previous_iteration_ids = current_iteration_ids

    return list(merged.values())


def has_blocking_findings(findings: list[dict[str, Any]]) -> bool:
    """True if any Critical or High findings remain."""
    return any(finding.get("severity") in BLOCKING_SEVERITIES for finding in findings)


def findings_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {severity: 0 for severity in SEVERITY_ORDER}
    for finding in findings:
        severity = finding.get("severity", "Mid")
        if severity in counts:
            counts[severity] += 1
    return {
        "total": len(findings),
        "by_severity": counts,
        "blocking_count": sum(
            counts.get(severity, 0) for severity in BLOCKING_SEVERITIES
        ),
    }


def _normalize_severity(raw: str) -> str:
    mapping = {
        "critical": "Critical",
        "crit": "Critical",
        "high": "High",
        "mid": "Mid",
        "medium": "Mid",
        "moderate": "Mid",
        "low": "Low",
        "nitpick": "Nitpick",
        "info": "Nitpick",
        "trivial": "Nitpick",
    }
    return mapping.get(str(raw).lower().strip(), "Mid")


def _coerce_iteration(raw: Any) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _finding_with_defaults(
    finding: dict[str, Any], *, default_iteration: int
) -> dict[str, Any]:
    merged = dict(finding)
    merged["iteration"] = _coerce_iteration(merged.get("iteration", default_iteration))
    merged["sourceRef"] = str(merged.get("sourceRef", ""))
    return merged
