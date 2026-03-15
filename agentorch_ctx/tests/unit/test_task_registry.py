from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from agentorch_ctx.task_registry.db import (
    check_stale_tasks,
    create_task,
    generate_task_id,
    get_current_task,
    get_task,
    join_task,
    list_tasks,
    open_tasks_db,
    update_task_status,
)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = open_tasks_db(tmp_path / "tasks.db")
    try:
        yield connection
    finally:
        connection.close()


def test_create_task_and_get_task(conn: sqlite3.Connection) -> None:
    create_task(
        conn,
        task_id="task-001",
        summary="Fix auth bug",
        created_by="claude",
        collab_ref="collab-123",
        pid=4321,
        metadata={"priority": "high"},
    )

    task = get_task(conn, "task-001")

    assert task is not None
    assert task["task_id"] == "task-001"
    assert task["summary"] == "Fix auth bug"
    assert task["status"] == "active"
    assert task["created_by"] == "claude"
    assert task["collab_ref"] == "collab-123"
    assert task["pid"] == 4321
    assert task["metadata"] == {"priority": "high"}
    assert task["providers"] == []


def test_get_current_task_returns_most_recent_active(conn: sqlite3.Connection) -> None:
    create_task(conn, task_id="task-old", summary="Older task")
    create_task(conn, task_id="task-new", summary="Newer task")
    update_task_status(conn, "task-old", "paused")

    current = get_current_task(conn)

    assert current is not None
    assert current["task_id"] == "task-new"


def test_get_current_task_filters_by_provider(conn: sqlite3.Connection) -> None:
    create_task(conn, task_id="task-a", summary="Task A")
    create_task(conn, task_id="task-b", summary="Task B")
    join_task(conn, "task-a", "claude", role="worker")
    join_task(conn, "task-b", "codex", role="orchestrator")

    assert get_current_task(conn, provider="claude")["task_id"] == "task-a"
    assert get_current_task(conn, provider="codex")["task_id"] == "task-b"
    assert get_current_task(conn, provider="gemini") is None


def test_update_task_status(conn: sqlite3.Connection) -> None:
    create_task(conn, task_id="task-001", summary="Fix auth bug")
    before = get_task(conn, "task-001")

    updated = update_task_status(conn, "task-001", "completed")

    assert updated["status"] == "completed"
    assert before is not None
    assert updated["updated_at"] >= before["updated_at"]


def test_join_task_tracks_multiple_providers(conn: sqlite3.Connection) -> None:
    create_task(conn, task_id="task-join", summary="Shared task")

    first = join_task(conn, "task-join", "claude", role="orchestrator")
    second = join_task(conn, "task-join", "codex", role="worker")

    task = get_task(conn, "task-join")
    assert first["provider"] == "claude"
    assert first["role"] == "orchestrator"
    assert second["provider"] == "codex"
    assert second["role"] == "worker"
    assert task is not None
    assert [provider["provider"] for provider in task["providers"]] == [
        "claude",
        "codex",
    ]


def test_check_stale_tasks(conn: sqlite3.Connection) -> None:
    create_task(conn, task_id="stale-task", summary="stale", pid=99999)
    create_task(conn, task_id="live-task", summary="live", pid=12345)

    def fake_kill(pid: int, signal: int) -> None:
        if pid == 12345:
            return None
        raise ProcessLookupError(pid)

    with patch("agentorch_ctx.task_registry.db.os.kill", side_effect=fake_kill):
        stale = check_stale_tasks(conn)

    assert [task["task_id"] for task in stale] == ["stale-task"]


def test_generate_task_id_various_inputs() -> None:
    task_id = generate_task_id("Fix authentication flow!!!")
    long_task_id = generate_task_id("A" * 80)
    unicode_task_id = generate_task_id("  Résumé / 進捗 / task  ")

    assert re.fullmatch(r"[a-z0-9-]+-\d{8}T\d{6}Z", task_id)
    assert task_id.startswith("fix-authentication-flow-")
    assert long_task_id.startswith(("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-",))
    assert unicode_task_id.startswith("resume-task-")
    assert len(long_task_id.split("-")[0]) <= 40


def test_list_tasks_with_filters(conn: sqlite3.Connection) -> None:
    create_task(conn, task_id="parent", summary="Parent")
    create_task(conn, task_id="child-active", summary="Child A", parent_id="parent")
    create_task(conn, task_id="child-done", summary="Child B", parent_id="parent")
    update_task_status(conn, "child-done", "completed")

    active = list_tasks(conn, status="active")
    children = list_tasks(conn, parent_id="parent")
    completed_children = list_tasks(conn, status="completed", parent_id="parent")

    assert {task["task_id"] for task in active} == {"parent", "child-active"}
    assert {task["task_id"] for task in children} == {"child-active", "child-done"}
    assert [task["task_id"] for task in completed_children] == ["child-done"]


def test_parent_id_hierarchy(conn: sqlite3.Connection) -> None:
    create_task(conn, task_id="root", summary="Root task")
    create_task(conn, task_id="child", summary="Child task", parent_id="root")
    create_task(conn, task_id="grandchild", summary="Grandchild task", parent_id="child")

    child = get_task(conn, "child")
    grandchild = get_task(conn, "grandchild")

    assert child is not None
    assert grandchild is not None
    assert child["parent_id"] == "root"
    assert grandchild["parent_id"] == "child"


def test_list_tasks_limit_validation(conn: sqlite3.Connection) -> None:
    create_task(conn, task_id="task-001", summary="Any")

    with pytest.raises(ValueError, match="limit must be greater than 0"):
        list_tasks(conn, limit=0)
