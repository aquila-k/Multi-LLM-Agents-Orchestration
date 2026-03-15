from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentorch_ctx.runtime.capabilities import CapabilityRecord, CapabilityRegistry
from agentorch_ctx.runtime.pathing import resolve_config_root
from agentorch_ctx.runtime.routing import RoutingEngine

CONFIG_SCHEMA_VERSION = "1.0.0"
MERGE_ORDER = [
    "provider defaults",
    "agent defaults",
    "phase default",
    "strategy default",
    "step override",
    "user provider defaults (fill only)",
]


@dataclass(frozen=True)
class RuntimeConfigBundle:
    config_root: Path
    providers: dict[str, dict[str, Any]]
    provider_refs: dict[str, Path]
    agents: dict[str, dict[str, Any]]
    agent_refs: dict[str, Path]
    strategies: dict[str, dict[str, Any]]
    strategy_refs: dict[str, Path]
    phases: dict[str, dict[str, Any]]
    phase_refs: dict[str, Path]
    policies: dict[str, dict[str, Any]]
    policy_refs: dict[str, Path]
    user_config: dict[str, Any]
    verified_fact_refs: list[Path]
    provider_market_fact_refs: list[Path]
    environment_signature_ref: Path | None
    validation_debt_ref: Path | None


@dataclass(frozen=True)
class RuntimeConfigResolution:
    bundle: RuntimeConfigBundle
    resolved_config: dict[str, Any]
    routing_result: dict[str, Any]


@dataclass(frozen=True)
class ContextsConfig:
    enabled: bool = True
    byte_budget: int = 16000
    write_timeout: int = 10
    auto_init: bool = True
    writeback_mode: str = "structured"


def load_config_bundle(root_dir: Path) -> RuntimeConfigBundle:
    cfg_root = resolve_config_root(root_dir.resolve())
    config_root = cfg_root / "configs"
    internal_root = config_root / "internal"
    facts_root = cfg_root / "facts"

    providers, provider_refs = _load_indexed_objects(
        internal_root / "providers", key_field="provider"
    )
    agents, agent_refs = _load_collection_objects(
        internal_root / "routing", collection_key="profiles", key_field="profile"
    )
    strategies, strategy_refs = _load_collection_objects(
        internal_root / "strategies",
        collection_key="strategies",
        key_field="strategyId",
    )
    phases, phase_refs = _load_indexed_objects(
        internal_root / "phases", key_field="phase"
    )
    policies, policy_refs = _load_indexed_objects(
        internal_root / "policies", key_field="policy"
    )
    routing_policy_path = internal_root / "routing" / "policy.json"
    if routing_policy_path.exists():
        routing_policy = json.loads(routing_policy_path.read_text(encoding="utf-8"))
        policies[routing_policy["policy"]] = routing_policy
        policy_refs[routing_policy["policy"]] = routing_policy_path
    user_config = _load_user_config(cfg_root)

    verified_fact_refs = sorted((facts_root / "verified-facts").glob("*.json"))
    provider_market_fact_refs = sorted(
        (facts_root / "provider-market-facts").glob("*.json")
    )
    environment_signature_ref = _optional_path(
        facts_root / "environment-signature.json"
    )
    validation_debt_ref = _optional_path(facts_root / "validation-debt.json")

    return RuntimeConfigBundle(
        config_root=cfg_root,
        providers=providers,
        provider_refs=provider_refs,
        agents=agents,
        agent_refs=agent_refs,
        strategies=strategies,
        strategy_refs=strategy_refs,
        phases=phases,
        phase_refs=phase_refs,
        policies=policies,
        policy_refs=policy_refs,
        user_config=user_config,
        verified_fact_refs=verified_fact_refs,
        provider_market_fact_refs=provider_market_fact_refs,
        environment_signature_ref=environment_signature_ref,
        validation_debt_ref=validation_debt_ref,
    )


