"""agentorch init — initialize a repository for agentorch (collab + ctx + instructions).

Also provides shared helpers used by cmd_collab_init and ctx init for generating
per-agent instruction files (CLAUDE.md, AGENTS.md, GEMINI.md, skills, rules, etc.).
"""

from __future__ import annotations

import fcntl
import os
import shutil
import sys
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

# Section markers used to detect/replace agentorch sections in multi-purpose files.
_CTX_SECTION_MARKER = "## agentorch ctx"
_COLLAB_SECTION_MARKER = "## agentorch collab"
_AGENTORCH_SECTION_MARKER = "## agentorch"  # legacy / shared marker

_CONTEXTS_RUN_CONTENT = """\
#!/usr/bin/env bash
# .contexts/run — thin wrapper that delegates to the installed agentorch CLI.
# Kept for backward compatibility with existing tools and skill definitions
# that invoke .contexts/run directly.
#
# Resolution order:
#   1. Installed `agentorch` command (pip / uv) — includes vector if installed with [vector]
#   2. Vector-enabled Python interpreters (for vector search support)
#   3. Source-repo development fallback (PYTHONPATH + python3 -m)
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Helper: try running agentorch_ctx with a given Python interpreter.
# Validates that the path looks like a Python binary before executing.
_try_python() {
  local py="$1"; shift
  local bn
  bn="$(basename "$py")"
  case "$bn" in
    python|python3|python3.*) ;;
    *) return 1 ;;  # reject non-python binaries
  esac
  if "$py" -c "import agentorch_ctx" 2>/dev/null; then
    exec "$py" -m agentorch_ctx ctx "$@"
  fi
  return 1
}

REPO_ROOT="$(dirname "$SCRIPT_DIR")"
export CONTEXTS_HOME="$SCRIPT_DIR/local"

# Priority 0: installed agentorch CLI (most common production case)
if command -v agentorch &>/dev/null; then
  exec agentorch ctx "$@"
fi

# Priority 1: CONTEXTS_VECTOR_PYTHON env var override
if [ -n "$CONTEXTS_VECTOR_PYTHON" ] && [ -x "$CONTEXTS_VECTOR_PYTHON" ]; then
  _try_python "$CONTEXTS_VECTOR_PYTHON" "$@" || true
fi

# Priority 2: saved path written by setup-vector
_vec_path_file="$SCRIPT_DIR/local/vector_python_path"
if [ -f "$_vec_path_file" ]; then
  _saved_python="$(cat "$_vec_path_file")"
  if [ -x "$_saved_python" ]; then
    _try_python "$_saved_python" "$@" || true
  fi
fi

# Priority 3: local .venv-vector/ (repo-root, legacy / manual setup)
_local_venv="$(dirname "$SCRIPT_DIR")/.venv-vector/bin/python"
if [ -x "$_local_venv" ]; then
  _try_python "$_local_venv" "$@" || true
fi

# Priority 4: global ~/.contexts-vector/
_global_venv="$HOME/.contexts-vector/bin/python"
if [ -x "$_global_venv" ]; then
  _try_python "$_global_venv" "$@" || true
fi

# Priority 5: development fallback (source repo)
PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" exec python3 -m agentorch_ctx ctx "$@"
"""

