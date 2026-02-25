#!/usr/bin/env bash
# resolve_routing.sh — Delegated routing resolver (delegated-auto mode)
#
# Usage:
#   resolve_routing.sh --phase <plan|impl|review> \
#     --task-root <dir> \
#     [--out <file>] \
#     [--model <model>] \
#     [--effort <low|medium|high>] \
#     [--timeout-ms <ms>]
#
# Output file (default: <task-root>/state/routing-decision.<phase>.json):
#   V2 routing_result schema + backward-compatible <phase>_profile key.
#
# Always exits 0 — falls back to safe defaults if codex call or JSON parsing fails.
#
# Exit codes:
#   0  Decision written (may be fallback default)
#   2  Bad arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || { cd "${SCRIPT_DIR}/../.." && pwd; })"
WRAPPER_DIR="${SCRIPT_DIR}/wrappers"

source "${SCRIPT_DIR}/lib/log.sh"

PHASE=""
TASK_ROOT=""
OUT_FILE=""
MODEL="gpt-5.3-codex"
EFFORT="medium"
TIMEOUT_MS=120000

while [[ $# -gt 0 ]]; do
	case "$1" in
	--phase)
		PHASE="$2"
		shift 2
		;;
	--task-root)
		TASK_ROOT="$2"
		shift 2
		;;
	--out)
		OUT_FILE="$2"
		shift 2
		;;
	--model)
		MODEL="$2"
		shift 2
		;;
	--effort)
		EFFORT="$2"
		shift 2
		;;
	--timeout-ms)
		TIMEOUT_MS="$2"
		shift 2
		;;
	*)
		log_warn "resolve_routing: unknown argument: $1"
		shift
		;;
	esac
done

if [[ -z $PHASE || -z $TASK_ROOT ]]; then
	log_error "resolve_routing: --phase and --task-root are required"
	exit 2
fi

case "$PHASE" in
plan | impl | review) ;;
*)
	log_error "resolve_routing: --phase must be plan|impl|review (got: ${PHASE})"
	exit 2
	;;
esac

STATE_DIR="${TASK_ROOT}/state"
WORK_DIR="${STATE_DIR}/routing-work"
ROUTING_INPUT_FILE="${STATE_DIR}/routing_input.json"
OPTION_DECISION_FILE="${STATE_DIR}/routing_decision.${PHASE}.option_decision.json"

if [[ -z $OUT_FILE ]]; then
	OUT_FILE="${STATE_DIR}/routing-decision.${PHASE}.json"
fi

TEMPLATE_FILE="${REPO_ROOT}/prompts-src/routing/${PHASE}-route-decider.md"
if [[ ! -f $TEMPLATE_FILE ]]; then
	log_error "resolve_routing: routing template not found: ${TEMPLATE_FILE}"
	exit 2
fi

write_option_decision() {
	local routing_file="$1"
	python3 - "$OPTION_DECISION_FILE" "$TASK_ROOT" "$PHASE" "$routing_file" <<'PYEOF'
import datetime
import json
import os
import sys

option_file, task_root, phase, routing_file = sys.argv[1:]

with open(routing_file, "r", encoding="utf-8") as f:
    routing = json.load(f)

run_id = ""
if isinstance(routing, dict):
    run_id = str(routing.get("run_id", "")).strip()

state_file = os.path.join(task_root, "state", "session_state.json")
if not run_id and os.path.isfile(state_file):
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        latest = state.get("latest_run_id")
        if isinstance(latest, str) and latest.strip():
            run_id = latest.strip()
    except Exception:
        pass

if not run_id:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-{phase}"

decision = str(routing.get("stop_action", "CONTINUE"))
selected = routing.get("selected_method_ids")
if not isinstance(selected, list):
    selected = []
selected = [str(item) for item in selected if str(item).strip()]
reason_codes = routing.get("reason_codes")
if not isinstance(reason_codes, list):
    reason_codes = []
reason_codes = [str(item) for item in reason_codes if str(item).strip()]
confidence = str(routing.get("confidence", "medium"))

payload = {
    "run_id": run_id,
    "phase": phase,
    "decision": decision,
    "selected_method_ids": selected,
    "confidence": confidence,
    "reason_codes": reason_codes,
    "recorded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

os.makedirs(os.path.dirname(os.path.abspath(option_file)), exist_ok=True)
partial = option_file + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, option_file)

print(decision)
PYEOF
}