def resolve_runtime_config(
    *,
    root_dir: Path,
    request: dict[str, Any],
    agent_profile_override: str | None = None,
    step_id: str | None = None,
) -> RuntimeConfigResolution:
    bundle = load_config_bundle(root_dir)
    contexts_config = _resolve_contexts_config(request, bundle)
    phase = _resolve_phase(request)
    phase_config = bundle.phases[phase]
    signals = _derive_task_signals(request)
    strategy_resolution = _resolve_strategy(
        bundle=bundle, phase=phase, request=request, signals=signals
    )
    budget_profile = _resolve_budget_profile(bundle=bundle, phase=phase)

    required_capabilities = list(phase_config.get("requiredCapabilities", []))
    if request["workflow_intent"] == "resume":
        required_capabilities.extend(phase_config.get("resumeRequiredCapabilities", []))

    selected_strategy = strategy_resolution["selected"]
    selected_step_id = _resolve_selected_step_id(
        selected_strategy=selected_strategy,
        requested_step=step_id or request.get("selectors", {}).get("step"),
    )
    effective_agent_profile = agent_profile_override or _resolve_strategy_agent_profile(
        selected_strategy=selected_strategy,
        step_id=selected_step_id,
    )

    if effective_agent_profile and effective_agent_profile in bundle.agents:
        selected_candidate = _build_candidate_from_profile(
            bundle=bundle, profile_name=effective_agent_profile
        )
        routing_trace_data = {
            "selected": selected_candidate,
            "candidate_scores": [],
            "hard_filters_applied": [],
            "reason_codes": [f"agent_profile_override:{effective_agent_profile}"],
            "confidence": 1.0,
            "stop_and_confirm": False,
            "budget_state": "ok",
        }
        routing_trace = _StaticRoutingTrace(routing_trace_data)
    else:
        capability_registry = _build_capability_registry(bundle)
        routing_engine = RoutingEngine(
            capability_registry, policy=bundle.policies.get("routing", {})
        )
        provider_candidates = _build_provider_candidates(bundle=bundle, phase=phase)
        routing_trace = routing_engine.route(
            phase=phase,
            candidates=provider_candidates,
            metrics=_build_default_metrics(request, phase),
            required_capabilities=required_capabilities,
            budget=_to_budget_gate_input(budget_profile),
        )

    selected_candidate = _apply_user_overrides(
        bundle=bundle,
        phase=phase,
        strategy_id=selected_strategy["strategyId"],
        step_id=selected_step_id,
        candidate=routing_trace.selected,
    )
    selected_provider = (
        bundle.providers.get(selected_candidate["provider"])
        if selected_candidate
        else None
    )
    selected_model_ref = selected_candidate["modelRef"] if selected_candidate else None
    selected_model = (
        _resolve_model_value(selected_provider, selected_model_ref)
        if selected_provider and selected_model_ref
        else None
    )

    resolved_config = {
        "schemaVersion": CONFIG_SCHEMA_VERSION,
        "taskId": request["task_id"],
        "workspaceRoot": str(root_dir.resolve()),
        "configRoot": str(bundle.config_root),
        "phase": phase,
        "mergeOrder": MERGE_ORDER,
        "signals": signals,
        "strategy": {
            "strategyId": strategy_resolution["selected"]["strategyId"],
            "selectedStrategyId": strategy_resolution["selected"]["strategyId"],
            "slug": strategy_resolution["selected"].get("slug"),
            "selectionSource": strategy_resolution["source"],
            "strategyRef": str(bundle.strategy_refs[selected_strategy["strategyId"]]),
            "steps": selected_strategy.get("steps", []),
            "preferredOutputMode": selected_strategy.get(
                "preferredOutputMode", request["output"]["preferred_mode"]
            ),
            "estimatedCallsMin": selected_strategy.get("estimatedCallsMin"),
            "estimatedCallsDefault": selected_strategy.get("estimatedCallsDefault"),
            "estimatedCallsMax": selected_strategy.get("estimatedCallsMax"),
            "estimatedCallsPerLoop": selected_strategy.get("estimatedCallsPerLoop"),
            "maxRepairLoops": selected_strategy.get("maxRepairLoops", 0),
            "requiresBudgetConfirm": selected_strategy.get(
                "requiresBudgetConfirm", False
            ),
        },
        "provider": {
            "provider": selected_candidate["provider"] if selected_candidate else None,
            "profile": selected_candidate["profile"] if selected_candidate else None,
            "providerRef": (
                str(bundle.provider_refs[selected_candidate["provider"]])
                if selected_candidate
                else None
            ),
            "agentRef": (
                str(bundle.agent_refs[selected_candidate["profile"]])
                if selected_candidate
                and selected_candidate["profile"] in bundle.agent_refs
                else None
            ),
            "command": selected_candidate["command"] if selected_candidate else None,
            "modelRef": selected_model_ref,
            "model": selected_model,
            "options": selected_candidate["options"] if selected_candidate else {},
            "supportedOptionKeys": (
                selected_candidate["supportedOptionKeys"] if selected_candidate else []
            ),
            "timeoutDefaults": (
                selected_candidate["timeoutDefaults"] if selected_candidate else {}
            ),
            "retryDefaults": (
                selected_candidate["retryDefaults"] if selected_candidate else {}
            ),
        },
        "phaseConfig": {
            "phase": phase,
            "phaseRef": str(bundle.phase_refs[phase]),
            "defaultStrategyId": phase_config.get("defaultStrategyId"),
            "autoAdvanceDefault": phase_config.get("autoAdvanceDefault", False),
            "allowWithHarden": phase_config.get("allowWithHarden", False),
            "composition": phase_config.get("composition", {}),
        },
        "phaseOptions": {
            "withHarden": bool(
                request.get("phase_options", {}).get("with_harden", False)
            ),
            "autoAdvance": bool(
                request.get("phase_options", {}).get("auto_advance", False)
            ),
            "budgetProfileRef": request.get("phase_options", {}).get(
                "budget_profile_ref", "budget-bootstrap"
            ),
        },
        "budgetProfile": budget_profile,
        "policyRefs": {key: str(path) for key, path in bundle.policy_refs.items()},
        "facts": {
            "verifiedFactRefs": [str(path) for path in bundle.verified_fact_refs],
            "providerMarketFactRefs": [
                str(path) for path in bundle.provider_market_fact_refs
            ],
            "environmentSignatureRef": (
                str(bundle.environment_signature_ref)
                if bundle.environment_signature_ref
                else None
            ),
            "validationDebtRef": (
                str(bundle.validation_debt_ref) if bundle.validation_debt_ref else None
            ),
        },
        "capabilityRequirements": required_capabilities,
        "effectiveOutputContract": {
            "allowedAutoApplyModes": ["patch", "create_file"],
            "fullFileRequiresApproval": True,
        },
        "contexts_config": {
            "enabled": contexts_config.enabled,
            "byte_budget": contexts_config.byte_budget,
            "write_timeout": contexts_config.write_timeout,
            "auto_init": contexts_config.auto_init,
            "writeback_mode": contexts_config.writeback_mode,
        },
    }

    routing_result = {
        "schemaVersion": CONFIG_SCHEMA_VERSION,
        "phase": phase,
        "selectedStrategyId": selected_strategy["strategyId"],
        "selectedProvider": (
            selected_candidate["provider"] if selected_candidate else None
        ),
        "selectedModel": selected_model_ref,
        "selectedProfile": (
            selected_candidate["profile"] if selected_candidate else None
        ),
        "candidateScores": {
            "strategies": strategy_resolution["candidates"],
            "providers": routing_trace.candidate_scores,
        },
        "hardFiltersApplied": routing_trace.hard_filters_applied,
        "reasonCodes": [
            *strategy_resolution["reasonCodes"],
            *routing_trace.reason_codes,
        ],
        "confidence": routing_trace.confidence,
        "requiresHumanConfirm": routing_trace.stop_and_confirm
        or selected_candidate is None,
        "budgetState": routing_trace.budget_state,
    }

    return RuntimeConfigResolution(
        bundle=bundle,
        resolved_config=resolved_config,
        routing_result=routing_result,
    )


