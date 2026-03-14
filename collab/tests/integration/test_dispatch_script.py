from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DispatchScriptIntegrationTest(unittest.TestCase):
    def test_run_script_emits_concise_artifact_first_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "workspace" / "deep"
            nested.mkdir(parents=True, exist_ok=True)
            (root / "AGENTS.md").write_text("# repo\n", encoding="utf-8")
            source = root / "goal.md"
            source.write_text(
                "# Plan runtime\n\nKeep output concise.\n", encoding="utf-8"
            )
            script = Path(__file__).resolve().parents[2] / "scripts" / "run"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--source",
                    str(source),
                    "--workflow-intent",
                    "plan",
                    "--operator-summary",
                    "script integration",
                ],
                cwd=nested,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0)
            stdout = completed.stdout
            self.assertIn("status: ready", stdout)
            self.assertIn("artifacts: request=", stdout)
            self.assertIn("artifacts: resolved_config=", stdout)
            self.assertIn("preflight:", stdout)

    def test_run_script_materializes_review_with_harden_phase_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("# repo\n", encoding="utf-8")
            source = root / "review.md"
            source.write_text("# Review runtime\n", encoding="utf-8")
            script = Path(__file__).resolve().parents[2] / "scripts" / "run"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--source",
                    str(source),
                    "--workflow-intent",
                    "review",
                    "--with-harden",
                    "--operator-summary",
                    "review with harden",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0)
            request_path = _extract_artifact_path(
                completed.stdout, "artifacts: request="
            )
            request = json.loads(Path(request_path).read_text(encoding="utf-8"))
            self.assertTrue(request["phase_options"]["with_harden"])
            task_root = Path(request_path).parents[1]
            resolved_config = json.loads(
                (
                    task_root / "resolved-config" / "resolved-config-intake.json"
                ).read_text(encoding="utf-8")
            )
            self.assertTrue(resolved_config["payload"]["phaseOptions"]["withHarden"])


def _extract_artifact_path(stdout: str, prefix: str) -> str:
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    raise AssertionError(f"missing line prefix: {prefix}")


if __name__ == "__main__":
    unittest.main()