# ── Fallback writer ────────────────────────────────────────────────────────────

write_fallback() {
	local reason="$1"
	log_warn "resolve_routing: falling back to default for phase=${PHASE} (${reason})"
	python3 - "$OUT_FILE" "$PHASE" "$reason" "$ROUTING_INPUT_FILE" <<'PYEOF'
import datetime
import json
import os
import sys

out_file, phase, reason, routing_input_file = sys.argv[1:]

defaults = {
    "plan": {
        "profile_key": "plan_profile",
        "profile_value": "standard",
        "method_id": "PLAN-PROFILE-STANDARD",
    },
    "impl": {
        "profile_key": "impl_profile",
        "profile_value": "safe_impl",
        "method_id": "IMPL-PROFILE-SAFE",
    },
    "review": {
        "profile_key": "review_profile",
        "profile_value": "review_cross",
        "method_id": "REVIEW-PROFILE-CROSS",
    },
}

spec = defaults[phase]
default_signals = {
    "impact_surface": "medium",
    "change_shape": "mixed",
    "scope_spread": "local",
    "requirement_clarity": "medium",
    "verification_load": "medium",
}
if os.path.isfile(routing_input_file):
    try:
        with open(routing_input_file, "r", encoding="utf-8") as f:
            routing_input = json.load(f)
        src = routing_input.get("signals") or {}
        for key in default_signals:
            value = src.get(key)
            if isinstance(value, str) and value:
                default_signals[key] = value
    except Exception:
        pass

payload = {
    "phase": phase,
    "selected_method_ids": [spec["method_id"]],
    "step_agent_model_map": {},
    "alternatives": {
        "accepted": [spec["method_id"]],
        "rejected": [],
    },
    "signals": default_signals,
    "reasoning": ["fallback_default"],
    "confidence": "low",
    "requires_human_confirm": False,
    "web_research_policy": {"mode": "off"},
    "reason_codes": ["ROUTING_FALLBACK"],
    "stop_action": "STOP_AND_CONFIRM" if default_signals.get("impact_surface") == "high" else "CONTINUE",
    "_fallback_reason": reason,
    "resolved_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
if payload["stop_action"] == "STOP_AND_CONFIRM":
    payload["requires_human_confirm"] = True
payload[spec["profile_key"]] = spec["profile_value"]

os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
partial = out_file + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, out_file)
PYEOF
	local decision_action=""
	decision_action="$(write_option_decision "$OUT_FILE")" || true
	if [[ $decision_action == "STOP_AND_CONFIRM" ]]; then
		log_warn "resolve_routing: STOP_AND_CONFIRM raised by fallback policy for phase=${PHASE}"
	fi
}

