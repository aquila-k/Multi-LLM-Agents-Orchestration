from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentorch_ctx.interfaces.skill_entry import (
    AssemblyOptions,
    ConstraintSpec,
    DispatchResult,
    DispatchSelectors,
    OperatorContext,
    PhaseOptions,
    SkillEntry,
    SourceKind,
    TargetSpec,
    WorkflowIntent,
)
from agentorch_ctx.runtime.request_writer import prepare_request
from agentorch_ctx.runtime.task_entrypoint import run_task_from_request


@dataclass
class ClaudeCodeSkill(SkillEntry):
    root_dir: Path

    def __post_init__(self) -> None:
        import logging
        import subprocess

        _log = logging.getLogger("agentorch_ctx.claude_code_skill")
        contexts_local = self.root_dir / ".contexts" / "local"
        db_path = contexts_local / "context.db"
        if not db_path.exists():
            try:
                import os as _os
                import sys as _sys

                _env = _os.environ.copy()
                _env["CONTEXTS_HOME"] = str(contexts_local)
                _pkg_root = str(Path(__file__).resolve().parents[2])
                _existing = _env.get("PYTHONPATH", "")
                if _pkg_root not in _existing.split(_os.pathsep):
                    _env["PYTHONPATH"] = _pkg_root + (
                        _os.pathsep + _existing if _existing else ""
                    )
                result = subprocess.run(
                    [_sys.executable, "-m", "agentorch_ctx", "ctx", "init"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=str(self.root_dir),
                    env=_env,
                )
                if result.returncode != 0:
                    _log.debug(
                        "contexts auto-init failed: returncode=%s stderr=%s",
                        result.returncode,
                        result.stderr.strip(),
                    )
            except Exception:  # noqa: BLE001
                _log.debug("contexts auto-init skipped (runtime unavailable)")

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
        prepared = prepare_request(
            root_dir=self.root_dir,
            source_path=source_path,
            workflow_intent=workflow_intent,
            source_kind=source_kind,
            selectors=selectors,
            targets=targets,
            constraints=constraints,
            operator_context=operator_context,
            phase_options=phase_options,
            assembly_options=assembly_options,
        )
        result = run_task_from_request(
            request_path=prepared.request_path,
            root_dir=self.root_dir,
        )
        return DispatchResult(
            task_id=result.task_id,
            request_path=result.request_path,
            controller_state_path=result.controller_state_path,
            intake_snapshot_dir=result.intake_snapshot_dir,
            shell_summary=result.shell_summary,
            stop_and_confirm=result.stop_and_confirm,
        )
