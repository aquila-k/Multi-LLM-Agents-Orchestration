"""Shared error classes for the .contexts runtime."""


class ContextsError(Exception):
    """Base error for all .contexts operations."""

    code = "UNKNOWN"


class NotInitialized(ContextsError):
    code = "NOT_INITIALIZED"


class NotFound(ContextsError):
    code = "NOT_FOUND"


class ConflictError(ContextsError):
    code = "CONFLICT"

    def __init__(self, msg, expected=None, actual=None, entry_id=None):
        super().__init__(msg)
        self.expected = expected
        self.actual = actual
        self.entry_id = entry_id


class InvalidArg(ContextsError):
    code = "INVALID_ARG"


class InvalidPayload(ContextsError):
    code = "INVALID_PAYLOAD"


class LockTimeout(ContextsError):
    code = "LOCK_TIMEOUT"


class DBError(ContextsError):
    code = "DB_ERROR"


class ApprovalRequired(ContextsError):
    code = "APPROVAL_REQUIRED"
