"""
Vector stack availability checks.

Provides is_vector_enabled() for runtime gating,
and check_vector_stack() for doctor diagnostics.
Results are cached per-process.
"""

from __future__ import annotations

import functools
import sqlite3
from pathlib import Path
from typing import Optional


@functools.lru_cache(maxsize=1)
def check_sqlite_vec() -> tuple[bool, str]:
    """Return (ok, version_or_error)."""
    try:
        import sqlite_vec  # type: ignore

        db = sqlite3.connect(":memory:")
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        row = db.execute("SELECT vec_version()").fetchone()
        db.close()
        return True, row[0]
    except ImportError:
        return False, "sqlite_vec not installed"
    except Exception as e:
        return False, str(e)


@functools.lru_cache(maxsize=1)
def check_onnxruntime() -> tuple[bool, str]:
    """Return (ok, version_or_error)."""
    try:
        import onnxruntime  # type: ignore

        return True, onnxruntime.__version__
    except ImportError:
        return False, "onnxruntime not installed"
    except Exception as e:
        return False, str(e)


@functools.lru_cache(maxsize=1)
def check_fastembed(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> tuple[bool, str]:
    """Return (ok, info_or_error). Initializes model (may download on first run)."""
    try:
        from fastembed import TextEmbedding  # type: ignore

        embedder = TextEmbedding(model_name=model_name)
        # Embed one token to confirm model loads
        list(embedder.embed(["hello"]))
        return True, "ok (model={})".format(model_name)
    except ImportError:
        return False, "fastembed not installed"
    except Exception as e:
        return False, str(e)


def load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """
    Attempt to load sqlite-vec extension into an existing connection.
    Returns True on success, False on failure (logs nothing — caller decides).
    """
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def is_vector_enabled(conn: Optional[sqlite3.Connection] = None) -> bool:
    """
    Quick runtime check: is sqlite-vec loadable AND does the DB show enabled=1?
    conn is optional — without it, only checks the stack (no DB check).
    """
    ok, _ = check_sqlite_vec()
    if not ok:
        return False
    if conn is None:
        return True
    try:
        row = conn.execute(
            "SELECT enabled FROM vector_index_state WHERE index_name = 'default'"
        ).fetchone()
        return bool(row and row[0])
    except Exception:
        return False


def full_stack_report(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> dict:
    """
    Run all checks and return a structured dict for vector-doctor output.
    Does NOT cache fastembed (it's slow and only called from doctor).
    """
    sq_ok, sq_info = check_sqlite_vec()
    ort_ok, ort_info = check_onnxruntime()
    fe_ok, fe_info = check_fastembed.__wrapped__(model_name)  # bypass lru_cache

    import sys

    python_ok = sys.version_info >= (3, 12)
    python_ver = "{}.{}.{}".format(*sys.version_info[:3])

    return {
        "python": {"ok": python_ok, "version": python_ver},
        "sqlite_vec": {"ok": sq_ok, "info": sq_info},
        "onnxruntime": {"ok": ort_ok, "info": ort_info},
        "fastembed": {"ok": fe_ok, "info": fe_info},
        "profile": "vector-enabled" if (sq_ok and ort_ok and fe_ok) else "core",
    }
