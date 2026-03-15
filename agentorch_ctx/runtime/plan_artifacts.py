"""
Extract canonical plan/checklist/deferred-items artifacts from a plan phase response.

The extractor looks for structured JSON blocks in the normalized response content.
If no structured blocks are found, it synthesizes minimal artifacts from the summary.
"""

from __future__ import annotations

import re
from typing import Any


def extract_plan_artifacts(
    *,
    task_id: str,
    step_id: str,
    normalized: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """
    Returns (plan_artifact, checklist_artifact, deferred_items_artifact_or_None).
    deferred_items is None if there are no deferred items.
    """
    content = _get_content(normalized)

    plan = _extract_plan(
        task_id=task_id, step_id=step_id, content=content, normalized=normalized
    )
    checklist = _extract_checklist(
        task_id=task_id, step_id=step_id, content=content, normalized=normalized
    )
    deferred = _extract_deferred(
        task_id=task_id, step_id=step_id, content=content, normalized=normalized
    )

    return plan, checklist, deferred


def _get_content(normalized: dict[str, Any]) -> str:
    payload = normalized.get("payload", normalized)
    for key in ("content", "summary", "text", "output"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    report = payload.get("report")
    if isinstance(report, str) and report.strip():
        return report
    reports = payload.get("reports")
    if isinstance(reports, list):
        for item in reports:
            if not isinstance(item, dict):
                continue
            for key in ("summary", "content", "text", "report"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    return val
    return str(payload)


def _extract_plan(
    *, task_id: str, step_id: str, content: str, normalized: dict[str, Any]
) -> dict[str, Any]:
    """Try to extract a structured plan from JSON blocks in content, fallback to minimal."""
    json_block = _find_json_block(
        content, keys=["implementationSteps", "implementation_steps", "steps"]
    )
    if json_block:
        steps = (
            json_block.get("implementationSteps")
            or json_block.get("implementation_steps")
            or json_block.get("steps", [])
        )
        normalized_steps = []
        for i, s in enumerate(steps if isinstance(steps, list) else []):
            if isinstance(s, str):
                normalized_steps.append(
                    {
                        "id": f"S{i + 1:02d}",
                        "description": s,
                        "targetFiles": [],
                        "dependsOn": [],
                    }
                )
            elif isinstance(s, dict):
                normalized_steps.append(
                    {
                        "id": s.get("id", f"S{i + 1:02d}"),
                        "description": s.get("description", s.get("desc", str(s))),
                        "targetFiles": s.get("targetFiles", s.get("files", [])),
                        "dependsOn": s.get("dependsOn", s.get("depends_on", [])),
                    }
                )
        summary = json_block.get("summary", "")
        target_paths = json_block.get("targetPaths", json_block.get("target_paths", []))
        constraints = json_block.get("constraints", {})
        ambiguities_resolved = json_block.get(
            "ambiguitiesResolved", json_block.get("ambiguities_resolved", [])
        )
        ambiguities_deferred = json_block.get(
            "ambiguitiesDeferred", json_block.get("ambiguities_deferred", [])
        )
    else:
        # Synthesize from text content
        normalized_steps = _synthesize_steps_from_text(content)
        summary = _first_line(content)
        target_paths = _extract_file_paths(content)
        constraints = {}
        ambiguities_resolved = []
        ambiguities_deferred = []

    if not summary:
        payload = normalized.get("payload", normalized)
        summary = payload.get("summary", "")[:240] if isinstance(payload, dict) else ""

    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "phase": "plan",
        "stepId": step_id,
        "summary": summary,
        "implementationSteps": normalized_steps,
        "targetPaths": target_paths,
        "constraints": constraints,
        "ambiguitiesResolved": ambiguities_resolved,
        "ambiguitiesDeferred": ambiguities_deferred,
        "extractedFrom": f"{task_id}:plan:{step_id}",
    }


def _extract_checklist(
    *, task_id: str, step_id: str, content: str, normalized: dict[str, Any]
) -> dict[str, Any]:
    """Try to extract checklist items from content."""
    json_block = _find_json_block(
        content, keys=["checklist", "items", "checklistItems"]
    )
    if json_block:
        raw_items = (
            json_block.get("checklist")
            or json_block.get("checklistItems")
            or json_block.get("items", [])
        )
    else:
        raw_items = _extract_checklist_from_text(content)

    items = []
    for i, item in enumerate(raw_items if isinstance(raw_items, list) else []):
        if isinstance(item, str):
            items.append(
                {
                    "id": f"C{i + 1:03d}",
                    "description": item,
                    "category": "impl",
                    "status": "pending",
                    "targetFiles": [],
                    "dependsOn": [],
                }
            )
        elif isinstance(item, dict):
            items.append(
                {
                    "id": item.get("id", f"C{i + 1:03d}"),
                    "description": item.get("description", item.get("desc", str(item))),
                    "category": item.get("category", "impl"),
                    "status": item.get("status", "pending"),
                    "targetFiles": item.get("targetFiles", item.get("files", [])),
                    "dependsOn": item.get("dependsOn", item.get("depends_on", [])),
                }
            )

    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "phase": "plan",
        "items": items,
        "extractedFrom": f"{task_id}:plan:{step_id}",
    }


def _extract_deferred(
    *, task_id: str, step_id: str, content: str, normalized: dict[str, Any]
) -> dict[str, Any] | None:
    """Extract deferred items. Returns None if none found."""
    json_block = _find_json_block(
        content, keys=["deferredItems", "deferred_items", "deferred"]
    )
    raw_items: list[Any] = []
    if json_block:
        raw_items = (
            json_block.get("deferredItems")
            or json_block.get("deferred_items")
            or json_block.get("deferred", [])
        )
    else:
        raw_items = _extract_deferred_from_text(content)

    if not raw_items:
        return None

    items = []
    for i, item in enumerate(raw_items if isinstance(raw_items, list) else []):
        if isinstance(item, str):
            items.append(
                {
                    "id": f"D{i + 1:03d}",
                    "description": item,
                    "reason": "deferred from plan",
                    "impact": "",
                    "expectedResolutionPhase": "",
                }
            )
        elif isinstance(item, dict):
            items.append(
                {
                    "id": item.get("id", f"D{i + 1:03d}"),
                    "description": item.get("description", item.get("desc", str(item))),
                    "reason": item.get("reason", "deferred from plan"),
                    "impact": item.get("impact", ""),
                    "expectedResolutionPhase": item.get(
                        "expectedResolutionPhase", item.get("phase", "")
                    ),
                }
            )

    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "phase": "plan",
        "items": items,
        "extractedFrom": f"{task_id}:plan:{step_id}",
    }


