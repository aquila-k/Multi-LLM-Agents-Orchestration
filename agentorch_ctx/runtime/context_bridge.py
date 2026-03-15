from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("agentorch_ctx.context_bridge")

StoredContext = dict[str, Any]
ContextRunner = Callable[..., dict[str, Any]]


def _run_contexts(
    root_dir: Path,
    *args: str,
    input_json: dict[str, Any] | None = None,
    timeout: float = 5,
) -> dict[str, Any]:
    """Call the contexts subsystem and return parsed JSON output.

    The subprocess is always invoked with the current Python interpreter and a
    repo-scoped ``CONTEXTS_HOME`` so it targets the requested repository even
    when the parent process has a different cwd or inherited context settings.
    """
    # Use the current Python interpreter to invoke agentorch_ctx ctx directly.
    # This avoids wrapper/PATH issues and guarantees the same package is used.
    # Set CONTEXTS_HOME so the subprocess finds the correct DB regardless of cwd.
    import os

    env = os.environ.copy()
    contexts_local = root_dir / ".contexts" / "local"
    env["CONTEXTS_HOME"] = str(contexts_local)

    # Ensure PYTHONPATH includes the package root so the subprocess can
    # import agentorch_ctx even when it is not pip-installed.
    pkg_root = str(Path(__file__).resolve().parents[2])
    existing = env.get("PYTHONPATH", "")
    if pkg_root not in existing.split(os.pathsep):
        env["PYTHONPATH"] = pkg_root + (os.pathsep + existing if existing else "")

    cmd = [sys.executable, "-m", "agentorch_ctx", "ctx", *args]

    logger.debug("contexts call: args=%s timeout=%s cwd=%s", args, timeout, root_dir)
    try:
        result = subprocess.run(
            cmd,
            input=json.dumps(input_json) if input_json is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(root_dir),
            env=env,
        )
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.warning("contexts call timed out: args=%s", args)
        return {"ok": False, "error": "timeout", "args": list(args)}
    except json.JSONDecodeError:
        logger.warning("contexts response is not JSON: args=%s", args)
        return {"ok": False, "error": "json_decode", "args": list(args)}
    except FileNotFoundError:
        logger.warning("contexts executable not found: args=%s", args)
        return {"ok": False, "error": "not_found", "args": list(args)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("contexts call failed: args=%s error=%s", args, exc)
        return {"ok": False, "error": type(exc).__name__, "args": list(args)}


def _is_degraded(result: dict[str, Any]) -> bool:
    """Return True when contexts result indicates degraded mode."""
    if result.get("ok") is False:
        if result.get("code") == "NOT_INITIALIZED":
            logger.warning(
                "contexts not initialized; degraded mode: args=%s", result.get("args")
            )
        return True
    return False


def load_task_context(
    root_dir: Path,
    task_id: str,
    session_id: str | None = None,
    include_project: bool = True,
    max_bytes: int = 8000,
    runner: ContextRunner = _run_contexts,
) -> dict[str, Any]:
    """Fetch stored context for the requested task."""
    args = ["get-task-context", "--task-id", task_id, "--max-bytes", str(max_bytes)]
    if session_id:
        args += ["--session-id", session_id]
    if include_project:
        args.append("--include-project")
    result = runner(root_dir, *args)
    if _is_degraded(result):
        return {}
    return result


def save_task_snapshot(
    root_dir: Path,
    task_id: str,
    payload: dict[str, Any],
    expected_revision: int,
    change_reason: str = "",
    runner: ContextRunner = _run_contexts,
) -> dict[str, Any]:
    """Update task snapshot with CAS protection and single retry."""
    args = [
        "update-task-context",
        "--task-id",
        task_id,
        "--expected-revision",
        str(expected_revision),
    ]
    if change_reason:
        args += ["--change-reason", change_reason]

    result = runner(root_dir, *args, input_json=payload)

    if result.get("ok") is False and result.get("code") == "CONFLICT":
        latest = get_current_revision(root_dir, task_id, runner=runner)
        # If revision fetch returned 0 but the original expected_revision was > 0,
        # the fetch itself was degraded — retrying with 0 would guarantee another
        # CONFLICT.  Skip the retry and log instead.
        if latest == 0 and expected_revision > 0:
            logger.warning(
                "task snapshot CAS conflict; revision fetch degraded; skip retry: task_id=%s",
                task_id,
            )
            return {"ok": False, "code": "CONFLICT", "skipped": True}
        retry_args = [
            "update-task-context",
            "--task-id",
            task_id,
            "--expected-revision",
            str(latest),
        ]
        if change_reason:
            retry_args += ["--change-reason", change_reason]
        result = runner(root_dir, *retry_args, input_json=payload)
        if result.get("ok") is False and result.get("code") == "CONFLICT":
            logger.warning(
                "task snapshot CAS conflict; skip after retry: task_id=%s",
                task_id,
            )
            return {"ok": False, "code": "CONFLICT", "skipped": True}

    return result


def log_episode(
    root_dir: Path,
    task_id: str,
    payload: dict[str, Any],
    change_reason: str = "",
    runner: ContextRunner = _run_contexts,
) -> dict[str, Any]:
    """Record an episode (phase completion observation)."""
    args = ["log-episode", "--task-id", task_id]
    if change_reason:
        args += ["--change-reason", change_reason]
    result = runner(root_dir, *args, input_json=payload)
    if _is_degraded(result):
        return {}
    return result


def log_decision(
    root_dir: Path,
    key: str,
    scope: str,
    payload: dict[str, Any],
    change_reason: str = "",
    confidence: float | None = None,
    runner: ContextRunner = _run_contexts,
) -> dict[str, Any]:
    """Record a decision via log-decision."""
    args = ["log-decision", "--key", key, "--scope", scope]
    if change_reason:
        args += ["--change-reason", change_reason]
    if confidence is not None:
        args += ["--confidence", str(confidence)]
    result = runner(root_dir, *args, input_json=payload)
    if _is_degraded(result):
        return {}
    return result


def get_project_context(
    root_dir: Path,
    max_bytes: int = 8000,
    runner: ContextRunner = _run_contexts,
) -> dict[str, Any]:
    """Fetch project-level context."""
    args = ["get-project-context", "--max-bytes", str(max_bytes)]
    result = runner(root_dir, *args)
    if _is_degraded(result):
        return {}
    return result


def get_current_revision(
    root_dir: Path,
    task_id: str,
    runner: ContextRunner = _run_contexts,
) -> int:
    """Return the current task snapshot revision."""
    args = ["get-task-context", "--task-id", task_id, "--max-bytes", "1"]
    result = runner(root_dir, *args)
    if _is_degraded(result):
        return 0
    top_level = result.get("task_snapshot_revision")
    if isinstance(top_level, int):
        return top_level
    snapshot = result.get("task_snapshot") or {}
    if isinstance(snapshot, dict):
        rev = snapshot.get("revision")
        if isinstance(rev, int):
            return rev
    return 0


def search_related(
    root_dir: Path,
    query: str,
    scope: str | None = None,
    limit: int = 5,
    runner: ContextRunner = _run_contexts,
) -> list[dict[str, Any]]:
    """Search related context entries for a free-text query."""
    args = [
        "search-memory",
        "--query",
        query,
        "--limit",
        str(limit),
        "--format",
        "json",
    ]
    if scope:
        args += ["--scope", scope]
    result = runner(root_dir, *args)
    if _is_degraded(result):
        return []
    results = result.get("results")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    return []
