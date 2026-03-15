"""ID and timestamp generators."""

import uuid
from datetime import datetime, timezone


def new_entry_id() -> str:
    """Generate an entry ID: 'e_' + 32 hex chars from UUID4."""
    return "e_" + uuid.uuid4().hex


def new_event_id() -> str:
    """Generate an event ID: 'ev_' + 32 hex chars from UUID4."""
    return "ev_" + uuid.uuid4().hex


def now_iso() -> str:
    """Return current UTC time as ISO8601 without microseconds: '2026-03-12T04:00:00Z'."""
    dt = datetime.now(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
