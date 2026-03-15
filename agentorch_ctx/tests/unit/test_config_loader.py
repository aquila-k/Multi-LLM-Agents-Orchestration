from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agentorch_ctx.runtime.config_loader import (
    _expand_presets,
    load_config_bundle,
    resolve_runtime_config,
)
from agentorch_ctx.runtime.providers import get_provider_adapter


class ConfigLoaderUnitTest(unittest.TestCase):
    def test_loads_standalone_config_inventory_and_fact_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = load_config_bundle(Path(tmp))

        self.assertEqual(set(bundle.providers), {"codex", "gemini", "copilot"})
        self.assertEqual(len(bundle.strategies), 18)
        self.assertEqual(set(bundle.phases), {"plan", "impl", "review", "harden"})
        self.assertIn("routing", bundle.policies)
        self.assertIn("codex", bundle.user_config["providers"])
        self.assertEqual(
            bundle.provider_refs["codex"].relative_to(bundle.config_root).as_posix(),
            "configs/internal/providers/codex.json",
        )
        self.assertEqual(
            bundle.agent_refs["impl-copilot-primary"]
            .relative_to(bundle.config_root)
            .as_posix(),
            "configs/internal/routing/profiles.json",
        )
        self.assertEqual(
            bundle.strategy_refs["COLLAB_IMPL_PATCH_FIRST"]
            .relative_to(bundle.config_root)
            .as_posix(),
            "configs/internal/strategies/impl.json",
        )
        self.assertEqual(
            bundle.phase_refs["impl"].relative_to(bundle.config_root).as_posix(),
            "configs/internal/phases/impl.json",
        )
        self.assertEqual(
            bundle.policy_refs["approval"].relative_to(bundle.config_root).as_posix(),
            "configs/internal/policies/approval.json",
        )
        self.assertEqual(
            bundle.policy_refs["budget"].relative_to(bundle.config_root).as_posix(),
            "configs/internal/policies/budget.json",
        )
        self.assertEqual(
            bundle.policy_refs["routing"].relative_to(bundle.config_root).as_posix(),
            "configs/internal/routing/policy.json",
        )
        self.assertTrue(bundle.verified_fact_refs)
        self.assertIsNotNone(bundle.validation_debt_ref)

    def test_resolves_impl_request_from_collab_configs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = {
                "task_id": "task-impl",
                "workflow_intent": "impl",
                "summary": "Implement bounded patch for runtime",
                "targets": {
                    "paths": ["agentorch_ctx/runtime/task_entrypoint.py"],
                    "globs": [],
                },
                "constraints": {"hard": [], "soft": []},
                "output": {
                    "preferred_mode": "patch",
                    "allowed_modes": ["patch", "report_only"],
                    "operations_required": True,
                },
                "selectors": {},
            }

            resolution = resolve_runtime_config(root_dir=Path(tmp), request=request)

        self.assertEqual(
            resolution.resolved_config["strategy"]["selectedStrategyId"],
            "COLLAB_IMPL_PATCH_FIRST",
        )
        self.assertEqual(resolution.resolved_config["provider"]["provider"], "codex")
        self.assertEqual(
            resolution.resolved_config["provider"]["modelRef"], "codex-primary"
        )
        self.assertEqual(
            resolution.resolved_config["provider"]["options"]["reasoningEffort"],
            "medium",
        )
        self.assertEqual(
            resolution.resolved_config["provider"]["timeoutDefaults"]["defaultMs"],
            600000,
        )
        self.assertEqual(
            resolution.resolved_config["provider"]["retryDefaults"]["transient"], 3
        )
        self.assertTrue(resolution.resolved_config["facts"]["verifiedFactRefs"])
        self.assertIsNotNone(resolution.resolved_config["facts"]["validationDebtRef"])
        self.assertEqual(resolution.routing_result["selectedProvider"], "codex")
        self.assertFalse(resolution.routing_result["requiresHumanConfirm"])

    def test_resume_resolution_uses_imported_verified_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = {
                "task_id": "task-resume",
                "workflow_intent": "resume",
                "summary": "Resume blocked impl phase",
                "targets": {"paths": ["collab/runtime"], "globs": []},
                "constraints": {"hard": [], "soft": []},
                "output": {
                    "preferred_mode": "patch",
                    "allowed_modes": ["patch", "report_only"],
                    "operations_required": True,
                },
                "selectors": {
                    "phase": "impl",
                    "step": "apply",
                    "resume_from": "cursor-1",
                },
            }

            resolution = resolve_runtime_config(root_dir=Path(tmp), request=request)

        self.assertEqual(resolution.routing_result["selectedProvider"], "codex")
        self.assertIn(
            "high_impact_not_verified:session.resume",
            resolution.routing_result["hardFiltersApplied"],
        )

    def test_step_override_takes_precedence_over_user_provider_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = {
                "task_id": "task-plan-step",
                "workflow_intent": "plan",
                "summary": "Review architecture for a broad release migration",
                "targets": {
                    "paths": [
                        "agentorch_ctx/runtime/config_loader.py",
                        "agentorch_ctx/runtime/phase_runner.py",
                        "agentorch_ctx/runtime/runtime_coordinator.py",
                        "agentorch_ctx/runtime/providers/copilot.py",
                    ],
                    "globs": [],
                },
                "constraints": {"hard": [], "soft": []},
                "output": {
                    "preferred_mode": "report_only",
                    "allowed_modes": ["report_only"],
                    "operations_required": False,
                },
                "selectors": {"strategy": "COLLAB_PLAN_THOROUGH"},
            }

            resolution = resolve_runtime_config(
                root_dir=Path(tmp),
                request=request,
                step_id="P0_risk_scan",
            )

        self.assertEqual(resolution.resolved_config["provider"]["provider"], "codex")
        self.assertEqual(
            resolution.resolved_config["provider"]["modelRef"], "gpt-5.3-codex"
        )
        self.assertEqual(
            resolution.resolved_config["provider"]["options"]["reasoningEffort"],
            "high",
        )

    def test_expand_presets_merges_step_overrides(self) -> None:
        phase_config = {
            "version": 1,
            "phase": "impl",
            "$presets": {
                "fast": {
                    "provider": "codex",
                    "model": "gpt-5.1-codex-mini",
                    "effort": "low",
                },
                "quality": {
                    "provider": "codex",
                    "model": "gpt-5.3-codex",
                    "effort": "high",
                },
            },
            "default": {"$preset": "quality"},
            "strategies": {
                "COLLAB_IMPL_PATCH_FIRST": {
                    "default": {
                        "$preset": "fast",
                        "model": "gpt-5.3-codex",
                    },
                    "steps": {
                        "I0_analyze": {
                            "$preset": "fast",
                            "effort": "mid",
                        }
                    },
                }
            },
        }

        expanded = _expand_presets(phase_config)

        self.assertNotIn("$presets", expanded)
        self.assertEqual(
            expanded["default"],
            {
                "provider": "codex",
                "model": "gpt-5.3-codex",
                "effort": "high",
            },
        )
        self.assertEqual(
            expanded["strategies"]["COLLAB_IMPL_PATCH_FIRST"]["default"],
            {
                "provider": "codex",
                "model": "gpt-5.3-codex",
                "effort": "low",
            },
        )
        self.assertEqual(
            expanded["strategies"]["COLLAB_IMPL_PATCH_FIRST"]["steps"]["I0_analyze"],
            {
                "provider": "codex",
                "model": "gpt-5.1-codex-mini",
                "effort": "mid",
            },
        )
        self.assertEqual(_expand_presets(expanded), expanded)

    def test_phase_default_applies_to_unlisted_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support_root = self._clone_support_collab(root)
            impl_user_config = {
                "$schema": "../schemas/phase.schema.json",
                "version": 1,
                "phase": "impl",
                "default": {
                    "provider": "codex",
                    "model": "gpt-5.4",
                    "effort": "xhigh",
                },
            }
            (support_root / "configs" / "user" / "impl.json").write_text(
                json.dumps(impl_user_config, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            resolution = resolve_runtime_config(
                root_dir=root,
                request=self._build_impl_request(task_id="task-phase-default"),
                step_id="I0_analyze",
            )

        self.assertEqual(resolution.resolved_config["provider"]["provider"], "codex")
        self.assertEqual(resolution.resolved_config["provider"]["modelRef"], "gpt-5.4")
        self.assertEqual(
            resolution.resolved_config["provider"]["options"]["reasoningEffort"],
            "xhigh",
        )

    def test_strategy_default_overrides_phase_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support_root = self._clone_support_collab(root)
            impl_user_config = {
                "$schema": "../schemas/phase.schema.json",
                "version": 1,
                "phase": "impl",
                "$presets": {
                    "standard": {
                        "provider": "codex",
                        "model": "gpt-5.3-codex",
                        "effort": "mid",
                    },
                    "quality": {
                        "provider": "codex",
                        "model": "gpt-5.3-codex",
                        "effort": "high",
                    },
                },
                "default": {"$preset": "standard"},
                "strategies": {
                    "COLLAB_IMPL_PATCH_FIRST": {"default": {"$preset": "quality"}}
                },
            }
            (support_root / "configs" / "user" / "impl.json").write_text(
                json.dumps(impl_user_config, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            resolution = resolve_runtime_config(
                root_dir=root,
                request=self._build_impl_request(task_id="task-strategy-default"),
                step_id="I2_generate",
            )

        self.assertEqual(
            resolution.resolved_config["provider"]["modelRef"], "gpt-5.3-codex"
        )
        self.assertEqual(
            resolution.resolved_config["provider"]["options"]["reasoningEffort"],
            "high",
        )

    def test_step_override_wins_over_strategy_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support_root = self._clone_support_collab(root)
            impl_user_config = {
                "$schema": "../schemas/phase.schema.json",
                "version": 1,
                "phase": "impl",
                "$presets": {
                    "fast": {
                        "provider": "codex",
                        "model": "gpt-5.1-codex-mini",
                        "effort": "low",
                    },
                    "quality": {
                        "provider": "codex",
                        "model": "gpt-5.3-codex",
                        "effort": "high",
                    },
                },
                "strategies": {
                    "COLLAB_IMPL_PATCH_FIRST": {
                        "default": {"$preset": "quality"},
                        "steps": {"I0_analyze": {"$preset": "fast"}},
                    }
                },
            }
            (support_root / "configs" / "user" / "impl.json").write_text(
                json.dumps(impl_user_config, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            analyze_resolution = resolve_runtime_config(
                root_dir=root,
                request=self._build_impl_request(task_id="task-step-override-analyze"),
                step_id="I0_analyze",
            )
            generate_resolution = resolve_runtime_config(
                root_dir=root,
                request=self._build_impl_request(task_id="task-step-override-generate"),
                step_id="I2_generate",
            )

        self.assertEqual(
            analyze_resolution.resolved_config["provider"]["modelRef"],
            "gpt-5.1-codex-mini",
        )
        self.assertEqual(
            analyze_resolution.resolved_config["provider"]["options"][
                "reasoningEffort"
            ],
            "low",
        )
        self.assertEqual(
            generate_resolution.resolved_config["provider"]["modelRef"],
            "gpt-5.3-codex",
        )
        self.assertEqual(
            generate_resolution.resolved_config["provider"]["options"][
                "reasoningEffort"
            ],
            "high",
        )

    def test_disabled_strategy_excluded_from_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support_root = self._clone_support_collab(root)
            impl_user_config = {
                "$schema": "../schemas/phase.schema.json",
                "version": 1,
                "phase": "impl",
                "strategies": {"COLLAB_IMPL_PATCH_FIRST": {"enabled": False}},
            }
            (support_root / "configs" / "user" / "impl.json").write_text(
                json.dumps(impl_user_config, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            resolution = resolve_runtime_config(
                root_dir=root,
                request=self._build_impl_request(task_id="task-disabled-strategy"),
            )

        candidate_ids = [
            candidate["strategyId"]
            for candidate in resolution.routing_result["candidateScores"]["strategies"]
        ]
        self.assertEqual(
            resolution.resolved_config["strategy"]["selectedStrategyId"],
            "COLLAB_IMPL_BATCH_SHOT",
        )
        self.assertNotIn("COLLAB_IMPL_PATCH_FIRST", candidate_ids)

    def test_gemini_effort_flows_through_without_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support_root = self._clone_support_collab(root)
            impl_user_config = {
                "$schema": "../schemas/phase.schema.json",
                "version": 1,
                "phase": "impl",
                "strategies": {
                    "COLLAB_IMPL_PATCH_FIRST": {
                        "steps": {
                            "I5_shield": {
                                "provider": "gemini",
                                "effort": "high",
                            }
                        }
                    }
                },
            }
            (support_root / "configs" / "user" / "impl.json").write_text(
                json.dumps(impl_user_config, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            request = self._build_impl_request(task_id="task-gemini-effort")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                resolution = resolve_runtime_config(
                    root_dir=root,
                    request=request,
                    step_id="I5_shield",
                )

        self.assertEqual(resolution.resolved_config["provider"]["provider"], "gemini")
        self.assertEqual(
            resolution.resolved_config["provider"]["options"]["reasoningEffort"],
            "high",
        )
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_gemini_effort_in_resolved_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support_root = self._clone_support_collab(root)
            impl_user_config = {
                "$schema": "../schemas/phase.schema.json",
                "version": 1,
                "phase": "impl",
                "strategies": {
                    "COLLAB_IMPL_PATCH_FIRST": {
                        "steps": {
                            "I5_shield": {
                                "provider": "gemini",
                                "effort": "low",
                            }
                        }
                    }
                },
            }
            (support_root / "configs" / "user" / "impl.json").write_text(
                json.dumps(impl_user_config, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            request = self._build_impl_request(task_id="task-gemini-low-effort")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                resolution = resolve_runtime_config(
                    root_dir=root,
                    request=request,
                    step_id="I5_shield",
                )

        self.assertEqual(resolution.resolved_config["provider"]["provider"], "gemini")
        self.assertEqual(
            resolution.resolved_config["provider"]["options"]["reasoningEffort"],
            "low",
        )
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_handles_missing_user_files_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._clone_support_collab(root, include_user=False)

            bundle = load_config_bundle(root)
            resolution = resolve_runtime_config(
                root_dir=root,
                request=self._build_impl_request(task_id="task-no-user"),
                step_id="I0_analyze",
            )

        self.assertEqual(bundle.user_config["providers"], {})
        self.assertEqual(bundle.user_config["phases"], {})
        self.assertEqual(
            resolution.resolved_config["provider"]["modelRef"], "codex-primary"
        )
        self.assertEqual(
            resolution.resolved_config["provider"]["options"]["reasoningEffort"],
            "medium",
        )

    def test_profile_effort_survives_user_provider_defaults_in_live_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support_root = self._clone_support_collab(root)
            providers_config = {
                "$schema": "../schemas/providers.schema.json",
                "version": 1,
                "providers": {
                    "codex": {
                        "model": "gpt-5.3-codex",
                        "effort": "mid",
                    },
                    "copilot": {
                        "model": "claude-sonnet-4.6",
                        "effort": "xhigh",
                    },
                    "gemini": {
                        "model": "gemini-2.5-pro",
                    },
                },
            }
            (support_root / "configs" / "user" / "providers.json").write_text(
                json.dumps(providers_config, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            plan_user_config = {
                "$schema": "../schemas/phase.schema.json",
                "version": 1,
                "phase": "plan",
            }
            (support_root / "configs" / "user" / "plan.json").write_text(
                json.dumps(plan_user_config, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            request = {
                "task_id": "task-copilot-effort",
                "workflow_intent": "plan",
                "summary": "Architecture review with copilot override",
                "targets": {
                    "paths": ["agentorch_ctx/runtime/config_loader.py"],
                    "globs": [],
                },
                "constraints": {"hard": [], "soft": []},
                "output": {
                    "preferred_mode": "report_only",
                    "allowed_modes": ["report_only"],
                    "operations_required": False,
                },
                "selectors": {"strategy": "COLLAB_PLAN_THOROUGH"},
            }

            resolution = resolve_runtime_config(
                root_dir=root,
                request=request,
                agent_profile_override="plan-copilot-primary",
                step_id="P0_risk_scan",
            )
            adapter = get_provider_adapter("copilot", root_dir=root, live_mode=True)
            adapter_request = adapter.build_request(
                task_id="task-copilot-effort",
                phase="plan",
                step="P0_risk_scan",
                attempt=1,
                run=1,
                request=request,
                request_ref="/tmp/request.json",
                resolved_config=resolution.resolved_config,
                resolved_config_ref="/tmp/resolved-config.json",
                routing_result_ref="/tmp/routing.json",
                prompt_bundle={
                    "targets": request["targets"],
                    "summary": request["summary"],
                    "operatorContext": {"summary": "unit test"},
                },
                prompt_bundle_ref="/tmp/prompt.json",
                manifest_ref="/tmp/manifest.json",
                session_state=None,
                session_state_ref="",
                artifact_destinations={"adapterRequest": "/tmp/adapter-request.json"},
            )

        self.assertEqual(resolution.resolved_config["provider"]["provider"], "copilot")
        self.assertEqual(
            resolution.resolved_config["provider"]["modelRef"],
            "copilot-primary",
        )
        self.assertEqual(
            resolution.resolved_config["provider"]["options"]["reasoningEffort"],
            "medium",
        )
        self.assertEqual(
            adapter._build_live_env(adapter_request=adapter_request),
            {"COPILOT_REASONING_EFFORT": "medium"},
        )

    def _build_impl_request(self, *, task_id: str) -> dict[str, object]:
        return {
            "task_id": task_id,
            "workflow_intent": "impl",
            "summary": "Implement bounded patch for runtime",
            "targets": {
                "paths": ["agentorch_ctx/runtime/task_entrypoint.py"],
                "globs": [],
            },
            "constraints": {"hard": [], "soft": []},
            "output": {
                "preferred_mode": "patch",
                "allowed_modes": ["patch", "report_only"],
                "operations_required": True,
            },
            "selectors": {},
        }

    def _clone_support_collab(self, root: Path, *, include_user: bool = True) -> Path:
        source_root = Path(__file__).resolve().parents[2]
        support_root = root / ".agentorch"
        configs_source = source_root / "configs"
        configs_target = support_root / "configs"
        facts_target = support_root / "facts"

        if include_user:
            shutil.copytree(configs_source, configs_target)
        else:
            shutil.copytree(
                configs_source,
                configs_target,
                ignore=shutil.ignore_patterns("user"),
            )
        shutil.copytree(source_root / "facts", facts_target)
        return support_root


if __name__ == "__main__":
    unittest.main()
