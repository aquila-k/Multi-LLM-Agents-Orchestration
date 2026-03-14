"""Entry type definitions, payload validation, and mutation classification."""

ENTRY_TYPES = (
    "project_profile",
    "task_snapshot",
    "session_snapshot",
    "decision",
    "episode",
    "procedural_rule",
)

REQUIRED_FIELDS = {
    "project_profile": ["goal"],
    "task_snapshot": ["task_goal"],
    "session_snapshot": ["session_goal"],
    "decision": ["decision"],
    "episode": ["observation"],
    "procedural_rule": ["name"],
}

DEFAULT_LOAD_POLICY = {
    "project_profile": "always",
    "task_snapshot": "on_task_start",
    "session_snapshot": "on_session_resume",
    "decision": "on_task_start",
    "episode": "on_explicit_search",
    "procedural_rule": "on_task_start",
}


def validate_payload(type_: str, payload: dict) -> None:
    """Raises ValueError with a descriptive message if validation fails."""
    if type_ not in ENTRY_TYPES:
        raise ValueError("Unknown entry type: {}".format(type_))
    if not isinstance(payload, dict):
        raise ValueError(
            "Payload must be a dict, got {}".format(type(payload).__name__)
        )
    required = REQUIRED_FIELDS.get(type_, [])
    for field in required:
        if field not in payload:
            raise ValueError(
                "Missing required field '{}' for entry type '{}'".format(field, type_)
            )
        if not isinstance(payload[field], str):
            raise ValueError(
                "Field '{}' must be a string, got {}".format(
                    field, type(payload[field]).__name__
                )
            )
        if not payload[field].strip():
            raise ValueError(
                "Field '{}' must not be empty for entry type '{}'".format(field, type_)
            )


def mutation_class(type_: str, scope_level: str) -> str:
    """
    Returns 'auto_activate' or 'proposal_required'.

    Rules:
      episode -> always auto_activate
      task_snapshot, session_snapshot -> auto_activate at task/session scope
      decision, procedural_rule -> auto_activate at task/session; proposal_required at project/branch
      project_profile -> always proposal_required
    """
    if type_ == "episode":
        return "auto_activate"

    if type_ in ("task_snapshot", "session_snapshot"):
        if scope_level in ("task", "session"):
            return "auto_activate"
        return "proposal_required"

    if type_ in ("decision", "procedural_rule"):
        if scope_level in ("task", "session"):
            return "auto_activate"
        return "proposal_required"

    if type_ == "project_profile":
        return "proposal_required"

    return "proposal_required"
