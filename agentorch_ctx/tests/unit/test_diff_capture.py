from __future__ import annotations

import unittest

from agentorch_ctx.runtime.diff_capture import check_paths_in_allowlist


class TestDiffCapture(unittest.TestCase):
    def test_check_paths_in_allowlist_all_in_scope_src_prefix(self) -> None:
        result = check_paths_in_allowlist(
            ["src/foo.py", "src/bar.py"],
            ["src/"],
        )

        self.assertTrue(result["allInScope"])
        self.assertEqual(result["outOfScopeFiles"], [])

    def test_check_paths_in_allowlist_out_of_scope_src_prefix(self) -> None:
        result = check_paths_in_allowlist(
            ["src/foo.py", "secrets/env.sh"],
            ["src/"],
        )

        self.assertFalse(result["allInScope"])
        self.assertIn("secrets/env.sh", result["outOfScopeFiles"])

    def test_check_paths_in_allowlist_all_in_scope(self) -> None:
        result = check_paths_in_allowlist(
            ["agentorch_ctx/runtime/file.py", "agentorch_ctx/tests/unit/test_file.py"],
            ["agentorch_ctx/runtime", "agentorch_ctx/tests"],
        )

        self.assertTrue(result["allInScope"])
        self.assertEqual(result["outOfScopeFiles"], [])

    def test_check_paths_in_allowlist_out_of_scope(self) -> None:
        result = check_paths_in_allowlist(
            ["agentorch_ctx/runtime/file.py", "README.md"],
            ["agentorch_ctx/runtime"],
        )

        self.assertFalse(result["allInScope"])
        self.assertEqual(result["outOfScopeFiles"], ["README.md"])

    def test_check_paths_empty_allowlist_passes_all(self) -> None:
        result = check_paths_in_allowlist(
            ["agentorch_ctx/runtime/file.py", "README.md"],
            [],
        )

        self.assertTrue(result["allInScope"])
        self.assertEqual(result["outOfScopeFiles"], [])

    def test_check_paths_in_allowlist_empty_allowlist_allows_all(self) -> None:
        result = check_paths_in_allowlist(
            ["anywhere/foo.py"],
            [],
        )

        self.assertTrue(result["allInScope"])
        self.assertEqual(result["outOfScopeFiles"], [])


if __name__ == "__main__":
    unittest.main()
