#!/usr/bin/env python3
"""task_search.py — Task discovery and management for canonical task root.

Commands:
  search   Search tasks by query text across .tmp/task/*/task-index.json
  validate Validate a task-name against canonical naming rules
  enrich   Add/update search metadata (aliases, keywords, summary) in task-index.json
  migrate  Enumerate tasks in legacy root (.tmp/agent-collab/tasks/) for migration

Usage:
  python3 task_search.py search --query <text> [--tasks-root <dir>] [--top N] [--threshold F]
  python3 task_search.py validate --name <task-name>
  python3 task_search.py enrich --task-root <dir> [--aliases <str>] [--keywords <str>] [--summary <str>]
  python3 task_search.py migrate [--tasks-root <dir>]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Task name validation ──────────────────────────────────────────────────────

NAME_MIN_LEN = 16
NAME_MAX_LEN = 72
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def task_name_valid(name: str) -> tuple[bool, str]:
    """Returns (is_valid, reason)."""
    if len(name) < NAME_MIN_LEN:
        return False, f"too short ({len(name)} < {NAME_MIN_LEN})"
    if len(name) > NAME_MAX_LEN:
        return False, f"too long ({len(name)} > {NAME_MAX_LEN})"
    if not NAME_PATTERN.match(name):
        return False, "must be lowercase alphanum+hyphen, no leading/trailing hyphen"
    return True, "ok"


# ── Task index I/O ────────────────────────────────────────────────────────────


def load_task_index(task_root: Path) -> Optional[dict]:
    """Load task-index.json from task root, or None if missing/invalid."""
    idx_path = task_root / "task-index.json"
    if not idx_path.is_file():
        return None
    try:
        with open(idx_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def save_task_index(task_root: Path, data: dict) -> None:
    """Atomically save task-index.json."""
    idx_path = task_root / "task-index.json"
    tmp_path = idx_path.with_suffix(".partial")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, idx_path)


# ── Search ────────────────────────────────────────────────────────────────────


def _score_task(data: dict, query_tokens: list[str]) -> float:
    """Score a task against query tokens. Higher = better match."""
    search_meta = data.get("search", {}) if isinstance(data.get("search"), dict) else {}

    # Collect searchable text fields
    texts = []
    task_name = data.get("task_name", "")
    if task_name:
        texts.append(task_name)

    summary = search_meta.get("summary", "")
    if summary:
        texts.append(summary)

    keywords = search_meta.get("keywords", [])
    if isinstance(keywords, list):
        texts.extend(str(k) for k in keywords)
    elif isinstance(keywords, str):
        texts.extend(k.strip() for k in keywords.split(",") if k.strip())

    aliases = search_meta.get("aliases", [])
    if isinstance(aliases, list):
        texts.extend(str(a) for a in aliases)
    elif isinstance(aliases, str):
        texts.extend(a.strip() for a in aliases.split(",") if a.strip())

    # Build normalized corpus
    corpus = " ".join(texts).lower()

    if not corpus or not query_tokens:
        return 0.0

    # Simple token-overlap score
    matched = sum(1 for t in query_tokens if t in corpus)
    score = matched / len(query_tokens)

    # Boost for exact task-name match
    if task_name.lower() in " ".join(query_tokens):
        score = min(1.0, score + 0.3)

    return score


def cmd_search(args: argparse.Namespace) -> int:
    tasks_root = (
        Path(args.tasks_root)
        if args.tasks_root
        else (_detect_repo_root() / ".tmp" / "task")
    )

    if not tasks_root.is_dir():
        print(f"[warn] tasks root not found: {tasks_root}", file=sys.stderr)
        return 0

    query = args.query.strip()
    if not query:
        print("[error] --query must not be empty", file=sys.stderr)
        return 1

    query_tokens = query.lower().split()
    threshold = float(args.threshold) if args.threshold else 0.3
    top_n = int(args.top) if args.top else 5

    results = []
    for task_dir in sorted(tasks_root.iterdir()):
        if not task_dir.is_dir():
            continue
        data = load_task_index(task_dir)
        if data is None:
            # Check if directory looks like a task root (has plan/impl/review)
            if not (task_dir / "plan").is_dir() and not (task_dir / "state").is_dir():
                continue
            data = {"task_name": task_dir.name}

        score = _score_task(data, query_tokens)
        if score >= threshold:
            results.append(
                {
                    "task_name": data.get("task_name", task_dir.name),
                    "task_root": str(task_dir),
                    "score": round(score, 3),
                    "summary": (
                        data.get("search", {}).get("summary", "")
                        if isinstance(data.get("search"), dict)
                        else ""
                    ),
                    "updated_at": data.get("updated_at", ""),
                    "latest_run_id": data.get("latest_run_id", ""),
                }
            )

    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:top_n]

    if not results:
        print(f"No tasks found matching: {query!r} (threshold={threshold})")
        return 0

    print(f"Found {len(results)} task(s) matching: {query!r}\n")
    for r in results:
        print(f"  score={r['score']:.3f}  name={r['task_name']}")
        print(f"          root={r['task_root']}")
        if r["summary"]:
            print(f"          summary={r['summary'][:80]}")
        if r["updated_at"]:
            print(f"          updated={r['updated_at']}")
        print()

    return 0


# ── Validate ──────────────────────────────────────────────────────────────────


def cmd_validate(args: argparse.Namespace) -> int:
    name = args.name
    valid, reason = task_name_valid(name)
    if valid:
        print(f"[ok] '{name}' is a valid task name")
        return 0
    else:
        print(f"[error] '{name}' is not valid: {reason}", file=sys.stderr)
        return 1


# ── Enrich ────────────────────────────────────────────────────────────────────


def cmd_enrich(args: argparse.Namespace) -> int:
    task_root = Path(args.task_root)
    if not task_root.is_dir():
        print(f"[error] task root not found: {task_root}", file=sys.stderr)
        return 1

    data = load_task_index(task_root)
    if data is None:
        # Create minimal index if missing
        data = {
            "task_name": task_root.name,
            "created_at": _iso_now(),
        }

    data.setdefault("search", {})
    search = data["search"]
    if not isinstance(search, dict):
        search = {}
        data["search"] = search

    changed = False

    if args.summary:
        search["summary"] = args.summary.strip()
        changed = True

    if args.keywords:
        kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
        existing = set(
            search.get("keywords", [])
            if isinstance(search.get("keywords"), list)
            else []
        )
        merged = sorted(existing | set(kws))
        search["keywords"] = merged
        changed = True

    if args.aliases:
        als = [a.strip() for a in args.aliases.split(",") if a.strip()]
        existing = set(
            search.get("aliases", []) if isinstance(search.get("aliases"), list) else []
        )
        merged = sorted(existing | set(als))
        search["aliases"] = merged
        changed = True

    if changed:
        data["updated_at"] = _iso_now()
        save_task_index(task_root, data)
        print(f"[ok] Enriched: {task_root / 'task-index.json'}")
        if args.summary:
            print(f"     summary: {search['summary'][:80]}")
        if args.keywords:
            print(f"     keywords: {search.get('keywords', [])}")
        if args.aliases:
            print(f"     aliases: {search.get('aliases', [])}")
    else:
        print(
            "[warn] Nothing to update (no --summary, --keywords, or --aliases provided)"
        )

    return 0


# ── Migrate ───────────────────────────────────────────────────────────────────


def cmd_migrate(args: argparse.Namespace) -> int:
    """List tasks in legacy root for migration (read-only; no auto-move)."""
    if args.tasks_root:
        canonical_root = Path(args.tasks_root)
        # Derive repo root: .tmp/task → .tmp → repo_root
        repo_root = canonical_root.parent.parent
    else:
        repo_root = _detect_repo_root()
        canonical_root = repo_root / ".tmp" / "task"
    legacy_roots = [
        repo_root / ".tmp" / "agent-collab" / "tasks",
        repo_root / ".tmp" / "agent-collab",
    ]

    print("=== Migration Report (read-only) ===\n")
    print(f"Canonical root: {canonical_root}")
    print()

    found_any = False
    for legacy_root in legacy_roots:
        if not legacy_root.is_dir():
            continue
        for d in sorted(legacy_root.iterdir()):
            if not d.is_dir():
                continue
            # Skip if it looks like a phase dir (plan/task/review), not a task container
            if d.name in {"plan", "task", "review", "state", "sessions"}:
                continue
            task_name = d.name
            valid, reason = task_name_valid(task_name)
            canonical_target = canonical_root / task_name
            exists_canonical = canonical_target.is_dir()
            status = "already-migrated" if exists_canonical else "pending"

            print(f"  [{status}] {task_name}")
            print(f"    legacy:    {d}")
            if not valid:
                print(f"    [warn] name not valid for canonical: {reason}")
            print(f"    canonical: {canonical_target}")
            print()
            found_any = True

    if not found_any:
        print("No tasks found in legacy roots.")

    print("Note: Migration is manual. Copy the task directory to the canonical root")
    print("      and update task-index.json to reflect the new path.")
    return 0


# ── Helpers ───────────────────────────────────────────────────────────────────


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _detect_repo_root() -> Path:
    """Find repo root via git, falling back to cwd."""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except Exception:
        return Path.cwd()


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="task_search.py",
        description="Task discovery and management for canonical task root (.tmp/task/)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Search tasks by query text")
    p_search.add_argument("--query", required=True, help="Search query string")
    p_search.add_argument(
        "--tasks-root", default="", help="Repo root (default: auto-detect via git)"
    )
    p_search.add_argument("--top", default="5", help="Max results to show (default: 5)")
    p_search.add_argument(
        "--threshold", default="0.3", help="Min score threshold 0.0-1.0 (default: 0.3)"
    )

    # validate
    p_validate = sub.add_parser("validate", help="Validate a task-name")
    p_validate.add_argument("--name", required=True, help="Task name to validate")

    # enrich
    p_enrich = sub.add_parser(
        "enrich", help="Add/update search metadata in task-index.json"
    )
    p_enrich.add_argument("--task-root", required=True, help="Task root directory")
    p_enrich.add_argument("--summary", default="", help="Short description of the task")
    p_enrich.add_argument("--keywords", default="", help="Comma-separated keywords")
    p_enrich.add_argument("--aliases", default="", help="Comma-separated aliases")

    # migrate
    p_migrate = sub.add_parser(
        "migrate", help="List legacy tasks for migration (read-only)"
    )
    p_migrate.add_argument(
        "--tasks-root", default="", help="Repo root (default: auto-detect via git)"
    )

    args = parser.parse_args()

    dispatch = {
        "search": cmd_search,
        "validate": cmd_validate,
        "enrich": cmd_enrich,
        "migrate": cmd_migrate,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