def _resolve_contexts_config(
    request: dict[str, Any],
    bundle: RuntimeConfigBundle,  # noqa: ARG001
) -> ContextsConfig:
    """Resolve contexts config from env, task config and defaults."""
    enabled_env = os.environ.get("CONTEXTS_ENABLED")
    if enabled_env == "0":
        return ContextsConfig(enabled=False)

    byte_budget_env = os.environ.get("CONTEXTS_BYTE_BUDGET")
    task_contexts = request.get("contexts", {})
    if not isinstance(task_contexts, dict):
        task_contexts = {}

    enabled = bool(task_contexts.get("enabled", True))
    byte_budget = int(byte_budget_env or task_contexts.get("byte_budget", 16000))
    write_timeout = int(
        os.environ.get(
            "CONTEXTS_WRITE_TIMEOUT",
            task_contexts.get("write_timeout", 10),
        )
    )
    auto_init = bool(task_contexts.get("auto_init", True))
    writeback_mode = str(task_contexts.get("writeback_mode", "structured"))

    return ContextsConfig(
        enabled=enabled,
        byte_budget=byte_budget,
        write_timeout=write_timeout,
        auto_init=auto_init,
        writeback_mode=writeback_mode,
    )


def _load_indexed_objects(
    directory: Path, *, key_field: str
) -> tuple[dict[str, dict[str, Any]], dict[str, Path]]:
    items: dict[str, dict[str, Any]] = {}
    refs: dict[str, Path] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        key = payload[key_field]
        items[key] = payload
        refs[key] = path
    return items, refs