generate_routing_input() {
	python3 - "$PHASE" "$TASK_ROOT" "$ROUTING_INPUT_FILE" <<'PYEOF'
import json
import os
import re
import sys

phase, task_root, out_file = sys.argv[1:]

pf = os.path.join(task_root, "plan", "preflight.md")
plan_file = os.path.join(task_root, "plan", "final-plan.md")
if not os.path.isfile(plan_file):
    alt = os.path.join(task_root, "plan", "final.md")
    if os.path.isfile(alt):
        plan_file = alt

parts = []
for path in (pf, plan_file):
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            parts.append(f.read())
text = "\n".join(parts).lower()

signals = {
    "impact_surface": "medium",
    "change_shape": "mixed",
    "scope_spread": "local",
    "requirement_clarity": "medium",
    "verification_load": "medium",
    "rollback_readiness": "medium",
    "time_cost_pressure": "medium",
    "freshness_need": "medium",
    "external_authority_need": "medium",
    "version_sensitivity": "medium",
    "security_advisory_need": "medium",
    "known_source_availability": "medium",
    "search_risk": "medium",
}

if text:
    high_impact_markers = [
        "public api", "breaking change", "auth", "authentication", "authorization",
        "permission", "database", "schema", "migration", "security", "critical path"
    ]
    low_impact_markers = [
        "docs only", "documentation only", "readme only", "typo", "comment only",
        "formatting only"
    ]
    if any(marker in text for marker in high_impact_markers):
        signals["impact_surface"] = "high"
    elif any(marker in text for marker in low_impact_markers):
        signals["impact_surface"] = "low"

    has_new = any(marker in text for marker in ["new file", "create", "add new", "from scratch", "greenfield"])
    has_edit = any(marker in text for marker in ["edit", "update", "modify", "patch", "fix", "existing"])
    if has_new and has_edit:
        signals["change_shape"] = "mixed"
    elif has_new:
        signals["change_shape"] = "new"
    elif has_edit:
        signals["change_shape"] = "edit"

    if any(marker in text for marker in ["cross-module", "cross module", "across modules", "multiple files", "cross-cutting"]):
        signals["scope_spread"] = "cross_module"

    if any(marker in text for marker in ["tbd", "unknown", "unclear", "to be decided", "missing details"]):
        signals["requirement_clarity"] = "low"
    elif any(marker in text for marker in ["acceptance criteria", "definition of done", "must", "shall"]):
        signals["requirement_clarity"] = "high"

    if any(marker in text for marker in ["integration test", "e2e", "end-to-end", "load test", "security test"]):
        signals["verification_load"] = "high"
    elif any(marker in text for marker in low_impact_markers):
        signals["verification_load"] = "low"

    if "rollback plan" in text:
        signals["rollback_readiness"] = "high"
    elif "irreversible" in text or "one-way migration" in text:
        signals["rollback_readiness"] = "low"

    if "urgent" in text or "timebox" in text or "deadline" in text:
        signals["time_cost_pressure"] = "high"
    elif "no rush" in text:
        signals["time_cost_pressure"] = "low"

    if "latest" in text or "today" in text or "breaking release" in text:
        signals["freshness_need"] = "high"
    else:
        signals["freshness_need"] = "low"

    if "official docs" in text or "external api" in text:
        signals["external_authority_need"] = "high"
    else:
        signals["external_authority_need"] = "low"

    if re.search(r"v\d+|version", text):
        signals["version_sensitivity"] = "high"
    else:
        signals["version_sensitivity"] = "low"

    if "cve" in text or "security advisory" in text:
        signals["security_advisory_need"] = "high"
    else:
        signals["security_advisory_need"] = "low"

    if "existing codebase" in text or "current repo" in text:
        signals["known_source_availability"] = "high"
    else:
        signals["known_source_availability"] = "medium"

    if "unverified source" in text or "forum" in text:
        signals["search_risk"] = "high"
    else:
        signals["search_risk"] = "low"

payload = {
    "phase": phase,
    "signals": signals,
    "constraints": {
        "scope_lock": "strict",
        "must_use_methods": [],
        "forbidden_methods": [],
        "allow_web_research": False,
    },
    "available_tools": ["codex", "gemini", "copilot"],
}

os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
partial = out_file + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, out_file)
PYEOF
}

# ── Context assembler ──────────────────────────────────────────────────────────

assemble_context() {
	local out="$1"

	{
		echo "### Task Root"
		echo ""
		echo "  ${TASK_ROOT}"
		echo ""

		if [[ -s $ROUTING_INPUT_FILE ]]; then
			echo "### Routing Input (JSON)"
			echo ""
			cat "$ROUTING_INPUT_FILE"
			echo ""
		fi

		# Preflight
		local pf="${TASK_ROOT}/plan/preflight.md"
		if [[ -s $pf ]]; then
			echo "### Preflight (first 80 lines)"
			echo ""
			head -80 "$pf"
			echo ""
		fi

		# Final plan
		local plan_file="${TASK_ROOT}/plan/final-plan.md"
		[[ -s $plan_file ]] || plan_file="${TASK_ROOT}/plan/final.md"
		if [[ -s $plan_file ]]; then
			echo "### Final Plan (first 150 lines)"
			echo ""
			head -150 "$plan_file"
			echo ""
		fi

		# Impl summary (for review phase)
		if [[ $PHASE == "review" ]]; then
			local summ="${TASK_ROOT}/impl/outputs/_summary.md"
			if [[ -s $summ ]]; then
				echo "### Implementation Summary"
				echo ""
				head -60 "$summ"
				echo ""
			fi
			local rr="${TASK_ROOT}/impl/routing_result.json"
			if [[ -s $rr ]]; then
				echo "### Impl Routing Result"
				echo ""
				cat "$rr"
				echo ""
			fi
		fi

	} >"$out"
}

# ── Main ───────────────────────────────────────────────────────────────────────

mkdir -p "$WORK_DIR"

