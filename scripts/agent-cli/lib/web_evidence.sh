#!/usr/bin/env bash
# web_evidence.sh — Strict validation for web-evidence.json
# Usage: source this file, then call:
#   web_evidence_reason_codes <evidence_json> [phase] [step]
#   web_evidence_validate <evidence_json> [phase] [step]
#
# Return codes for web_evidence_validate:
#   0 = pass
#   1 = STOP_AND_CONFIRM
#   2 = reject

web_evidence_reason_codes() {
	local evidence_json="${1-}"
	local phase="${2-}"
	local step="${3-}"

	if [[ -z $evidence_json || ! -f $evidence_json ]]; then
		echo "[]"
		return 0
	fi

	python3 - "$evidence_json" "$phase" "$step" <<'PYEOF'
import json
import sys

path, phase, step = sys.argv[1], sys.argv[2].strip().lower(), sys.argv[3].strip().lower()
codes = []

def add(code: str) -> None:
    if code not in codes:
        codes.append(code)

def is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False

def to_low(value) -> str:
    return value.strip().lower() if isinstance(value, str) else ""

def allows_web(phase_name: str, step_name: str) -> bool:
    if phase_name in {"review", "brief"}:
        return True
    joined = f"{phase_name} {step_name}".strip()
    return ("review" in joined) or ("brief" in joined)

def is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False

def is_high_risk(entry: dict) -> bool:
    for key in ("high_risk", "is_high_risk", "isHighRisk"):
        if is_truthy(entry.get(key)):
            return True

    severity_like_values = {"high", "critical", "severe", "major", "p0", "p1"}
    severity_keys = (
        "severity",
        "risk",
        "risk_level",
        "riskLevel",
        "finding_severity",
        "finding_risk",
        "impact_surface",
    )
    pools = [entry]
    nested = entry.get("finding")
    if isinstance(nested, dict):
        pools.append(nested)

    for pool in pools:
        for key in severity_keys:
            value = pool.get(key)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in severity_like_values:
                    return True
                if normalized.startswith("high") or "critical" in normalized:
                    return True
    return False

try:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
except Exception:
    add("WEB_EVIDENCE_MISSING")
    print(json.dumps(codes))
    raise SystemExit(0)

evidence = payload.get("evidence", [])
if not isinstance(evidence, list):
    evidence = []

if evidence and not allows_web(phase, step):
    add("WEB_SEARCH_NOT_ALLOWED_IN_STEP")

for item in evidence:
    if not isinstance(item, dict):
        continue
    decision = to_low(item.get("decision"))
    is_adopt = decision == "adopt"
    if not is_adopt:
        continue

    if is_blank(item.get("source_uri")):
        add("WEB_EVIDENCE_MISSING")
    if is_blank(item.get("retrieved_at")):
        add("WEB_EVIDENCE_MISSING")
    if is_blank(item.get("evidence_summary")):
        add("WEB_EVIDENCE_MISSING")

    if is_high_risk(item):
        if to_low(item.get("confidence")) == "low":
            add("WEB_SOURCE_UNTRUSTED")
        if to_low(item.get("source_type")) == "unknown":
            add("WEB_SOURCE_UNTRUSTED")

print(json.dumps(codes))
PYEOF
}

web_evidence_validate() {
	local evidence_json="${1-}"
	local phase="${2-}"
	local step="${3-}"

	if [[ -z $evidence_json || ! -f $evidence_json ]]; then
		return 0
	fi

	local reason_codes
	reason_codes="$(web_evidence_reason_codes "$evidence_json" "$phase" "$step" 2>/dev/null || echo '["WEB_EVIDENCE_MISSING"]')"

	python3 - "$reason_codes" <<'PYEOF'
import json
import sys

try:
    codes = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(2)

if not isinstance(codes, list):
    raise SystemExit(2)

codes = [str(code) for code in codes]
if "WEB_SOURCE_UNTRUSTED" in codes:
    raise SystemExit(1)
if "WEB_EVIDENCE_MISSING" in codes or "WEB_SEARCH_NOT_ALLOWED_IN_STEP" in codes:
    raise SystemExit(2)
raise SystemExit(0)
PYEOF
}