def _load_collection_objects(
    directory: Path, *, collection_key: str, key_field: str
) -> tuple[dict[str, dict[str, Any]], dict[str, Path]]:
    items: dict[str, dict[str, Any]] = {}
    refs: dict[str, Path] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get(collection_key, []):
            key = item[key_field]
            items[key] = item
            refs[key] = path
    return items, refs


def _optional_path(path: Path) -> Path | None:
    return path if path.exists() else None


def _load_user_config(root_dir: Path) -> dict[str, Any]:
    config_root = root_dir / "configs" if (root_dir / "configs").exists() else root_dir
    user_root = config_root / "user"
    phase_names = ("plan", "impl", "review", "harden")
    providers_path = user_root / "providers.json"

    providers: dict[str, Any] = {}
    if providers_path.exists():
        payload = json.loads(providers_path.read_text(encoding="utf-8"))
        providers = payload.get("providers", {})

    phase_configs: dict[str, dict[str, Any]] = {}
    phase_refs: dict[str, Path] = {}
    strategy_enabled: dict[str, dict[str, bool]] = {}
    for phase in phase_names:
        path = user_root / f"{phase}.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        phase_configs[phase] = payload
        phase_refs[phase] = path
        strategy_enabled[phase] = {
            strategy_id: bool(strategy_config.get("enabled", True))
            for strategy_id, strategy_config in payload.get("strategies", {}).items()
            if isinstance(strategy_config, dict)
        }

    return {
        "providers": providers,
        "phases": phase_configs,
        "strategyEnabled": strategy_enabled,
        "refs": {
            "providers": providers_path if providers_path.exists() else None,
            "phases": phase_refs,
        },
    }


def _expand_presets(phase_config: dict[str, Any]) -> dict[str, Any]:
    if not phase_config:
        return {}

    def resolve_step(step_config: Any, presets: dict[str, Any]) -> Any:
        if not isinstance(step_config, dict):
            return step_config
        preset_name = step_config.get("$preset")
        base = dict(presets.get(preset_name, {})) if preset_name else {}
        overrides = {
            key: value for key, value in step_config.items() if key != "$preset"
        }
        return {**base, **overrides}

    expanded = _clone_payload(phase_config)
    presets = expanded.pop("$presets", {})

    if "default" in expanded:
        expanded["default"] = resolve_step(expanded["default"], presets)

    strategies = expanded.get("strategies", {})
    for strategy_id, strategy_config in list(strategies.items()):
        if not isinstance(strategy_config, dict):
            continue
        expanded_strategy = dict(strategy_config)
        if "default" in strategy_config:
            expanded_strategy["default"] = resolve_step(
                strategy_config["default"], presets
            )
        if "steps" in strategy_config:
            expanded_strategy["steps"] = {
                step_name: resolve_step(step_config, presets)
                for step_name, step_config in strategy_config["steps"].items()
            }
        strategies[strategy_id] = expanded_strategy
    return expanded


def is_strategy_enabled(
    bundle: RuntimeConfigBundle, phase: str, strategy_id: str
) -> bool:
    return (
        bundle.user_config.get("strategyEnabled", {})
        .get(phase, {})
        .get(strategy_id, True)
    )


def _build_capability_registry(bundle: RuntimeConfigBundle) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for path in bundle.verified_fact_refs:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload.get("records", []):
            registry.register(
                CapabilityRecord(
                    provider=record["provider"],
                    capability_key=record["capabilityId"],
                    state=record["state"],
                    source=record["evidenceSource"],
                    environment_signature={},
                )
            )
    return registry


def _resolve_phase(request: dict[str, Any]) -> str:
    selector_phase = request.get("selectors", {}).get("phase")
    if selector_phase:
        return selector_phase
    workflow_intent = request["workflow_intent"]
    return "plan" if workflow_intent == "resume" else workflow_intent