_GITIGNORE_ENTRIES = """
# agentorch generated data (gitignored by agentorch init)
.agentorch/artifacts/
.agentorch/state/
.contexts/local/
.contexts/cache/
.contexts/exports/
.contexts/context.db
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _safe_write_guard(path: Path) -> None:
    """Remove dangling or unexpected symlinks before writing to *path*."""
    if path.is_symlink():
        path.unlink()


def _install_template(
    repo_root: Path,
    dest_relative: str,
    template_path: str,
    *,
    force: bool = False,
    executable: bool = False,
) -> None:
    """Copy a template file to dest_relative under repo_root."""
    src = _TEMPLATES_DIR / template_path
    dst = repo_root / dest_relative

    if dst.exists() and not force:
        print(f"  [skip] {dest_relative} (already exists; use --force to overwrite)")
        return

    if not src.exists():
        print(f"  [warn] template not found: {src}", file=sys.stderr)
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    _safe_write_guard(dst)
    shutil.copy2(src, dst)
    if executable:
        dst.chmod(0o755)
    print(f"  [ok]   {dest_relative}")


def _append_section(
    file_path: Path,
    section_content: str,
    marker: str,
    *,
    force: bool = False,
    default_header: str = "",
) -> None:
    """Append or replace a marked section in a multi-purpose file (CLAUDE.md, AGENTS.md, etc.)."""
    _safe_write_guard(file_path)

    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8")
        if marker in existing:
            if not force:
                print(f"  [skip] {file_path.name} ({marker} already present; use --force)")
                return
            idx = existing.index(marker)
            prefix = existing[:idx].rstrip() + "\n"
            file_path.write_text(prefix + "\n" + section_content, encoding="utf-8")
            print(f"  [ok]   {file_path.name} ({marker} replaced)")
        else:
            with file_path.open("a+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.seek(0)
                current = f.read()
                if marker in current:
                    return
                f.write("\n" + section_content)
            print(f"  [ok]   {file_path.name} ({marker} appended)")
    else:
        header = default_header or f"# {file_path.stem}\n"
        file_path.write_text(header + section_content, encoding="utf-8")
        print(f"  [ok]   {file_path.name} (created)")


def _ensure_contexts_run(repo_root: Path, *, force: bool = False) -> None:
    """Create .contexts/run wrapper and .contexts/local/ directory."""
    contexts_dir = repo_root / ".contexts"
    run_file = contexts_dir / "run"
    local_dir = contexts_dir / "local"

    local_dir.mkdir(parents=True, exist_ok=True)

    if run_file.exists() and not force:
        print("  [skip] .contexts/run (already exists; use --force to overwrite)")
    else:
        _safe_write_guard(run_file)
        run_file.write_text(_CONTEXTS_RUN_CONTENT, encoding="utf-8")
        run_file.chmod(0o755)
        print("  [ok]   .contexts/run")


def _ensure_gitignore(repo_root: Path) -> None:
    """Append agentorch entries to .gitignore if not already present."""
    gi = repo_root / ".gitignore"
    _safe_write_guard(gi)

    with gi.open("a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        existing = f.read()

        existing_lines = {l.strip() for l in existing.splitlines()}
        entries_to_add = []
        for line in _GITIGNORE_ENTRIES.strip().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and stripped not in existing_lines:
                entries_to_add.append(stripped)

        if not entries_to_add:
            return

        f.write("\n# agentorch generated data (gitignored by agentorch init)\n")
        for entry in entries_to_add:
            f.write(f"{entry}\n")
    print("  [ok]   .gitignore (agentorch entries appended)")


def _ensure_repo_root_marker(repo_root: Path) -> None:
    """Ensure AGENTS.md or .git exists as repo root marker."""
    agents_md = repo_root / "AGENTS.md"
    if not agents_md.exists() and not (repo_root / ".git").exists():
        agents_md.write_text(
            "# AGENTS\n\nThis file marks the repository root for agentorch tooling.\n",
            encoding="utf-8",
        )
        print("  [ok]   AGENTS.md created (repo root marker)")


def _run_ctx_db_init(repo_root: Path) -> int:
    """Initialize the context DB via contexts.__main__."""
    saved_argv = sys.argv
    saved_cwd = os.getcwd()
    sys.argv = ["agentorch ctx", "init"]
    os.chdir(str(repo_root))
    try:
        from agentorch_ctx.contexts.__main__ import main as ctx_main

        try:
            result = ctx_main()
            return result if isinstance(result, int) else 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        os.chdir(saved_cwd)
        sys.argv = saved_argv


# ---------------------------------------------------------------------------
# ctx init: context management instructions
# ---------------------------------------------------------------------------


def run_ctx_init(repo_root: Path, *, force: bool = False) -> int:
    """Generate ctx-specific agent instructions and initialize context DB."""
    exit_code = 0

    # 1. Repo root marker
    _ensure_repo_root_marker(repo_root)

    # 2. .contexts/run wrapper + DB init
    _ensure_contexts_run(repo_root, force=force)
    rc = _run_ctx_db_init(repo_root)
    if rc != 0:
        exit_code = rc

    # 3. Agent instruction files — ctx
    print()
    print("  --- ctx: agent instructions ---")

    # Claude Code: skill + rules + CLAUDE.md section
    _install_template(
        repo_root,
        ".claude/skills/agentorch-ctx/SKILL.md",
        "ctx/claude_skill.md",
        force=force,
    )
    _install_template(
        repo_root,
        ".claude/rules/agentorch-ctx.md",
        "ctx/claude_rules.md",
        force=force,
    )
    claude_md_section = (_TEMPLATES_DIR / "ctx" / "claude_md_section.md").read_text(encoding="utf-8")
    _append_section(
        repo_root / "CLAUDE.md",
        claude_md_section,
        _CTX_SECTION_MARKER,
        force=force,
        default_header="# CLAUDE\n",
    )

    # Codex: skill + AGENTS.md section
    _install_template(
        repo_root,
        ".agents/skills/agentorch-ctx/SKILL.md",
        "ctx/codex_skill.md",
        force=force,
    )
    agents_md_section = (_TEMPLATES_DIR / "ctx" / "agents_md_section.md").read_text(encoding="utf-8")
    _append_section(
        repo_root / "AGENTS.md",
        agents_md_section,
        _CTX_SECTION_MARKER,
        force=force,
        default_header="# AGENTS\n",
    )

    # Copilot: instructions file (also reads .claude/skills/ automatically)
    _install_template(
        repo_root,
        ".github/instructions/agentorch-ctx.instructions.md",
        "ctx/copilot_instructions.md",
        force=force,
    )

    # Gemini: GEMINI.md section
    gemini_md_section = (_TEMPLATES_DIR / "ctx" / "gemini_md_section.md").read_text(encoding="utf-8")
    _append_section(
        repo_root / "GEMINI.md",
        gemini_md_section,
        _CTX_SECTION_MARKER,
        force=force,
        default_header="# GEMINI\n",
    )

    # 4. .gitignore
    _ensure_gitignore(repo_root)

    return exit_code


# ---------------------------------------------------------------------------
# collab init: orchestration instructions
# ---------------------------------------------------------------------------


def run_collab_init(repo_root: Path, *, force: bool = False) -> int:
    """Generate collab-specific agent instructions and orchestration configs."""
    # 1. Orchestration configs (delegates to existing cmd_collab_init)
    from agentorch_ctx.cli.cmd_collab_init import run as collab_init_run

    rc = collab_init_run(target_dir=repo_root, force=force)

    # 2. Agent instruction files — collab (Claude Code only)
    print()
    print("  --- collab: agent instructions ---")

    _install_template(
        repo_root,
        ".claude/skills/agentorch-collab/SKILL.md",
        "collab/claude_skill.md",
        force=force,
    )
    _install_template(
        repo_root,
        ".claude/rules/agentorch-collab.md",
        "collab/claude_rules.md",
        force=force,
    )
    collab_md_section = (_TEMPLATES_DIR / "collab" / "claude_md_section.md").read_text(encoding="utf-8")
    _append_section(
        repo_root / "CLAUDE.md",
        collab_md_section,
        _COLLAB_SECTION_MARKER,
        force=force,
        default_header="# CLAUDE\n",
    )

    return rc


# ---------------------------------------------------------------------------
# Full init: both ctx + collab
# ---------------------------------------------------------------------------


def run(target_dir: Path | None = None, *, force: bool = False) -> int:
    """Run both collab init and ctx init for the given directory."""
    repo_root = (target_dir or Path.cwd()).resolve()
    exit_code = 0

    print("=== agentorch init ===")
    print()

    # Step 1: collab init
    print("--- Step 1/2: collab (orchestration configs + instructions) ---")
    rc = run_collab_init(repo_root, force=force)
    if rc != 0:
        exit_code = rc

    print()

    # Step 2: ctx init
    print("--- Step 2/2: ctx (context DB + instructions) ---")
    rc = run_ctx_init(repo_root, force=force)
    if rc != 0:
        exit_code = rc

    print()
    if exit_code == 0:
        print("Repository fully initialized for agentorch.")
        print("  Orchestration configs : .agentorch/configs/")
        print("  Context DB            : .contexts/local/context.db")
        print("  Claude Code skills    : .claude/skills/agentorch-{collab,ctx}/")
        print("  Claude Code rules     : .claude/rules/agentorch-{collab,ctx}.md")
        print("  Codex skill           : .agents/skills/agentorch-ctx/")
        print("  Copilot instructions  : .github/instructions/agentorch-ctx.instructions.md")
        print("  CLAUDE.md / AGENTS.md / GEMINI.md sections appended")
        print()
        print("Next steps:")
        print("  1. Edit .agentorch/configs/providers.json to set your models")
        print("  2. Run: agentorch collab plan --source goal.md")
        print("  3. Run: agentorch ctx search-memory --query <term>")
    return exit_code
