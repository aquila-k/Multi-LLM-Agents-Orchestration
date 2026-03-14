from __future__ import annotations

import unittest

from collab.runtime.prompt_builder import build_prompt


class PromptBuilderUnitTest(unittest.TestCase):
    def test_codex_impl_full_file_mode_uses_final_content_instruction(self) -> None:
        prompt = build_prompt(
            request=self._request(),
            resolved_config=self._resolved_config(),
            step_id="I2_generate",
            provider="codex",
            model_ref="codex-primary",
            effective_output_mode="full_file",
        )

        self.assertIn("complete, final content of each changed file", prompt)
        self.assertIn("Do NOT use diff format.", prompt)
        self.assertNotIn("Output changes as unified diff patches", prompt)

    def test_codex_impl_patch_mode_uses_diff_instruction(self) -> None:
        prompt = build_prompt(
            request=self._request(),
            resolved_config=self._resolved_config(),
            step_id="I2_generate",
            provider="codex",
            model_ref="codex-primary",
            effective_output_mode="patch",
        )

        self.assertIn("Output changes as unified diff patches", prompt)

    def test_codex_impl_default_mode_falls_back_to_diff_instruction(self) -> None:
        prompt = build_prompt(
            request=self._request(),
            resolved_config=self._resolved_config(),
            step_id="I2_generate",
            provider="codex",
            model_ref="codex-primary",
            effective_output_mode="",
        )

        self.assertIn("Output changes as unified diff patches", prompt)

    def test_prompt_renders_prior_step_artifact_references(self) -> None:
        request = self._request()
        request["operator_context"] = {
            "prior_step_artifact_refs": [
                {
                    "step": "I0_analyze",
                    "refType": "responseRef",
                    "ref": "/tmp/response-impl-I0_analyze.json",
                }
            ],
            "plan_artifact_ref": "/tmp/plan-plan-FINAL_plan.json",
            "checklist_artifact_ref": "/tmp/checklist-plan-FINAL_plan.json",
        }
        prompt = build_prompt(
            request=request,
            resolved_config=self._resolved_config(),
            step_id="I2_generate",
            provider="codex",
            model_ref="codex-primary",
            effective_output_mode="patch",
        )

        self.assertIn("## Prior Step Artifact References", prompt)
        self.assertIn(
            "- Step `I0_analyze` responseRef: `/tmp/response-impl-I0_analyze.json`",
            prompt,
        )
        self.assertIn("- plan_artifact_ref: `/tmp/plan-plan-FINAL_plan.json`", prompt)
        self.assertIn(
            "- checklist_artifact_ref: `/tmp/checklist-plan-FINAL_plan.json`",
            prompt,
        )

    def _request(self) -> dict[str, object]:
        return {
            "workflow_intent": "impl",
            "summary": "Implement output contract handling",
            "targets": {"paths": ["collab/runtime/prompt_builder.py"]},
            "constraints": {"hard": [], "soft": []},
            "source": {"path": "/tmp/nonexistent.md", "kind": "markdown"},
        }

    def _resolved_config(self) -> dict[str, object]:
        return {
            "phase": "impl",
            "artifacts": {},
        }


if __name__ == "__main__":
    unittest.main()
