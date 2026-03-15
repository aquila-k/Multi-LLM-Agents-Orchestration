from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentorch_ctx.runtime.claude_code_skill import ClaudeCodeSkill


class ClaudeCodeSkillUnitTest(unittest.TestCase):
    def test_auto_init_uses_repo_scoped_contexts_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
            with patch.dict("os.environ", {"CONTEXTS_HOME": "/tmp/external-contexts"}):
                with patch(
                    "subprocess.run",
                    return_value=SimpleNamespace(
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                ) as mock_run:
                    ClaudeCodeSkill(root_dir=root_dir)
        self.assertEqual(mock_run.call_args.kwargs["cwd"], str(root_dir))
        self.assertEqual(
            mock_run.call_args.kwargs["env"]["CONTEXTS_HOME"],
            str(root_dir / ".contexts" / "local"),
        )


if __name__ == "__main__":
    unittest.main()