def _find_json_block(content: str, keys: list[str]) -> dict[str, Any] | None:
    """Find the first JSON code block in content that contains one of the given keys."""
    for pattern in [r"```json\s*(\{[\s\S]*?\})\s*```", r"```\s*(\{[\s\S]*?\})\s*```"]:
        for match in re.finditer(pattern, content, re.MULTILINE):
            try:
                import json

                obj = json.loads(match.group(1))
                if isinstance(obj, dict) and any(k in obj for k in keys):
                    return obj
            except (ValueError, TypeError):
                continue
    return None


def _synthesize_steps_from_text(content: str) -> list[dict[str, Any]]:
    """Extract numbered list items as implementation steps."""
    steps = []
    for i, line in enumerate(content.splitlines()):
        line = line.strip()
        if re.match(r"^\d+[\.\)]\s+", line):
            desc = re.sub(r"^\d+[\.\)]\s+", "", line).strip()
            if desc:
                steps.append(
                    {
                        "id": f"S{i + 1:02d}",
                        "description": desc,
                        "targetFiles": [],
                        "dependsOn": [],
                    }
                )
    return steps[:20]  # cap at 20


def _extract_checklist_from_text(content: str) -> list[str]:
    """Extract markdown checkbox items as checklist."""
    items = []
    for line in content.splitlines():
        line = line.strip()
        match = re.match(r"^[-*]\s*\[[ xX]\]\s+(.+)$", line)
        if match:
            items.append(match.group(1).strip())
    return items[:50]


def _extract_deferred_from_text(content: str) -> list[str]:
    """Look for deferred/TODO/carry-over sections."""
    items = []
    in_deferred_section = False
    for line in content.splitlines():
        lower = line.lower().strip()
        if re.search(r"deferred|carry.?over|持ち越し|次タスク|todo", lower):
            in_deferred_section = True
            continue
        if in_deferred_section:
            if re.match(r"^#+\s", line):
                in_deferred_section = False
                continue
            match = re.match(r"^[-*\d.]+\s+(.+)$", line.strip())
            if match:
                items.append(match.group(1).strip())
    return items[:20]


def _extract_file_paths(content: str) -> list[str]:
    """Extract file paths mentioned in content."""
    paths = []
    for match in re.finditer(
        r"(?:^|\s)([a-zA-Z_][a-zA-Z0-9_/.-]*/[a-zA-Z0-9_/.-]+\.(?:py|json|yaml|yml|md|ts|js|sh))",
        content,
    ):
        path = match.group(1).strip()
        if path not in paths:
            paths.append(path)
    return paths[:30]


def _first_line(content: str) -> str:
    for line in content.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:240]
    return ""


def validate_plan_artifacts(
    plan: dict[str, Any],
    checklist: dict[str, Any],
    deferred: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    """
    Validate that plan and checklist artifacts are non-empty and contain scope refs.

    Returns (is_valid, list_of_failure_reasons).
    An empty list of failure reasons means the artifacts are valid.
    """
    failures: list[str] = []

    # Checklist must have at least one item
    checklist_items = checklist.get("items")
    if not checklist_items:
        failures.append(
            "checklist.items is empty or missing — plan phase produced no checklist"
        )

    # Plan must have at least one implementation step
    impl_steps = plan.get("implementationSteps")
    if not impl_steps:
        failures.append(
            "plan.implementationSteps is empty or missing — plan phase produced no steps"
        )

    # Plan must have some scope reference: either targetPaths or constraints
    has_target_paths = bool(plan.get("targetPaths"))
    has_constraints = bool(plan.get("constraints"))
    if not has_target_paths and not has_constraints:
        failures.append(
            "plan.targetPaths and plan.constraints are both empty — no scope defined"
        )

    return (len(failures) == 0, failures)


def plan_artifact_scope_summary(
    plan: dict[str, Any],
    checklist: dict[str, Any],
    deferred: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return a compact scope summary suitable for attaching to a manifest.

    Keys:
      totalSteps           — number of implementationSteps in plan
      totalChecklistItems  — number of items in checklist
      hasTargetPaths       — whether plan.targetPaths is non-empty
      hasDeferredItems     — whether a deferred artifact with items was provided
    """
    total_steps = len(plan.get("implementationSteps") or [])
    total_checklist_items = len(checklist.get("items") or [])
    has_target_paths = bool(plan.get("targetPaths"))
    has_deferred_items = bool(deferred and deferred.get("items"))

    return {
        "totalSteps": total_steps,
        "totalChecklistItems": total_checklist_items,
        "hasTargetPaths": has_target_paths,
        "hasDeferredItems": has_deferred_items,
    }
