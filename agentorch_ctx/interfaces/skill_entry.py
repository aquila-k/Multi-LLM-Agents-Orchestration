from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

PhaseName = Literal["plan", "impl", "review", "harden"]
WorkflowIntent = Literal["plan", "impl", "review", "harden", "resume"]
SourceKind = Literal["markdown", "json"]
OutputMode = Literal[
    "patch",
    "create_file",
    "full_file",
    "mixed",
    "rename_file",
    "delete_file",
    "binary_patch",
    "report_only",
]


class SourceReference(TypedDict):
    path: str
    kind: SourceKind


class DispatchSelectors(TypedDict, total=False):
    phase: PhaseName
    strategy: str
    step: str
    resume_from: str
    approval_continuation: str


class PhaseOptions(TypedDict, total=False):
    with_harden: bool
    auto_advance: bool
    budget_profile_ref: str


class TargetSpec(TypedDict, total=False):
    paths: list[str]
    globs: list[str]
    summary: str


class ApprovalRequestSpec(TypedDict, total=False):
    schemaVersion: str
    taskId: str
    phase: str
    stepId: str
    operationType: str
    scope: dict[str, Any]
    rationale: str
    impact: str
    riskLevel: Literal["low", "medium", "high", "critical"]
    preApprovedInPlan: bool
    preApprovalRef: str


class ConstraintSpec(TypedDict, total=False):
    hard: list[str]
    soft: list[str]
    approvals_required: list[ApprovalRequestSpec]
    disallowed_paths: list[str]


class ArtifactDestinations(TypedDict, total=False):
    task_root: str
    intake_dir: str
    request_dir: str
    response_dir: str
    state_dir: str


class OperatorContext(TypedDict, total=False):
    summary: str
    requested_by: str
    session_hint: str
    approval_mode: Literal["fail_closed", "continue_if_approved"]


class AssemblyOptions(TypedDict, total=False):
    prompt_version: str
    schema_version: str
    concise_shell_summary: bool


class OutputSpec(TypedDict):
    preferred_mode: OutputMode
    allowed_modes: list[OutputMode]
    operations_required: bool


class RequestMetadata(TypedDict):
    created_at: str
    source_canonicalized_at: str
    host: str
    cwd: str


class CanonicalDispatchRequest(TypedDict):
    task_id: str
    source: SourceReference
    workflow_intent: WorkflowIntent
    summary: str
    targets: TargetSpec
    constraints: ConstraintSpec
    output: OutputSpec
    artifacts: ArtifactDestinations
    schema_version: str
    operator_context: OperatorContext
    phase_options: PhaseOptions
    selectors: DispatchSelectors
    assembly_options: AssemblyOptions
    metadata: RequestMetadata


@dataclass(frozen=True)
class DispatchResult:
    task_id: str
    request_path: Path
    controller_state_path: Path
    intake_snapshot_dir: Path
    shell_summary: str
    stop_and_confirm: bool = False


class SkillEntry(Protocol):
    """Canonical controller-facing dispatcher contract."""

    def dispatch(
        self,
        *,
        source_path: Path,
        workflow_intent: WorkflowIntent,
        source_kind: SourceKind,
        selectors: DispatchSelectors | None = None,
        targets: TargetSpec | None = None,
        constraints: ConstraintSpec | None = None,
        operator_context: OperatorContext | None = None,
        phase_options: PhaseOptions | None = None,
        assembly_options: AssemblyOptions | None = None,
    ) -> DispatchResult:
        """
        Resolve the user-provided task source into a canonical request and
        start the standalone collab runtime entry flow.
        """
