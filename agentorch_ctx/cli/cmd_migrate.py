"""agentorch migrate — migrate from legacy collab/ layout to .agentorch/."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def run(target_dir: Path | None = None, *, dry_run: bool = False) -> int:
    """Migrate a repository from the legacy ``collab/`` layout to ``.agentorch/``.

    Returns 0 on success, 1 on error.
    """
    repo_root = (target_dir or Path.cwd()).resolve()
    legacy_dir = repo_root / "collab"

    if not legacy_dir.is_dir():
        print("No legacy 'collab/' directory found. Nothing to migrate.")
        return 0

    if not (legacy_dir / "configs").exists():
        print(
            "error: 'collab/' exists but lacks 'configs/' — "
            "doesn't look like a collab runtime directory.",
            file=sys.stderr,
        )
        return 1

    agentorch_dir = repo_root / ".agentorch"

    # Detect if .agentorch/ already exists
    if agentorch_dir.is_dir() and (agentorch_dir / "configs").exists():
        print(
            ".agentorch/ already exists with configs. "
            "Migration would overwrite existing configuration.",
            file=sys.stderr,
        )
        print("If you want to proceed, remove .agentorch/ first.", file=sys.stderr)
        return 1

    # Plan migration steps
    steps: list[tuple[str, Path, Path]] = []

    # Configs: collab/configs/user/ → .agentorch/configs/
    legacy_user_configs = legacy_dir / "configs" / "user"
    if legacy_user_configs.is_dir():
        for config_file in sorted(legacy_user_configs.glob("*.json")):
            steps.append(
                (
                    "copy config",
                    config_file,
                    agentorch_dir / "configs" / config_file.name,
                )
            )
    else:
        # Legacy may have configs directly under collab/configs/
        legacy_configs = legacy_dir / "configs"
        for config_file in sorted(legacy_configs.glob("*.json")):
            steps.append(
                (
                    "copy config",
                    config_file,
                    agentorch_dir / "configs" / config_file.name,
                )
            )

    # Artifacts: collab/artifacts/ → .agentorch/artifacts/
    legacy_artifacts = legacy_dir / "artifacts"
    if legacy_artifacts.is_dir():
        steps.append(
            (
                "move artifacts",
                legacy_artifacts,
                agentorch_dir / "artifacts",
            )
        )

    # State: collab/state/ → .agentorch/state/
    legacy_state = legacy_dir / "state"
    if legacy_state.is_dir():
        steps.append(
            (
                "move state",
                legacy_state,
                agentorch_dir / "state",
            )
        )

    if not steps:
        print("No migratable data found in collab/.")
        return 0

    # Print plan
    print(f"Migration plan: collab/ → .agentorch/  ({len(steps)} steps)")
    print()
    for action, src, dst in steps:
        print(
            f"  {action}: {src.relative_to(repo_root)} → {dst.relative_to(repo_root)}"
        )

    if dry_run:
        print()
        print("(dry-run mode — no changes made)")
        return 0

    # Execute migration
    print()
    agentorch_dir.mkdir(parents=True, exist_ok=True)
    (agentorch_dir / "configs").mkdir(exist_ok=True)

    for action, src, dst in steps:
        if action == "copy config":
            shutil.copy2(src, dst)
            print(f"  [ok] {dst.relative_to(repo_root)}")
        elif action in ("move artifacts", "move state"):
            if dst.exists():
                print(
                    f"  [skip] {dst.relative_to(repo_root)} already exists",
                    file=sys.stderr,
                )
            else:
                shutil.move(str(src), str(dst))
                print(f"  [ok] {dst.relative_to(repo_root)}")

    # Write .agentorch/.gitignore
    inner_gi = agentorch_dir / ".gitignore"
    if not inner_gi.exists():
        inner_gi.write_text("artifacts/\nstate/\n", encoding="utf-8")
        print(f"  [ok] {inner_gi.relative_to(repo_root)}")

    # Update repo .gitignore
    root_gi = repo_root / ".gitignore"
    existing = root_gi.read_text(encoding="utf-8") if root_gi.exists() else ""
    gitignore_additions = []
    if ".agentorch/artifacts/" not in existing:
        gitignore_additions.append(".agentorch/artifacts/")
    if ".agentorch/state/" not in existing:
        gitignore_additions.append(".agentorch/state/")
    if gitignore_additions:
        with root_gi.open("a", encoding="utf-8") as handle:
            handle.write("\n# agentorch-ctx generated data\n")
            for entry in gitignore_additions:
                handle.write(f"{entry}\n")
        print("  [ok] .gitignore updated")

    print()
    print("Migration complete.")
    print(f"  Legacy 'collab/' directory has been left intact as a backup.")
    print(f"  Once you confirm everything works, you may archive it:")
    print(f"    mv collab/ .archive/collab-legacy/")
    return 0
