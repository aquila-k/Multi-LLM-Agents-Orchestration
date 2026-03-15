"""Scope level inference and scope-ref construction."""

SCOPE_LEVELS = ("project", "branch", "task", "session")


def infer_scope_level(session_id, task_id, branch_ref) -> str:
    """Most-specific-wins: session > task > branch > project."""
    if session_id:
        return "session"
    if task_id:
        return "task"
    if branch_ref:
        return "branch"
    return "project"


def compute_scope_ref(
    scope_level: str, project_id: str, branch_ref=None, task_id=None, session_id=None
) -> str:
    """
    Build a scope_ref string from the scope level and identifiers.

    project  -> "project/{project_id}"
    branch   -> "branch/{branch_ref}"
    task     -> "task/{task_id}"
    session  -> "session/{session_id}"

    Raises ValueError if the required identifier for the scope level is missing.
    """
    if scope_level == "project":
        if not project_id:
            raise ValueError("project_id is required for scope_level 'project'")
        return "project/{}".format(project_id)
    if scope_level == "branch":
        if not branch_ref:
            raise ValueError("branch_ref is required for scope_level 'branch'")
        return "branch/{}".format(branch_ref)
    if scope_level == "task":
        if not task_id:
            raise ValueError("task_id is required for scope_level 'task'")
        return "task/{}".format(task_id)
    if scope_level == "session":
        if not session_id:
            raise ValueError("session_id is required for scope_level 'session'")
        return "session/{}".format(session_id)
    raise ValueError("Unknown scope_level: {}".format(scope_level))


def parse_scope_ref(scope_ref: str):
    """
    Returns (scope_level, scope_id) from a scope_ref string.
    Raises ValueError if the format is invalid.
    """
    if not scope_ref or "/" not in scope_ref:
        raise ValueError("Malformed scope_ref: {}".format(scope_ref))
    parts = scope_ref.split("/", 1)
    level = parts[0]
    scope_id = parts[1]
    if level not in SCOPE_LEVELS:
        raise ValueError("Unknown scope level in scope_ref: {}".format(level))
    if not scope_id:
        raise ValueError("Empty scope_id in scope_ref: {}".format(scope_ref))
    return (level, scope_id)


def scope_level_of_ref(scope_ref: str) -> str:
    """Returns scope_level string from a scope_ref string."""
    level, _ = parse_scope_ref(scope_ref)
    return level


def logical_key(record_family: str, type_: str, key: str, scope_ref: str) -> str:
    """Build a logical key string for uniqueness tracking."""
    return "{}:{}:{}:{}".format(record_family, type_, key, scope_ref)
