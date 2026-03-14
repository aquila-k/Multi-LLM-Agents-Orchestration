from __future__ import annotations

import json
import re
from typing import Any

OUTPUT_MODES = {
    "patch",
    "create_file",
    "full_file",
    "mixed",
    "rename_file",
    "delete_file",
    "binary_patch",
    "report_only",
}


def parse_provider_output(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    if not text:
        return {
            "status": "failed",
            "mode": "report_only",
            "summary": "Provider returned empty output.",
            "warnings": [],
            "issues": [
                {
                    "code": "EMPTY_OUTPUT",
                    "message": "No provider output was captured.",
                    "severity": "error",
                }
            ],
            "payload": {},
            "meaningful": False,
            "parser_confidence": 0.0,
        }

    parsed_json = _extract_json_payload(text)
    if isinstance(parsed_json, dict):
        mode = parsed_json.get("mode", _infer_mode_from_payload(parsed_json))
        status = parsed_json.get("status", "success")
        return {
            "status": (
                status
                if status in {"success", "partial", "failed", "blocked"}
                else "partial"
            ),
            "mode": mode if mode in OUTPUT_MODES else "report_only",
            "summary": parsed_json.get("summary") or _first_line(text),
            "warnings": parsed_json.get("warnings", []),
            "issues": parsed_json.get("issues", []),
            "payload": parsed_json.get("payload", parsed_json),
            "meaningful": True,
            "parser_confidence": 0.98,
        }

    if _looks_like_patch(text):
        return {
            "status": "partial",
            "mode": "patch",
            "summary": "Patch-style output detected.",
            "warnings": [
                {
                    "code": "PATCH_TEXT_ONLY",
                    "message": "Raw patch output was captured without structured JSON.",
                    "severity": "warning",
                }
            ],
            "issues": [],
            "payload": {"patch": text},
            "meaningful": True,
            "parser_confidence": 0.7,
        }

    return {
        "status": "partial",
        "mode": "report_only",
        "summary": _first_line(text),
        "warnings": [
            {
                "code": "UNSTRUCTURED_OUTPUT",
                "message": "Provider output required fallback parsing.",
                "severity": "warning",
            }
        ],
        "issues": [],
        "payload": {"report": text},
        "meaningful": True,
        "parser_confidence": 0.45,
    }


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    for candidate in (text, *_fenced_json_blocks(text)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _fenced_json_blocks(text: str) -> list[str]:
    pattern = re.compile(r"```json\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    return [match.group(1).strip() for match in pattern.finditer(text)]


def _looks_like_patch(text: str) -> bool:
    return any(marker in text for marker in ("diff --git", "@@", "+++ ", "--- "))


def _infer_mode_from_payload(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("operations"), list):
        return "patch"
    if any(key in payload for key in ("findings", "recommendations", "reports")):
        return "report_only"
    return "report_only"


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:200]
    return "Unstructured provider output"