def _derive_task_signals(request: dict[str, Any]) -> dict[str, Any]:
    target_paths = request.get("targets", {}).get("paths", [])
    target_globs = request.get("targets", {}).get("globs", [])
    summary = request.get("summary", "")
    summary_lower = summary.lower()
    return {
        "targetCount": len(target_paths) + len(target_globs),
        "hasGlobs": bool(target_globs),
        "operationsRequired": bool(
            request.get("output", {}).get("operations_required")
        ),
        "workflowIntent": request.get("workflow_intent"),
        "summaryLength": len(summary),
        "ambiguityHints": [
            hint
            for hint in ("question", "clarify", "unclear", "ambigu")
            if hint in summary_lower
        ],
        "releaseHints": [
            hint
            for hint in ("release", "architecture", "security", "migration")
            if hint in summary_lower
        ],
        "hardConstraintCount": len(request.get("constraints", {}).get("hard", [])),
    }


def _resolve_selected_step_id(
    *, selected_strategy: dict[str, Any], requested_step: str | None
) -> str | None:
    if not requested_step:
        return None
    for step in selected_strategy.get("steps", []):
        if step.get("id") == requested_step:
            return requested_step
    return None


def _resolve_strategy_agent_profile(
    *, selected_strategy: dict[str, Any], step_id: str | None
) -> str | None:
    if not step_id:
        return None
    for step in selected_strategy.get("steps", []):
        if step.get("id") == step_id:
            profile = step.get("agentProfile")
            return str(profile) if profile else None
    return None


def _resolve_strategy(
    *,
    bundle: RuntimeConfigBundle,
    phase: str,
    request: dict[str, Any],
    signals: dict[str, Any],
) -> dict[str, Any]:
    explicit_strategy = request.get("selectors", {}).get("strategy")
    phase_strategies = sorted(
        (
            strategy
            for strategy in bundle.strategies.values()
            if strategy.get("phase") == phase
            and strategy.get("enabled", True)
            and is_strategy_enabled(bundle, phase, strategy["strategyId"])
        ),
        key=lambda item: item["strategyId"],
    )
    if not phase_strategies:
        raise ValueError(f"No enabled strategies available for phase '{phase}'")
    phase_default = bundle.phases[phase]["defaultStrategyId"]

    if (
        explicit_strategy
        and explicit_strategy in bundle.strategies
        and bundle.strategies[explicit_strategy].get("phase") == phase
        and is_strategy_enabled(bundle, phase, explicit_strategy)
    ):
        candidates = [
            {
                "strategyId": strategy["strategyId"],
                "score": 100 if strategy["strategyId"] == explicit_strategy else 0,
                "selected": strategy["strategyId"] == explicit_strategy,
                "reasons": (
                    ["explicit_selector"]
                    if strategy["strategyId"] == explicit_strategy
                    else []
                ),
            }
            for strategy in phase_strategies
        ]
        return {
            "selected": bundle.strategies[explicit_strategy],
            "source": "explicit_selector",
            "candidates": candidates,
            "reasonCodes": ["strategy_source:explicit_selector"],
        }

    scored_candidates: list[tuple[int, dict[str, Any], list[str]]] = []
    for strategy in phase_strategies:
        score, reasons = _score_strategy_candidate(
            strategy=strategy,
            phase=phase,
            phase_default=phase_default,
            signals=signals,
        )
        scored_candidates.append((score, strategy, reasons))
    scored_candidates.sort(
        key=lambda item: (item[0], item[1]["strategyId"]), reverse=True
    )
    selected = scored_candidates[0][1]
    selected_source = (
        "phase_default" if selected["strategyId"] == phase_default else "rubric"
    )
    reason_codes = [f"strategy_source:{selected_source}"]
    if explicit_strategy and explicit_strategy not in bundle.strategies:
        reason_codes.append("strategy_override_unavailable")
    elif explicit_strategy and not is_strategy_enabled(
        bundle, phase, explicit_strategy
    ):
        reason_codes.append("strategy_override_disabled")
    candidates = [
        {
            "strategyId": strategy["strategyId"],
            "score": score,
            "selected": strategy["strategyId"] == selected["strategyId"],
            "reasons": reasons,
        }
        for score, strategy, reasons in scored_candidates
    ]
    return {
        "selected": selected,
        "source": selected_source,
        "candidates": candidates,
        "reasonCodes": reason_codes,
    }


