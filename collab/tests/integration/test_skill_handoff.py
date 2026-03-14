from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collab.runtime.claude_code_skill import ClaudeCodeSkill


class SkillHandoffIntegrationTest(unittest.TestCase):
    def test_markdown_source_is_canonicalized_and_state_is_initialized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "goal.md"
            source.write_text(
                "# Implement intake\n\nNeed a safe dispatcher.\n", encoding="utf-8"
            )

            skill = ClaudeCodeSkill(root_dir=root)
            result = skill.dispatch(
                source_path=source,
                workflow_intent="plan",
                source_kind="markdown",
                targets={"paths": ["collab/runtime"], "summary": "runtime only"},
                constraints={"hard": ["no legacy dependency"]},
                operator_context={"summary": "phase c test"},
            )

            request = json.loads(result.request_path.read_text(encoding="utf-8"))
            self.assertEqual(request["workflow_intent"], "plan")
            self.assertEqual(request["summary"], "Implement intake")
            self.assertEqual(request["targets"]["paths"], ["collab/runtime"])
            self.assertFalse(request["phase_options"]["auto_advance"])
            self.assertFalse(request["phase_options"]["with_harden"])
            self.assertEqual(
                request["assembly_options"],
                {
                    "prompt_version": "1.0.0",
                    "schema_version": "1.0.0",
                    "concise_shell_summary": True,
                },
            )

            task_artifact_root = (
                root / "collab" / "artifacts" / "tasks" / result.task_id
            )
            intake_snapshot = result.intake_snapshot_dir / "source-snapshot.md"
            self.assertTrue(intake_snapshot.exists())
            resolved_config_artifact = json.loads(
                (
                    task_artifact_root
                    / "resolved-config"
                    / "resolved-config-intake.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                resolved_config_artifact["payload"]["strategy"]["selectedStrategyId"],
                "COLLAB_PLAN_FULL",
            )
            self.assertEqual(
                resolved_config_artifact["payload"]["provider"]["provider"], "gemini"
            )
            routing_artifact = json.loads(
                (
                    task_artifact_root / "routing" / "routing-result-intake.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(routing_artifact["payload"]["selectedProvider"], "gemini")
            self.assertTrue(routing_artifact["payload"]["candidateScores"]["providers"])
            prompt_bundle_artifact = json.loads(
                (
                    task_artifact_root / "prompts" / "prompt-bundle-intake.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                prompt_bundle_artifact["payload"]["selectedProvider"], "gemini"
            )
            manifest_artifact = json.loads(
                (task_artifact_root / "manifests" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest_artifact["payload"]["activePhase"], "plan")
            self.assertEqual(
                manifest_artifact["payload"]["artifactRefs"]["promptBundle"],
                (task_artifact_root / "prompts" / "prompt-bundle-intake.json")
                .resolve()
                .as_posix(),
            )
            summary_markdown = (
                task_artifact_root / "summaries" / "intake-summary.md"
            ).read_text(encoding="utf-8")
            self.assertIn("# Collab Intake Summary", summary_markdown)
            self.assertIn("COLLAB_PLAN_FULL", summary_markdown)

            controller_state = json.loads(
                result.controller_state_path.read_text(encoding="utf-8")
            )
            self.assertEqual(controller_state["current_status"], "running")
            self.assertEqual(controller_state["active_phase"], "plan")
            self.assertEqual(controller_state["active_strategy"], "COLLAB_PLAN_FULL")
            self.assertEqual(
                controller_state["pending_approval_state"]["status"], "not_required"
            )

            known_information_path = (
                result.controller_state_path.parent / "known-information.json"
            )
            known_information = json.loads(
                known_information_path.read_text(encoding="utf-8")
            )
            self.assertEqual(known_information["user_goal_summary"], "Implement intake")
            self.assertEqual(
                known_information["confirmed_constraints"], ["no legacy dependency"]
            )
            self.assertEqual(
                known_information["entries"][1]["value"], "COLLAB_PLAN_FULL"
            )
            self.assertEqual(known_information["entries"][2]["value"], "gemini")
            self.assertEqual(
                Path(known_information["latest_phase_summary"]["artifact_ref"])
                .resolve()
                .as_posix(),
                (task_artifact_root / "summaries" / "intake-summary.md")
                .resolve()
                .as_posix(),
            )

            registry_path = root / "collab" / "state" / "task-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertIn(result.task_id, registry["tasks"])
            self.assertIn("phase=plan", result.shell_summary)


if __name__ == "__main__":
    unittest.main()
