"""agentorch bootstrap — check and guide global environment setup."""

from __future__ import annotations

import shutil
from pathlib import Path

_NVM_PATTERN = Path.home() / ".nvm" / "versions" / "node"

_INSTALL_INSTRUCTIONS = {
    "pyyaml": "pip install pyyaml",
    "gemini": "npm install -g @google/gemini-cli  # or: npx @google/gemini-cli",
    "codex": "npm install -g @openai/codex",
    "copilot": "npm install -g @github/copilot  # requires GitHub Copilot access",
}

_CRITICAL = {"pyyaml"}  # at least one provider CLI is needed too.


def _find_nvm_bin(name: str) -> Path | None:
    """Look for <name> under ~/.nvm/versions/node/*/bin/ with package fallback."""
    if not _NVM_PATTERN.is_dir():
        return None

    # Same fallback shape as doctor: prefer NVM bin entries when PATH misses them.
    nvm_candidates = sorted(_NVM_PATTERN.glob(f"*/bin/{name}"))
    if nvm_candidates:
        return nvm_candidates[-1].expanduser().resolve()

    # Optional package-style fallback used by some npm-installed CLIs.
    for pkg_dir in sorted(
        _NVM_PATTERN.glob(f"*/lib/node_modules/*/{name}"), reverse=True
    ):
        loader = pkg_dir / "npm-loader.js"
        if loader.exists():
            return loader.resolve()
    return None


def _check_pyyaml() -> tuple[bool, str]:
    try:
        import yaml  # type: ignore[import-not-found]  # noqa: F401

        return True, "importable"
    except ImportError:
        return False, "not installed"
    except Exception as exc:
        return False, f"import failed: {exc}"


def _check_cli(name: str) -> tuple[bool, str]:
    path = shutil.which(name)
    if path:
        return True, path
    nvm_path = _find_nvm_bin(name)
    if nvm_path:
        return True, f"{nvm_path} (via ~/.nvm)"
    return False, "not found"


def run(verbose: bool = False) -> int:
    """Run bootstrap checks and print guidance. Return 0 if critical deps exist."""
    print("agentorch bootstrap — checking environment")
    print()

    results: dict[str, tuple[bool, str]] = {}

    pyyaml_ok, pyyaml_detail = _check_pyyaml()
    results["pyyaml"] = (pyyaml_ok, pyyaml_detail)
    print(f"  {'[OK]  ' if pyyaml_ok else '[FAIL]'} pyyaml: {pyyaml_detail}")

    print()
    print("  Provider CLIs:")

    cli_results: dict[str, tuple[bool, str]] = {}
    for cli in ("gemini", "codex", "copilot"):
        ok, detail = _check_cli(cli)
        cli_results[cli] = (ok, detail)
        results[cli] = (ok, detail)
        print(f"  {'[OK]  ' if ok else '[MISS]'} {cli}: {detail}")

    print()
    installed = [name for name, (ok, _) in results.items() if ok]
    missing = [name for name, (ok, _) in results.items() if not ok]
    print(f"Summary: installed={', '.join(installed) if installed else '(none)'}")
    print(f"Summary: missing={', '.join(missing) if missing else '(none)'}")

    any_cli = any(ok for ok, _ in cli_results.values())
    critical_ok = all(results[dep][0] for dep in _CRITICAL) and any_cli
    all_ok = not missing

    if all_ok:
        print("All dependencies present. No action needed.")
        return 0

    print()
    print("Action needed:")
    if not results["pyyaml"][0]:
        print(f"  - Install pyyaml:  {_INSTALL_INSTRUCTIONS['pyyaml']}")
    for cli in ("gemini", "codex", "copilot"):
        if not cli_results[cli][0]:
            print(f"  - Install {cli}:  {_INSTALL_INSTRUCTIONS[cli]}")

    if verbose:
        print()
        print(
            "Verbose: critical deps require `pyyaml` and at least one of "
            "`gemini`, `codex`, `copilot`."
        )
        print(f"Verbose: NVM scan root = {_NVM_PATTERN}")

    if not critical_ok:
        print()
        print("ERROR: critical dependencies missing (pyyaml and/or provider CLI).")
        return 1

    print()
    print("Note: optional provider CLIs are missing but core deps are satisfied.")
    return 0
