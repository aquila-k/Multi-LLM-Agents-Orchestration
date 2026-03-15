from __future__ import annotations

from dataclasses import dataclass

COMMON_STATES = {
    "pending",
    "ready",
    "running",
    "blocked",
    "partial",
    "succeeded",
    "failed",
    "canceled",
}
TASK_STATES = {
    "pending",
    "running",
    "blocked",
    "partial",
    "succeeded",
    "failed",
    "canceled",
}
PHASE_STATES = COMMON_STATES
STEP_STATES = COMMON_STATES


@dataclass(frozen=True)
class TransitionResult:
    before: str
    after: str
    allowed: bool


class StateMachine:
    def transition_task(self, before: str, after: str) -> TransitionResult:
        return TransitionResult(
            before=before,
            after=after,
            allowed=(after in self._task_edges().get(before, set())),
        )

    def transition_phase(self, before: str, after: str) -> TransitionResult:
        return TransitionResult(
            before=before,
            after=after,
            allowed=(after in self._phase_edges().get(before, set())),
        )

    def transition_step(self, before: str, after: str) -> TransitionResult:
        return TransitionResult(
            before=before,
            after=after,
            allowed=(after in self._step_edges().get(before, set())),
        )

    def ensure_task_transition(self, before: str, after: str) -> None:
        result = self.transition_task(before, after)
        if not result.allowed:
            raise ValueError(f"invalid task transition: {before} -> {after}")

    def ensure_phase_transition(self, before: str, after: str) -> None:
        result = self.transition_phase(before, after)
        if not result.allowed:
            raise ValueError(f"invalid phase transition: {before} -> {after}")

    def ensure_step_transition(self, before: str, after: str) -> None:
        result = self.transition_step(before, after)
        if not result.allowed:
            raise ValueError(f"invalid step transition: {before} -> {after}")

    def _task_edges(self) -> dict[str, set[str]]:
        return {
            "pending": {"running"},
            "running": {"blocked", "partial", "succeeded", "failed", "canceled"},
            "blocked": {"running", "canceled"},
            "partial": {"running", "failed", "canceled"},
            "succeeded": set(),
            "failed": set(),
            "canceled": set(),
        }

    def _phase_edges(self) -> dict[str, set[str]]:
        return {
            "pending": {"ready", "canceled"},
            "ready": {"running", "canceled"},
            "running": {"blocked", "partial", "succeeded", "failed", "canceled"},
            "blocked": {"running", "canceled"},
            "partial": {"running", "failed", "canceled", "succeeded"},
            "succeeded": set(),
            "failed": set(),
            "canceled": set(),
        }

    def _step_edges(self) -> dict[str, set[str]]:
        return self._phase_edges()
