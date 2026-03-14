from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MARKER_FILES = ("AGENTS.md", ".git")


@dataclass(frozen=True)
class RuntimePaths:
    repo_root: Path
    support_collab_root: Path
    script_path: Path


def resolve_runtime_paths(
    *,
    start_dir: Path | None = None,
    explicit_root: Path | None = None,
) -> RuntimePaths:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run"
    repo_root = resolve_repo_root(start_dir=start_dir, explicit_root=explicit_root)
    support_collab_root = resolve_support_collab_root(repo_root)
    return RuntimePaths(
        repo_root=repo_root,
        support_collab_root=support_collab_root,
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
    search_roots.append(Path(__file__).resolve().parents[2])

    for candidate in search_roots:
        resolved = _walk_for_repo_root(candidate)
        if resolved is not None:
            return resolved
    return Path(__file__).resolve().parents[2]


def resolve_support_collab_root(repo_root: Path) -> Path:
    workspace_collab_root = repo_root / "collab"
    if (workspace_collab_root / "configs").exists():
        return workspace_collab_root
    return Path(__file__).resolve().parents[1]


def augment_path_env(
    repo_root: Path, env: dict[str, str] | None = None
) -> dict[str, str]:
    base_env = dict(os.environ if env is None else env)
    current_entries = [
        entry for entry in base_env.get("PATH", "").split(os.pathsep) if entry
    ]
    candidate_entries = [
        repo_root / "collab" / "scripts",
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
