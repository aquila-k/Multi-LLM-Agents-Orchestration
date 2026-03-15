"""Policy rule validation."""

POLICY_REQUIRED_FIELDS = ["target_kind", "match_pattern", "enforcement"]
TARGET_KINDS = ("command", "file_operation", "network", "vcs", "tool", "any")
ENFORCEMENT_LEVELS = ("warn", "confirm", "deny")


def validate_policy_payload(payload: dict) -> None:
    """Raises ValueError if target_kind/match_pattern/enforcement missing or invalid."""
    if not isinstance(payload, dict):
        raise ValueError(
            "Policy payload must be a dict, got {}".format(type(payload).__name__)
        )
    for field in POLICY_REQUIRED_FIELDS:
        if field not in payload:
            raise ValueError("Missing required policy field: '{}'".format(field))

    target_kind = payload["target_kind"]
    if target_kind not in TARGET_KINDS:
        raise ValueError(
            "Invalid target_kind '{}'; must be one of: {}".format(
                target_kind, ", ".join(TARGET_KINDS)
            )
        )

    match_pattern = payload["match_pattern"]
    if not isinstance(match_pattern, str) or not match_pattern.strip():
        raise ValueError("match_pattern must be a non-empty string")

    enforcement = payload["enforcement"]
    if enforcement not in ENFORCEMENT_LEVELS:
        raise ValueError(
            "Invalid enforcement '{}'; must be one of: {}".format(
                enforcement, ", ".join(ENFORCEMENT_LEVELS)
            )
        )
