from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentorch_ctx.runtime.pathing import augment_path_env, resolve_runtime_paths
from agentorch_ctx.runtime.preflight import run_preflight


class PathingPreflightUnitTest(unittest.TestCase):
    def test_resolves_repo_root_from_nested_directory_without_existing_collab_dir(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "src" / "nested"
            nested.mkdir(parents=True, exist_ok=True)
            (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")

            runtime_paths = resolve_runtime_paths(start_dir=nested)

        self.assertEqual(runtime_paths.repo_root, root.resolve())
        self.assertEqual(runtime_paths.config_root, Path(__file__).resolve().parents[2])

    def test_augment_path_env_prefers_workspace_bins_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_bin = root / ".venv" / "bin"
            node_bin = root / "node_modules" / ".bin"
            venv_bin.mkdir(parents=True, exist_ok=True)
            node_bin.mkdir(parents=True, exist_ok=True)

            env = augment_path_env(root, {"PATH": f"{venv_bin}:{node_bin}:{venv_bin}"})

        entries = env["PATH"].split(":")
        self.assertEqual(entries[0], str(venv_bin))
        self.assertEqual(entries[1], str(node_bin))
        self.assertEqual(entries.count(str(venv_bin)), 1)

    def test_preflight_reports_provider_discoverability_without_blocking_stub_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
            runtime_paths = resolve_runtime_paths(start_dir=root)

            result = run_preflight(runtime_paths)

        self.assertEqual(
            {status.provider for status in result.providers},
            {"codex", "gemini", "copilot"},
        )
        self.assertEqual(
            sorted(result.missing_providers),
            sorted(
                [status.provider for status in result.providers if not status.available]
            ),
        )


if __name__ == "__main__":
    unittest.main()
