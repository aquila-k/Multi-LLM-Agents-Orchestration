from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypeAlias, TypedDict

JsonPrimitive: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]

FactStatus = Literal["declared", "observed", "verified", "superseded"]


class KnownInformationEntry(TypedDict, total=False):
    key: str
    value: JsonValue
    status: FactStatus
    source: str
    updated_at: str
    affects: list[str]
    supersedes: str


class ControllerState(TypedDict, total=False):
    task_id: str
    active_phase: str
    active_step: str
    active_strategy: str
    current_status: str
    last_successful_artifact_refs: list[str]
    pending_approval_state: ApprovalState
    retry_counters: dict[str, int]
    resume_selectors: dict[str, JsonValue]
    latest_shell_digest_refs: list[str]
    blocked_reason: str
    failure_class: str
    resume_hint: str
    updated_at: str


class ApprovalState(TypedDict, total=False):
    required: bool
    status: Literal["pending", "approved", "rejected", "not_required"]
    marker: str
    updated_at: str


class ResumeCursor(TypedDict, total=False):
    phase: str
    strategy: str
    step: str
    attempt: str
    run: str
    artifact_ref: str
    updated_at: str


class EnvironmentSignature(TypedDict, total=False):
    cwd: str
    platform: str
    python: str
    shell: str
    timestamp: str


@dataclass(frozen=True)
class TaskStatePaths:
    task_root: Path
    controller_state: Path
    known_information: Path
    environment_signature: Path
    approval_state: Path
    resume_cursor: Path


@dataclass(frozen=True)
class TaskStateSnapshot:
    paths: TaskStatePaths
    controller_state: ControllerState
    known_information: list[KnownInformationEntry]
    environment_signature: EnvironmentSignature
    approval_state: ApprovalState
    resume_cursor: ResumeCursor


class StateStore(Protocol):
    """Mutable task state contract for the self-contained collab runtime."""

    def ensure_task(self, task_id: str) -> TaskStatePaths:
        """Create or resolve the canonical mutable state paths for a task."""

    def load_task(self, task_id: str) -> TaskStateSnapshot | None:
        """Load the full mutable state snapshot for a task, if it exists."""

    def write_controller_state(self, task_id: str, state: ControllerState) -> Path:
        """Atomically replace the controller state for a task."""

    def write_known_information(
        self, task_id: str, entries: list[KnownInformationEntry]
    ) -> Path:
        """Atomically replace the task-local known information ledger."""

    def write_environment_signature(
        self, task_id: str, signature: EnvironmentSignature
    ) -> Path:
        """Persist the environment signature used for resume safety."""

    def write_approval_state(self, task_id: str, state: ApprovalState) -> Path:
        """Persist approval gating state for stop-and-confirm flows."""

    def write_resume_cursor(self, task_id: str, cursor: ResumeCursor) -> Path:
        """Persist the canonical resume selector for later continuation."""

    def upsert_task_registry_entry(
        self, task_id: str, payload: dict[str, JsonValue]
    ) -> Path:
        """Update the global task registry without depending on conversation state."""