if ! generate_routing_input; then
	log_warn "resolve_routing: failed to derive routing_input.json, using defaults"
	python3 - "$PHASE" "$ROUTING_INPUT_FILE" <<'PYEOF'
import json
import os
import sys

phase, out_file = sys.argv[1:]
payload = {
    "phase": phase,
    "signals": {
        "impact_surface": "medium",
        "change_shape": "mixed",
        "scope_spread": "local",
        "requirement_clarity": "medium",
        "verification_load": "medium",
        "rollback_readiness": "medium",
        "time_cost_pressure": "medium",
        "freshness_need": "medium",
        "external_authority_need": "medium",
        "version_sensitivity": "medium",
        "security_advisory_need": "medium",
        "known_source_availability": "medium",
        "search_risk": "medium",
    },
    "constraints": {
        "scope_lock": "strict",
        "must_use_methods": [],
        "forbidden_methods": [],
        "allow_web_research": False,
    },
    "available_tools": ["codex", "gemini", "copilot"],
}
os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
partial = out_file + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, out_file)
PYEOF
fi

CONTEXT_FILE="${WORK_DIR}/${PHASE}-context.md"
assemble_context "$CONTEXT_FILE"

PROMPT_FILE="${WORK_DIR}/${PHASE}-prompt.md"
{
	cat "$TEMPLATE_FILE"
	echo ""
	echo "## V2 Routing Contract Override (S02)"
	echo ""
	echo "Return one JSON object with this schema and required fields:"
	echo ""
	echo '{'
	echo '  "phase": "plan|impl|review",'
	echo '  "selected_method_ids": ["..."],'
	echo '  "step_agent_model_map": {},'
	echo '  "alternatives": {"accepted": ["..."], "rejected": [{"method_id":"...","reason":"..."}]},'
	echo '  "signals": {"impact_surface":"low|medium|high","change_shape":"edit|new|mixed","scope_spread":"local|cross_module","requirement_clarity":"low|medium|high","verification_load":"low|medium|high"},'
	echo '  "reasoning": ["..."],'
	echo '  "confidence": "high|medium|low",'
	echo '  "requires_human_confirm": false,'
	echo '  "web_research_policy": {"mode":"off"},'
	echo '  "reason_codes": [],'
	echo '  "stop_action": "CONTINUE|STOP_AND_CONFIRM"'
	echo '}'
	echo ""
	echo "Use routing_input.json as primary evidence for signals and constraints."
	echo ""
	cat "$CONTEXT_FILE"
} >"$PROMPT_FILE"

RAW_OUT="${WORK_DIR}/${PHASE}-raw.out"
ERR_FILE_W="${WORK_DIR}/${PHASE}-err.log"

log_info "resolve_routing: invoking codex for phase=${PHASE}"

WRAPPER_EXIT=0
"${WRAPPER_DIR}/run_codex.sh" \
	--prompt-file "$PROMPT_FILE" \
	--out "$RAW_OUT" \
	--err "$ERR_FILE_W" \
	--model "$MODEL" \
	--effort "$EFFORT" \
	--timeout-ms "$TIMEOUT_MS" \
	--timeout-mode "wait_done" || WRAPPER_EXIT=$?

if [[ $WRAPPER_EXIT -ne 0 ]]; then
	write_fallback "codex_exit_${WRAPPER_EXIT}"
	exit 0
fi

if [[ ! -s $RAW_OUT ]]; then
	write_fallback "empty_output"
	exit 0
fi

# ── JSON extraction + validation ───────────────────────────────────────────────