def _score_strategy_candidate(
    *,
    strategy: dict[str, Any],
    phase: str,
    phase_default: str,
    signals: dict[str, Any],
) -> tuple[int, list[str]]:
    strategy_id = strategy["strategyId"]
    score = 60 if strategy_id == phase_default else 40
    reasons = ["phase_default"] if strategy_id == phase_default else []
    target_count = int(signals["targetCount"])
    has_globs = bool(signals["hasGlobs"])
    summary_length = int(signals["summaryLength"])
    has_ambiguity = bool(signals["ambiguityHints"])
    has_release_hints = bool(signals["releaseHints"])
    operations_required = bool(signals["operationsRequired"])
    hard_constraint_count = int(signals["hardConstraintCount"])

    if phase == "plan":
        if strategy_id == "COLLAB_PLAN_QUESTIONS_ONLY" and has_ambiguity:
            score += 35
            reasons.append("ambiguity_signal")
        if (
            strategy_id == "COLLAB_PLAN_MINIMAL"
            and target_count <= 1
            and not has_globs
            and summary_length < 80
            and hard_constraint_count == 0
        ):
            score += 20
            reasons.append("narrow_scope")
        if strategy_id == "COLLAB_PLAN_FULL":
            score += 10
            reasons.append("default_nontrivial_plan")
        if strategy_id == "COLLAB_PLAN_THOROUGH" and (
            target_count >= 4 or has_globs or has_release_hints
        ):
            score += 35
            reasons.append("broad_or_architectural_scope")
    elif phase == "impl":
        if strategy_id == "COLLAB_IMPL_PATCH_FIRST":
            score += 10
            reasons.append("bounded_patch_default")
        if strategy_id == "COLLAB_IMPL_BATCH_SHOT" and _request_prefers_full_output(
            strategy, operations_required
        ):
            score += 30
            reasons.append("batch_generation_fit")
        if strategy_id == "COLLAB_IMPL_SPEC_PATCH" and hard_constraint_count >= 2:
            score += 20
            reasons.append("acceptance_boundary_signal")
        if strategy_id == "COLLAB_IMPL_FILE_BY_FILE" and (
            target_count >= 4 or has_globs
        ):
            score += 30
            reasons.append("broad_generation_scope")
        if strategy_id == "COLLAB_IMPL_SHIELD_FIX" and has_release_hints:
            score += 10
            reasons.append("remediation_signal")
    elif phase == "review":
        if strategy_id == "COLLAB_REVIEW_PRESET_STANDARD":
            score += 10
            reasons.append("default_review_path")
        if strategy_id == "COLLAB_REVIEW_PRESET_LITE" and target_count <= 1:
            score += 15
            reasons.append("localized_change")
        if strategy_id == "COLLAB_REVIEW_PRESET_STRICT" and (
            target_count >= 4 or has_release_hints
        ):
            score += 25
            reasons.append("high_risk_or_release_scope")
        if strategy_id == "COLLAB_REVIEW_MODE_B" and target_count == 0:
            score += 20
            reasons.append("standalone_review_signal")
    elif phase == "harden":
        if strategy_id == "COLLAB_HARDEN_STANDARD":
            score += 10
            reasons.append("default_hardening_path")
        if strategy_id == "COLLAB_HARDEN_LITE" and target_count <= 1:
            score += 15
            reasons.append("routine_change")
        if strategy_id == "COLLAB_HARDEN_FULL" and (
            target_count >= 4 or has_release_hints
        ):
            score += 25
            reasons.append("release_grade_scope")
    return score, reasons


def _request_prefers_full_output(
    strategy: dict[str, Any], operations_required: bool
) -> bool:
    preferred = strategy.get("preferredOutputMode")
    return preferred in {"full_file", "create_file"} and operations_required


def _resolve_budget_profile(
    *, bundle: RuntimeConfigBundle, phase: str
) -> dict[str, Any]:
    budget_policy = bundle.policies.get("budget", {})
    default_profile = json.loads(
        json.dumps(budget_policy.get("defaultBudgetProfile", {}))
    )
    default_profile["phaseCap"] = default_profile.get("phaseCaps", {}).get(phase)
    default_profile["estimatedNextCost"] = 0.0
    return default_profile


