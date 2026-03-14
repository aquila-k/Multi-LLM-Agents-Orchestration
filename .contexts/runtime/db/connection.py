"""SQLite database connection management."""

import sqlite3
from pathlib import Path


def open_db(db_path: Path, read_only: bool = False) -> sqlite3.Connection:
    """
    Open a SQLite database in WAL mode with foreign_keys=ON.

    Sets check_same_thread=False (caller is responsible for thread safety).
    Sets row_factory = sqlite3.Row.
    Runs PRAGMAs: journal_mode=WAL, foreign_keys=ON.

    If read_only is True, opens via URI with '?mode=ro'.
    """
    db_path_str = str(db_path)

    if read_only:
        uri = "file:{}?mode=ro".format(db_path_str)
        conn = sqlite3.connect(
            uri, uri=True, check_same_thread=False, isolation_level=None
        )
    else:
        conn = sqlite3.connect(
            db_path_str, check_same_thread=False, isolation_level=None
        )

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
