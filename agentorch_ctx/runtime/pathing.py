from __future__ import annotations

import os
import shutil
import warnings
from dataclasses import dataclass
from pathlib import Path

MARKER_FILES = ("AGENTS.md", ".git")

# Package directory name (used for source-repo layout).
_PKG_DIR_NAME = "agentorch_ctx"

# Directory name created by ``agentorch init`` in external repos.
_INIT_DIR_NAME = ".agentorch"

# Legacy directory name used before the CLI packaging rename.
_LEGACY_DIR_NAME = "collab"


@dataclass(frozen=True)
class RuntimePaths:
    repo_root: Path
    config_root: Path
    script_path: Path


def package_root() -> Path:
    """Return the root of the ``agentorch_ctx`` package itself.

    Used for accessing internal configs, schemas, and facts that are bundled
    with the package.  This is NOT the user's project root — never write
    user data here.
    """
    return Path(__file__).resolve().parents[1]


def resolve_runtime_paths(
    *,
    start_dir: Path | None = None,
    explicit_root: Path | None = None,
) -> RuntimePaths:
    script_path = Path(shutil.which("agentorch") or "agentorch")
    repo_root = resolve_repo_root(start_dir=start_dir, explicit_root=explicit_root)
    config_root_dir = resolve_config_root(repo_root)
    return RuntimePaths(
        repo_root=repo_root,
        config_root=config_root_dir,
        script_path=script_path,
    )


def resolve_repo_root(
    *, start_dir: Path | None = None, explicit_root: Path | None = None
) -> Path:
    if explicit_root is not None:
        return explicit_root.expanduser().resolve()

    search_roots = []
    if start_dir is not None:
        search_roots.append(start_dir.expanduser().resolve())
    search_roots.append(Path.cwd().resolve())

    for candidate in search_roots:
        resolved = _walk_for_repo_root(candidate)
        if resolved is not None:
            return resolved
    raise FileNotFoundError(
        "Could not find repo root (no AGENTS.md or .git found). "
        "Run 'agentorch init' first, or pass --root explicitly."
    )


def resolve_config_root(repo_root: Path) -> Path:
    """Return the directory that contains ``configs/``, ``facts/``, etc.

    Resolution order:
      1. ``<repo_root>/.agentorch/``  — init'd external repo
      2. ``<repo_root>/agentorch_ctx/`` — source-repo development layout
      3. ``<repo_root>/collab/``      — legacy layout (DeprecationWarning)
      4. ``package_root()``           — pip-installed package (internal defaults)
    """
    init_dir = repo_root / _INIT_DIR_NAME
    if (init_dir / "configs").exists():
        return init_dir
    pkg_dir = repo_root / _PKG_DIR_NAME
    if (pkg_dir / "configs").exists():
        return pkg_dir
    legacy_dir = repo_root / _LEGACY_DIR_NAME
    if (legacy_dir / "configs").exists():
        warnings.warn(
            "Using legacy 'collab/' directory for configs. "
            "Run 'agentorch migrate' to move to .agentorch/.",
            DeprecationWarning,
            stacklevel=2,
        )
        return legacy_dir
    return package_root()


def resolve_data_root(repo_root: Path) -> Path:
    """Return the data root directory for artifacts and state.

    Resolution order:
      1. ``<repo_root>/.agentorch/`` — created by ``agentorch init``
      2. ``<repo_root>/agentorch_ctx/`` — source-repo / development layout
      3. ``<repo_root>/collab/``     — legacy layout (DeprecationWarning)
      4. Auto-create ``<repo_root>/.agentorch/`` as a fallback
    """
    init_dir = repo_root / _INIT_DIR_NAME
    if init_dir.is_dir():
        return init_dir
    pkg_in_repo = repo_root / _PKG_DIR_NAME
    if pkg_in_repo.is_dir() and (pkg_in_repo / "configs").exists():
        return pkg_in_repo
    legacy_dir = repo_root / _LEGACY_DIR_NAME
    if legacy_dir.is_dir() and (legacy_dir / "configs").exists():
        warnings.warn(
            "Using legacy 'collab/' directory for data. "
            "Run 'agentorch migrate' to move to .agentorch/.",
            DeprecationWarning,
            stacklevel=2,
        )
        return legacy_dir
    # Auto-create .agentorch/ for pip-installed use without explicit init
    init_dir.mkdir(parents=True, exist_ok=True)
    (init_dir / "artifacts").mkdir(exist_ok=True)
    (init_dir / "state").mkdir(exist_ok=True)
    return init_dir


def artifacts_root(repo_root: Path) -> Path:
    """``<data_root>/artifacts``"""
    return resolve_data_root(repo_root) / "artifacts"


def state_root(repo_root: Path) -> Path:
    """``<data_root>/state``"""
    return resolve_data_root(repo_root) / "state"


def task_artifacts_dir(repo_root: Path, task_id: str) -> Path:
    """``<data_root>/artifacts/tasks/<task_id>``"""
    return artifacts_root(repo_root) / "tasks" / task_id


def task_state_dir(repo_root: Path, task_id: str) -> Path:
    """``<data_root>/state/tasks/<task_id>``"""
    return state_root(repo_root) / "tasks" / task_id


# --- Backward-compatible aliases (kept for callers that haven't migrated) ---


def resolve_support_collab_root(repo_root: Path) -> Path:  # noqa: D401
    """Deprecated alias for :func:`resolve_config_root`."""
    return resolve_config_root(repo_root)


def augment_path_env(
    repo_root: Path, env: dict[str, str] | None = None
) -> dict[str, str]:
    base_env = dict(os.environ if env is None else env)
    current_entries = [
        entry for entry in base_env.get("PATH", "").split(os.pathsep) if entry
    ]
    data_root = resolve_data_root(repo_root)
    candidate_entries = [
        data_root / "scripts",
        repo_root / ".venv" / "bin",
        repo_root / "node_modules" / ".bin",
        repo_root / "bin",
    ]
    prefixed = [str(path) for path in candidate_entries if path.exists()]
    merged = _dedupe_paths([*prefixed, *current_entries])
    base_env["PATH"] = os.pathsep.join(merged)
    return base_env


def _walk_for_repo_root(start: Path) -> Path | None:
    candidate = start
    if candidate.is_file():
        candidate = candidate.parent
    for current in [candidate, *candidate.parents]:
        if _is_repo_root(current):
            return current
    return None


def _is_repo_root(path: Path) -> bool:
    return any((path / marker).exists() for marker in MARKER_FILES)


def _dedupe_paths(entries: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for entry in entries:
        normalized = entry.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped
