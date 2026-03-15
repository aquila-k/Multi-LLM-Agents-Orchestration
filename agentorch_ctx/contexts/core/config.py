"""Configuration file management and repo/project auto-detection."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .ids import now_iso


def resolve_db_path(db_path_arg=None) -> Path:
    """
    Resolve the database path with the following priority:
    1. db_path_arg (explicit --db-path)
    2. CONTEXTS_HOME env var -> Path(CONTEXTS_HOME) / "context.db"
    3. Walk up from cwd to find AGENTS.md or .git -> repo_root/.contexts/local/context.db
    4. Raise FileNotFoundError
    """
    if db_path_arg:
        return Path(db_path_arg)

    env_home = os.environ.get("CONTEXTS_HOME")
    if env_home:
        return Path(env_home) / "context.db"

    try:
        root = find_repo_root(Path.cwd())
        return root / ".contexts" / "local" / "context.db"
    except FileNotFoundError:
        pass

    raise FileNotFoundError(
        "Cannot resolve DB path: no --db-path, no CONTEXTS_HOME, "
        "and no AGENTS.md or .git found in parent directories."
    )


def load_config(db_path: Path) -> dict:
    """Load config.json from db_path.parent. Raises FileNotFoundError if missing."""
    config_path = db_path.parent / "config.json"
    if not config_path.exists():
        raise FileNotFoundError("Config file not found: {}".format(config_path))
    with open(str(config_path), "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(db_path: Path, cfg: dict) -> None:
    """Atomic write via .partial -> os.replace()."""
    config_path = db_path.parent / "config.json"
    partial_path = db_path.parent / "config.json.partial"
    with open(str(partial_path), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(str(partial_path), str(config_path))


def auto_detect_project_id(repo_root: Path) -> str:
    """
    SHA-256 of git remote get-url origin; fallback: SHA-256 of repo_root str.
    Returns first 12 hex chars.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            source = result.stdout.strip()
        else:
            source = str(repo_root)
    except (subprocess.SubprocessError, OSError):
        source = str(repo_root)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def auto_detect_repo_id(repo_root: Path) -> str:
    """
    SHA-256 of git rev-parse --show-toplevel output. First 12 hex chars.
    Falls back to SHA-256 of repo_root str.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            source = result.stdout.strip()
        else:
            source = str(repo_root)
    except (subprocess.SubprocessError, OSError):
        source = str(repo_root)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def find_repo_root(start: Path) -> Path:
    """
    Walk up from start; stop at AGENTS.md or .git (AGENTS.md has priority).
    Raises FileNotFoundError if neither is found.
    """
    current = start.resolve()
    while True:
        if (current / "AGENTS.md").exists():
            return current
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(
        "Cannot find repo root: no AGENTS.md or .git in any parent of {}".format(start)
    )
