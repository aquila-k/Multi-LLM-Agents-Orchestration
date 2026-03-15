from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentorch_ctx.runtime.context_bridge import (
    _run_contexts,
    get_current_revision,
    load_task_context,
    log_episode,
    save_task_snapshot,
    search_related,
)


class ContextBridgeUnitTest(unittest.TestCase):
    def test_load_task_context_succeeds(self) -> None:
        result = load_task_context(
            root_dir=Path("."),
            task_id="T0",
            runner=lambda *args, **kwargs: {"ok": True, "task_snapshot": {"value": 1}},
        )
        self.assertEqual(result, {"ok": True, "task_snapshot": {"value": 1}})

    def test_load_task_context_degraded_when_not_initialized(self) -> None:
        result = load_task_context(
            root_dir=Path("."),
            task_id="T1",
            runner=lambda *args, **kwargs: {"ok": False, "code": "NOT_INITIALIZED"},
        )
        self.assertEqual(result, {})

    def test_load_task_context_handles_timeout(self) -> None:
        with patch(
            "agentorch_ctx.runtime.context_bridge.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="", timeout=0.1),
        ):
            result = load_task_context(root_dir=Path("."), task_id="T2")
        self.assertEqual(result, {})

    def test_run_contexts_forces_repo_scoped_contexts_home(self) -> None:
        root_dir = Path("/tmp/repo-under-test")
        with patch.dict("os.environ", {"CONTEXTS_HOME": "/tmp/other-contexts"}):
            with patch(
                "agentorch_ctx.runtime.context_bridge.subprocess.run",
                return_value=SimpleNamespace(stdout='{"ok": true}'),
            ) as mock_run:
                result = _run_contexts(root_dir, "get-project-context")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mock_run.call_args.kwargs["cwd"], str(root_dir))
        self.assertEqual(
            mock_run.call_args.kwargs["env"]["CONTEXTS_HOME"],
            str(root_dir / ".contexts" / "local"),
        )

    def test_save_task_snapshot_success(self) -> None:
        calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

        def runner(
            root_dir: Path, *command_args: str, **kwargs: object
        ) -> dict[str, object]:
            calls.append((command_args, kwargs))
            return {"ok": True}

        result = save_task_snapshot(
            root_dir=Path("."),
            task_id="T3",
            payload={"foo": "bar"},
            expected_revision=1,
            runner=runner,
        )
        self.assertEqual(result, {"ok": True})
        self.assertTrue(any(call[0][0] == "update-task-context" for call in calls))

    def test_save_task_snapshot_retries_on_conflict(self) -> None:
        state = {"update_calls": 0}

        def runner(
            root_dir: Path, *command_args: str, **kwargs: object
        ) -> dict[str, object]:
            cmd = command_args[0]
            if cmd == "update-task-context":
                state["update_calls"] += 1
                if state["update_calls"] == 1:
                    return {"ok": False, "code": "CONFLICT"}
                return {"ok": True}
            if cmd == "get-task-context":
                return {"ok": True, "task_snapshot_revision": 2}
            return {"ok": True}

        result = save_task_snapshot(
            root_dir=Path("."),
            task_id="T4",
            payload={"bar": "baz"},
            expected_revision=1,
            runner=runner,
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(state["update_calls"], 2)

    def test_save_task_snapshot_skips_after_conflict_retry_failure(self) -> None:
        def runner(
            root_dir: Path, *command_args: str, **kwargs: object
        ) -> dict[str, object]:
            cmd = command_args[0]
            if cmd == "update-task-context":
                return {"ok": False, "code": "CONFLICT"}
            if cmd == "get-task-context":
                return {"ok": True, "task_snapshot_revision": 5}
            return {"ok": True}

        result = save_task_snapshot(
            root_dir=Path("."),
            task_id="T5",
            payload={"baz": "qux"},
            expected_revision=1,
            runner=runner,
        )
        self.assertEqual(result, {"ok": False, "code": "CONFLICT", "skipped": True})

    def test_get_current_revision_returns_snapshot_revision(self) -> None:
        result = get_current_revision(
            root_dir=Path("."),
            task_id="T6",
            runner=lambda *args, **kwargs: {
                "ok": True,
                "task_snapshot": {"revision": 7},
            },
        )
        self.assertEqual(result, 7)

    def test_log_episode_uses_log_episode_command(self) -> None:
        calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

        def runner(
            root_dir: Path, *command_args: str, **kwargs: object
        ) -> dict[str, object]:
            calls.append((command_args, kwargs))
            return {"ok": True}

        result = log_episode(
            root_dir=Path("."),
            task_id="T7",
            payload={"observation": "done"},
            runner=runner,
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls[0][0][0], "log-episode")
        self.assertEqual(calls[0][0][1:3], ("--task-id", "T7"))

    def test_search_related_returns_matches(self) -> None:
        result = search_related(
            root_dir=Path("."),
            query="context",
            runner=lambda *args, **kwargs: {
                "ok": True,
                "results": [{"key": "k1"}, {"key": "k2"}],
            },
        )
        self.assertEqual(result, [{"key": "k1"}, {"key": "k2"}])


if __name__ == "__main__":
    unittest.main()
