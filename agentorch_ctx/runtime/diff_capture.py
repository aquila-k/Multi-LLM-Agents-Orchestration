"""Post-execution diff capture for direct-write validation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def capture_git_diff(
    root_dir: Path,
    baseline_ref: str = "HEAD",
) -> dict[str, Any]:
    """
    Capture changed files and byte counts since baseline_ref using git diff.
    Falls back to empty result if git is unavailable or not a repo.

    Returns:
        {
            "method": "git_diff" | "unavailable",
            "changedFiles": list[str],
            "changedFileCount": int,
            "baselineRef": str,
        }
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", baseline_ref],
            cwd=root_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return _unavailable_result()
        changed = [f for f in result.stdout.splitlines() if f.strip()]
        return {
            "method": "git_diff",
            "changedFiles": changed,
            "changedFileCount": len(changed),
            "baselineRef": baseline_ref,
        }
    except Exception:
        return _unavailable_result()


def check_paths_in_allowlist(
    changed_files: list[str],
    allowed_dirs: list[str],
) -> dict[str, Any]:
    """
    Check that all changed files are within the allowed directories.

    Returns:
        {
            "allInScope": bool,
            "outOfScopeFiles": list[str],
            "checkedFiles": int,
            "allowedDirs": list[str],
        }
    """
    if not allowed_dirs:
        return {
            "allInScope": True,
            "outOfScopeFiles": [],
            "checkedFiles": len(changed_files),
            "allowedDirs": [],
        }

    out_of_scope = []
    for f in changed_files:
        f_normalized = f.lstrip("/")
        if not any(
            f_normalized == d.lstrip("/")
            or f_normalized.startswith(d.rstrip("/") + "/")
            for d in allowed_dirs
        ):
            out_of_scope.append(f)

    return {
        "allInScope": len(out_of_scope) == 0,
        "outOfScopeFiles": out_of_scope,
        "checkedFiles": len(changed_files),
        "allowedDirs": allowed_dirs,
    }


def _unavailable_result() -> dict[str, Any]:
    return {
        "method": "unavailable",
        "changedFiles": [],
        "changedFileCount": 0,
        "baselineRef": "",
    }