def _build_provider_candidates(
    *, bundle: RuntimeConfigBundle, phase: str
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for profile_name in bundle.phases[phase].get("candidateProfiles", []):
        profile = bundle.agents[profile_name]
        provider = bundle.providers[profile["provider"]]
        options = dict(provider.get("defaultOptions", {}))
        options.update(profile.get("defaultOptions", {}))
        capabilities = dict(provider.get("declaredCapabilities", {}))
        capabilities.update(profile.get("declaredCapabilities", {}))
        candidates.append(
            {
                "provider": provider["provider"],
                "profile": profile["profile"],
                "modelRef": profile.get(
                    "defaultModelRef", provider.get("defaultModelRef")
                ),
                "command": provider["command"],
                "options": options,
                "supportedOptionKeys": _supported_option_keys(provider),
                "timeoutDefaults": provider.get("timeoutDefaults", {}),
                "retryDefaults": provider.get("retryDefaults", {}),
                "capabilities": capabilities,
                "scores": profile.get("routingScores", {}),
                "penalties": profile.get("penalties", {}),
                "estimated_cost": profile.get("estimatedCostUnits", 0.0),
                "selectionNotes": profile.get("selectionNotes", []),
            }
        )
    return candidates


def _build_default_metrics(request: dict[str, Any], phase: str) -> dict[str, Any]:
    target_count = len(request.get("targets", {}).get("paths", [])) + len(
        request.get("targets", {}).get("globs", [])
    )
    return {
        "capabilityFit": 3,
        "contextFit": 4 if target_count <= 3 else 3,
        "toolFit": 4 if phase == "impl" else 3,
        "sessionFit": 5 if request["workflow_intent"] == "resume" else 3,
        "outputDisciplineFit": (
            4 if request.get("output", {}).get("operations_required") else 3
        ),
        "evidenceFit": 4 if phase in {"plan", "review", "harden"} else 3,
        "reliabilityFit": 4,
        "costFit": 3,
        "latencyFit": 3,
        "mergeFit": 4 if phase in {"review", "harden"} else 3,
    }


def _to_budget_gate_input(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "taskSoftCap": profile.get("taskSoftCap"),
        "taskHardCap": profile.get("taskHardCap"),
        "estimatedNextCost": profile.get("estimatedNextCost", 0.0),
    }


def _build_candidate_from_profile(
    *, bundle: RuntimeConfigBundle, profile_name: str
) -> dict[str, Any]:
    profile = bundle.agents[profile_name]
    provider = bundle.providers[profile["provider"]]
    options = dict(provider.get("defaultOptions", {}))
    options.update(profile.get("defaultOptions", {}))
    capabilities = dict(provider.get("declaredCapabilities", {}))
    capabilities.update(profile.get("declaredCapabilities", {}))
    return {
        "provider": provider["provider"],
        "profile": profile["profile"],
        "modelRef": profile.get("defaultModelRef", provider.get("defaultModelRef")),
        "command": provider["command"],
        "options": options,
        "supportedOptionKeys": _supported_option_keys(provider),
        "timeoutDefaults": provider.get("timeoutDefaults", {}),
        "retryDefaults": provider.get("retryDefaults", {}),
        "capabilities": capabilities,
        "scores": profile.get("routingScores", {}),
        "penalties": profile.get("penalties", {}),
        "estimated_cost": profile.get("estimatedCostUnits", 0.0),
        "selectionNotes": profile.get("selectionNotes", []),
    }


def _apply_user_overrides(
    *,
    bundle: RuntimeConfigBundle,
    phase: str,
    strategy_id: str,
    step_id: str | None,
    candidate: dict[str, Any] | None,
) -> dict[str, Any] | None:
    resolved = _clone_payload(candidate) if candidate else None
    if step_id:
        step_override = _resolve_user_step_override(
            bundle=bundle,
            phase=phase,
            strategy_id=strategy_id,
            step_id=step_id,
        )
        override_provider = step_override.get("provider")
        if override_provider:
            resolved = _build_candidate_for_provider(
                bundle=bundle, phase=phase, provider_name=str(override_provider)
            )

        if resolved is None:
            return None

        override_model = step_override.get("model")
        if override_model:
            resolved["modelRef"] = str(override_model)

        override_effort = step_override.get("effort")
        if override_effort:
            resolved.setdefault("options", {})
            resolved["options"]["reasoningEffort"] = override_effort

        if override_effort and not _provider_supports_reasoning_effort(
            bundle.providers.get(resolved["provider"], {})
        ):
            print(
                (
                    f"WARNING: Step {step_id}: effort={override_effort} ignored "
                    f"(provider '{resolved['provider']}' does not support reasoningEffort)"
                ),
                file=sys.stderr,
            )
            resolved.setdefault("options", {}).pop("reasoningEffort", None)

    if resolved is None:
        return None

    return _apply_user_provider_defaults(bundle=bundle, candidate=resolved)


def _apply_user_provider_defaults(
    *, bundle: RuntimeConfigBundle, candidate: dict[str, Any]
) -> dict[str, Any]:
    resolved = _clone_payload(candidate)
    provider_name = resolved["provider"]
    provider_defaults = bundle.user_config.get("providers", {}).get(provider_name, {})
    if not provider_defaults:
        return resolved

    override_model = provider_defaults.get("model")
    if override_model and not resolved.get("modelRef"):
        resolved["modelRef"] = str(override_model)

    override_effort = provider_defaults.get("effort")
    if (
        override_effort
        and _provider_supports_reasoning_effort(bundle.providers.get(provider_name, {}))
        and not resolved.setdefault("options", {}).get("reasoningEffort")
    ):
        resolved["options"]["reasoningEffort"] = override_effort

    return resolved


def _resolve_user_step_override(
    *,
    bundle: RuntimeConfigBundle,
    phase: str,
    strategy_id: str,
    step_id: str,
) -> dict[str, Any]:
    raw_phase_config = bundle.user_config.get("phases", {}).get(phase, {})
    if not raw_phase_config:
        return {}

    phase_config = _expand_presets(raw_phase_config)
    merged = dict(phase_config.get("default", {}))
    strategy_config = phase_config.get("strategies", {}).get(strategy_id, {})
    merged.update(strategy_config.get("default", {}))
    merged.update(strategy_config.get("steps", {}).get(step_id, {}))
    return _clone_payload(merged) if merged else {}


def _build_candidate_for_provider(
    *, bundle: RuntimeConfigBundle, phase: str, provider_name: str
) -> dict[str, Any]:
    for profile_name in bundle.phases.get(phase, {}).get("candidateProfiles", []):
        profile = bundle.agents.get(profile_name)
        if profile and profile.get("provider") == provider_name:
            return _build_candidate_from_profile(
                bundle=bundle, profile_name=profile_name
            )

    provider = bundle.providers[provider_name]
    return {
        "provider": provider["provider"],
        "profile": None,
        "modelRef": provider.get("defaultModelRef"),
        "command": provider["command"],
        "options": dict(provider.get("defaultOptions", {})),
        "supportedOptionKeys": _supported_option_keys(provider),
        "timeoutDefaults": provider.get("timeoutDefaults", {}),
        "retryDefaults": provider.get("retryDefaults", {}),
        "capabilities": dict(provider.get("declaredCapabilities", {})),
        "scores": {},
        "penalties": {},
        "estimated_cost": 0.0,
        "selectionNotes": ["user_provider_override"],
    }


def _resolve_model_value(
    provider_config: dict[str, Any], model_ref_or_alias: str | None
) -> str | None:
    if not model_ref_or_alias:
        return None
    return provider_config.get("modelAliases", {}).get(
        model_ref_or_alias, model_ref_or_alias
    )


def _provider_supports_reasoning_effort(provider_config: dict[str, Any]) -> bool:
    return "reasoningEffort" in provider_config.get("supportedOptionKeys", [])


def _supported_option_keys(provider_config: dict[str, Any]) -> list[str]:
    return list(provider_config.get("supportedOptionKeys", []))


def _clone_payload(payload: Any) -> Any:
    return json.loads(json.dumps(payload))


class _StaticRoutingTrace:
    """Minimal routing trace wrapper for agent_profile_override path."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def selected(self) -> dict[str, Any] | None:
        return self._data["selected"]

    @property
    def candidate_scores(self) -> list[Any]:
        return self._data.get("candidate_scores", [])

    @property
    def hard_filters_applied(self) -> list[Any]:
        return self._data.get("hard_filters_applied", [])

    @property
    def reason_codes(self) -> list[str]:
        return self._data.get("reason_codes", [])

    @property
    def confidence(self) -> float:
        return float(self._data.get("confidence", 1.0))

    @property
    def stop_and_confirm(self) -> bool:
        return bool(self._data.get("stop_and_confirm", False))

    @property
    def budget_state(self) -> str:
        return str(self._data.get("budget_state", ""))
