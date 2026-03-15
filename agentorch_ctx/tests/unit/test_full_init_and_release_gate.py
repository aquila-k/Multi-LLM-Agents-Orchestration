import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentorch_ctx.cli import cmd_full_init
from agentorch_ctx.scripts.validation import release_gate


class FullInitUnitTest(unittest.TestCase):
    def test_run_ctx_init_writes_codex_skill_under_agent_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)

            with patch.object(cmd_full_init, "_run_ctx_db_init", return_value=0):
                rc = cmd_full_init.run_ctx_init(repo_root)

            self.assertEqual(rc, 0)
            self.assertTrue(
                (repo_root / ".agent" / "skills" / "agentorch-ctx" / "SKILL.md").exists()
            )
            self.assertFalse((repo_root / ".agents").exists())
            self.assertIn(
                "## agentorch ctx",
                (repo_root / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_run_ctx_init_installs_ctx_hooks_and_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)

            with patch.object(cmd_full_init, "_run_ctx_db_init", return_value=0):
                rc = cmd_full_init.run_ctx_init(repo_root)

            self.assertEqual(rc, 0)
            self.assertTrue((repo_root / ".claude" / "hooks" / "session_start_context.sh").exists())
            settings = json.loads((repo_root / ".claude" / "settings.json").read_text(encoding="utf-8"))
            hooks = settings["hooks"]
            self.assertIn("SessionStart", hooks)
            self.assertIn("PreToolUse", hooks)
            self.assertIn("Stop", hooks)

    def test_ensure_claude_ctx_hooks_preserves_existing_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            settings_path = repo_root / ".claude" / "settings.json"
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps(
                    {
                        "permissions": {"allow": ["Bash(existing:*)"]},
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "*",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": ".claude/hooks/custom.sh",
                                        }
                                    ],
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            cmd_full_init.ensure_claude_ctx_hooks(repo_root)

            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(settings["permissions"]["allow"], ["Bash(existing:*)"])
            commands = []
            for entries in settings["hooks"].values():
                for entry in entries:
                    for handler in entry["hooks"]:
                        commands.append(handler["command"])
            self.assertIn(".claude/hooks/custom.sh", commands)
            self.assertIn("bash .claude/hooks/session_start_context.sh", commands)
            self.assertIn("bash .claude/hooks/pre_tool_use_context_check.sh", commands)
            self.assertIn("bash .claude/hooks/stop_context_save.sh", commands)


class ReleaseGateUnitTest(unittest.TestCase):
    def test_skip_live_validation_defers_live_provider_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            probe_dir = Path(tmp)
            for name in (
                "check-entrypoint.json",
                "check-resume.json",
                "check-review-harden.json",
                "check-artifacts.json",
            ):
                (probe_dir / name).write_text(
                    json.dumps(
                        {
                            "validatedAt": "2026-03-15T00:00:00Z",
                            "allPassed": True,
                            "checks": [],
                        }
                    ),
                    encoding="utf-8",
                )

            with patch.object(release_gate, "PROBE_DIR", probe_dir):
                result = release_gate.evaluate(require_live_providers=False)

        gates = {gate["gate"]: gate for gate in result["gates"]}
        self.assertFalse(result["liveActivationBlocked"])
        self.assertEqual(result["summary"], "STUB-SAFE CLEAR: 2 deferred gate(s)")
        self.assertEqual(result["openObligations"], [])
        self.assertEqual(len(result["deferredObligations"]), 2)
        self.assertTrue(gates["live_providers"]["deferred"])
        self.assertTrue(gates["output_discipline"]["deferred"])


if __name__ == "__main__":
    unittest.main()
