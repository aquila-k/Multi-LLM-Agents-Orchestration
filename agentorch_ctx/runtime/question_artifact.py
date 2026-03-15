"""Question artifact helpers for async clarification."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_question_artifact(
    *,
    task_id: str,
    phase: str,
    step: str = "",
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Build a question artifact for async clarification.

    Each question dict should contain at minimum ``text`` and ``reason``.
    Optional keys: ``choices`` (list of dicts with label/description/recommended),
    ``allowFreeform`` (bool, default True).

    IDs are auto-assigned as Q001, Q002, etc. if not provided.
    """
    normalized_questions: list[dict[str, Any]] = []
    for idx, q in enumerate(questions, start=1):
        question_id = q.get("id") or f"Q{idx:03d}"
        entry: dict[str, Any] = {
            "id": question_id,
            "text": str(q.get("text", "")),
            "reason": str(q.get("reason", "")),
        }
        if "choices" in q and isinstance(q["choices"], list):
            entry["choices"] = q["choices"]
        entry["allowFreeform"] = bool(q.get("allowFreeform", True))
        normalized_questions.append(entry)

    return {
        "schemaVersion": "1.0.0",
        "taskId": task_id,
        "phase": phase,
        "step": step,
        "generatedAt": _isoformat(datetime.now(timezone.utc)),
        "questions": normalized_questions,
        "status": "pending",
    }


def ingest_answered_questions(
    *,
    question_artifact: dict[str, Any],
    answers: dict[str, str],
) -> dict[str, Any]:
    """
    Apply user answers to a question artifact, returning updated artifact.

    ``answers`` maps question ID → answer text.
    """
    updated = dict(question_artifact)
    now = _isoformat(datetime.now(timezone.utc))
    updated_questions: list[dict[str, Any]] = []
    answered_count = 0

    for q in updated.get("questions", []):
        q_copy = dict(q)
        qid = str(q_copy.get("id", ""))
        if qid in answers:
            q_copy["answer"] = answers[qid]
            q_copy["answeredAt"] = now
            answered_count += 1
        elif q_copy.get("answer"):
            answered_count += 1
        updated_questions.append(q_copy)

    updated["questions"] = updated_questions
    total = len(updated_questions)
    if answered_count >= total and total > 0:
        updated["status"] = "answered"
    elif answered_count > 0:
        updated["status"] = "partially_answered"
    else:
        updated["status"] = "pending"

    return updated


def _isoformat(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