EXTRACTED=$(
	python3 - "$RAW_OUT" "$PHASE" "$ROUTING_INPUT_FILE" <<'PYEOF'
import datetime
import json
import os
import sys

raw_file, phase, routing_input_file = sys.argv[1:]

PROFILE_SPEC = {
    "plan": {
        "profile_key": "plan_profile",
        "legacy_default": "standard",
        "method_default": "PLAN-PROFILE-STANDARD",
        "legacy_to_method": {"standard": "PLAN-PROFILE-STANDARD"},
        "method_to_legacy": {"PLAN-PROFILE-STANDARD": "standard"},
    },
    "impl": {
        "profile_key": "impl_profile",
        "legacy_default": "safe_impl",
        "method_default": "IMPL-PROFILE-SAFE",
        "legacy_to_method": {
            "safe_impl": "IMPL-PROFILE-SAFE",
            "one_shot_impl": "IMPL-PROFILE-ONE_SHOT",
            "design_only": "IMPL-PROFILE-DESIGN_ONLY",
        },
        "method_to_legacy": {
            "IMPL-PROFILE-SAFE": "safe_impl",
            "IMPL-PROFILE-ONE_SHOT": "one_shot_impl",
            "IMPL-PROFILE-DESIGN_ONLY": "design_only",
        },
    },
    "review": {
        "profile_key": "review_profile",
        "legacy_default": "review_cross",
        "method_default": "REVIEW-PROFILE-CROSS",
        "legacy_to_method": {
            "review_only": "REVIEW-PROFILE-ONLY",
            "review_cross": "REVIEW-PROFILE-CROSS",
            "post_impl_review": "REVIEW-PROFILE-POST_IMPL",
            "codex_only": "REVIEW-PROFILE-CODEX_ONLY",
        },
        "method_to_legacy": {
            "REVIEW-PROFILE-ONLY": "review_only",
            "REVIEW-PROFILE-CROSS": "review_cross",
            "REVIEW-PROFILE-POST_IMPL": "post_impl_review",
            "REVIEW-PROFILE-CODEX_ONLY": "codex_only",
        },
    },
}

SIGNAL_ALLOWED = {
    "impact_surface": {"low", "medium", "high"},
    "change_shape": {"edit", "new", "mixed"},
    "scope_spread": {"local", "cross_module"},
    "requirement_clarity": {"low", "medium", "high"},
    "verification_load": {"low", "medium", "high"},
}

def extract_first_json_object(text):
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None

def to_string_list(value):
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        s = str(item).strip()
        if s:
            out.append(s)
    return out

def convert_method_id(value, legacy_to_method):
    s = str(value).strip()
    if not s:
        return ""
    return legacy_to_method.get(s, s)

def normalize_rejected(value, legacy_to_method):
    out = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                method = convert_method_id(item.get("method_id", ""), legacy_to_method)
                if not method:
                    continue
                reason = str(item.get("reason", "not_selected")).strip() or "not_selected"
                out.append({"method_id": method, "reason": reason})
            else:
                method = convert_method_id(item, legacy_to_method)
                if method:
                    out.append({"method_id": method, "reason": "not_selected"})
    elif isinstance(value, dict):
        for k, v in value.items():
            method = convert_method_id(k, legacy_to_method)
            if method:
                reason = str(v).strip() or "not_selected"
                out.append({"method_id": method, "reason": reason})
    return out

with open(raw_file, "r", encoding="utf-8", errors="replace") as f:
    text = f.read()

source = extract_first_json_object(text)
if source is None:
    print("FAIL:NO_JSON")
    sys.exit(0)

spec = PROFILE_SPEC[phase]
legacy_to_method = spec["legacy_to_method"]
method_to_legacy = spec["method_to_legacy"]
incomplete = False

routing_input_signals = {
    "impact_surface": "medium",
    "change_shape": "mixed",
    "scope_spread": "local",
    "requirement_clarity": "medium",
    "verification_load": "medium",
}
if os.path.isfile(routing_input_file):
    try:
        with open(routing_input_file, "r", encoding="utf-8") as f:
            routing_input = json.load(f)
        src = routing_input.get("signals") or {}
        if isinstance(src, dict):
            for key in routing_input_signals:
                value = src.get(key)
                if isinstance(value, str) and value.strip():
                    routing_input_signals[key] = value.strip()
    except Exception:
        pass

selected_raw = source.get("selected_method_ids")
selected_method_ids = []
if isinstance(selected_raw, list):
    for item in selected_raw:
        method_id = convert_method_id(item, legacy_to_method)
        if method_id:
            selected_method_ids.append(method_id)
else:
    incomplete = True

if not selected_method_ids:
    profile_key = spec["profile_key"]
    legacy_profile = source.get(profile_key)
    if isinstance(legacy_profile, str) and legacy_profile.strip():
        selected_method_ids = [convert_method_id(legacy_profile, legacy_to_method)]
    else:
        selected_method_ids = [spec["method_default"]]
    incomplete = True

alternatives_src = source.get("alternatives")
accepted = []
rejected = []
if isinstance(alternatives_src, dict):
    accepted = [convert_method_id(item, legacy_to_method) for item in to_string_list(alternatives_src.get("accepted"))]
    accepted = [item for item in accepted if item]
    rejected = normalize_rejected(alternatives_src.get("rejected"), legacy_to_method)
elif isinstance(alternatives_src, list):
    rejected = normalize_rejected(alternatives_src, legacy_to_method)
    incomplete = True
else:
    incomplete = True

if not rejected:
    rejected = normalize_rejected(source.get("rejected"), legacy_to_method)
    if source.get("rejected") is not None and not rejected:
        incomplete = True

if not accepted:
    accepted = list(selected_method_ids)
    incomplete = True

reasoning = to_string_list(source.get("reasoning"))
if not reasoning:
    reasoning = ["fallback_default"]
    incomplete = True

confidence = str(source.get("confidence", "medium")).strip().lower()
if confidence not in {"high", "medium", "low"}:
    confidence = "medium"
    incomplete = True

reason_codes = to_string_list(source.get("reason_codes"))
if source.get("reason_codes") is not None and not isinstance(source.get("reason_codes"), list):
    incomplete = True

requires_human_confirm = bool(source.get("requires_human_confirm", False))
strict_evidence_violation = bool(source.get("strict_evidence_violation", False))

signals_in = source.get("signals")
signals = {}
if not isinstance(signals_in, dict):
    signals_in = {}
    incomplete = True
for key, allowed in SIGNAL_ALLOWED.items():
    candidate = signals_in.get(key, routing_input_signals[key])
    if not isinstance(candidate, str):
        candidate = routing_input_signals[key]
        incomplete = True
    candidate = candidate.strip()
    if candidate not in allowed:
        candidate = routing_input_signals[key]
        incomplete = True
    signals[key] = candidate

web_policy = source.get("web_research_policy")
if not isinstance(web_policy, dict) or not isinstance(web_policy.get("mode"), str):
    web_policy = {"mode": "off"}
    incomplete = True

stop_reasons = []
if signals.get("impact_surface") == "high" and confidence == "low":
    stop_reasons.append("impact_surface_high_confidence_low")
block_codes = [code for code in reason_codes if code.startswith("BLOCK")]
if block_codes:
    stop_reasons.extend([f"reason_code:{code}" for code in block_codes])
if strict_evidence_violation:
    stop_reasons.append("strict_evidence_violation")

stop_action = "STOP_AND_CONFIRM" if stop_reasons else "CONTINUE"
if stop_action == "STOP_AND_CONFIRM":
    requires_human_confirm = True

primary_method = selected_method_ids[0]
legacy_profile = method_to_legacy.get(primary_method, spec["legacy_default"])

result = {
    "phase": phase,
    "selected_method_ids": selected_method_ids,
    "step_agent_model_map": source.get("step_agent_model_map", {}) if isinstance(source.get("step_agent_model_map"), dict) else {},
    "alternatives": {"accepted": accepted, "rejected": rejected},
    "signals": signals,
    "reasoning": reasoning,
    "confidence": confidence,
    "requires_human_confirm": requires_human_confirm,
    "web_research_policy": web_policy,
    "reason_codes": reason_codes,
    "strict_evidence_violation": strict_evidence_violation,
    "stop_action": stop_action,
    "resolved_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

result[spec["profile_key"]] = legacy_profile

if not isinstance(source.get("step_agent_model_map"), dict):
    incomplete = True
if incomplete:
    result["_incomplete"] = True

print(json.dumps(result))
PYEOF
)

if [[ $EXTRACTED == FAIL:* ]]; then
	write_fallback "parse_error:${EXTRACTED}"
	exit 0
fi

# Write validated decision
python3 - "$OUT_FILE" "$EXTRACTED" <<'PYEOF'
import json
import os
import sys

out_file = sys.argv[1]
data = json.loads(sys.argv[2])

os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
partial = out_file + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(partial, out_file)
PYEOF

DECISION_ACTION="$(write_option_decision "$OUT_FILE")" || DECISION_ACTION=""
if [[ $DECISION_ACTION == "STOP_AND_CONFIRM" ]]; then
	log_warn "resolve_routing: STOP_AND_CONFIRM detected for phase=${PHASE}; review ${OPTION_DECISION_FILE}"
fi

log_ok "resolve_routing: phase=${PHASE} decision written → ${OUT_FILE}"
exit 0
