"""Parallel step fan-out execution for read-only review/analysis steps."""

from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

PARALLEL_WORKER_TIMEOUT_SEC = 300  # 5 minutes per worker


@dataclass(frozen=True)
class ParallelStepResult:
    step_id: str
    success: bool
    output: dict[str, Any]
    error: str


def execute_steps_parallel(
    *,
    step_defs: list[dict[str, Any]],
    execute_fn: Callable[[dict[str, Any]], dict[str, Any]],
    max_workers: int = 3,
) -> list[ParallelStepResult]:
    """
    Fan out read-only step execution in parallel.

    `execute_fn` takes a step_def dict and returns a result dict with at least:
    - "step": str
    - "success": bool
    - "output": dict

    Returns results in order of completion, not input order.
    All results are returned even if some fail.
    """
    if not step_defs:
        return []

    if len(step_defs) == 1:
        try:
            result = execute_fn(step_defs[0])
            return [
                ParallelStepResult(
                    step_id=step_defs[0].get("id", "unknown"),
                    success=bool(result.get("success", True)),
                    output=result.get("output", {}),
                    error=str(result.get("error", "")),
                )
            ]
        except Exception as exc:  # noqa: BLE001
            return [
                ParallelStepResult(
                    step_id=step_defs[0].get("id", "unknown"),
                    success=False,
                    output={},
                    error=str(exc)[:500],
                )
            ]

    results: list[ParallelStepResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_step = {
            pool.submit(execute_fn, step_def): step_def for step_def in step_defs
        }
        for future in concurrent.futures.as_completed(
            future_to_step, timeout=PARALLEL_WORKER_TIMEOUT_SEC * len(step_defs)
        ):
            step_def = future_to_step[future]
            step_id = step_def.get("id", "unknown")
            try:
                result = future.result(timeout=PARALLEL_WORKER_TIMEOUT_SEC)
                results.append(
                    ParallelStepResult(
                        step_id=step_id,
                        success=bool(result.get("success", True)),
                        output=result.get("output", {}),
                        error=str(result.get("error", "")),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "parallel step failed",
                    extra={"step_id": step_id, "error": str(exc)[:200]},
                )
                results.append(
                    ParallelStepResult(
                        step_id=step_id,
                        success=False,
                        output={},
                        error=str(exc)[:500],
                    )
                )

    return results


def is_parallel_step(step_def: dict[str, Any]) -> bool:
    """True if this step is marked as parallelizable (read-only)."""
    return bool(step_def.get("parallel", False)) or step_def.get("id", "").endswith(
        "_parallel_enrich"
    )


def is_consolidation_step(step_def: dict[str, Any]) -> bool:
    """True if this step is a post-parallel consolidation/merge step."""
    step_id = str(step_def.get("id", ""))
    return step_id.endswith("_consolidate") or bool(step_def.get("consolidate", False))


def merge_parallel_results(
    results: list[ParallelStepResult],
) -> dict[str, Any]:
    """
    Merge parallel worker outputs into a single consolidated artifact.

    Returns a dict suitable for persisting as a merge-input artifact that the
    subsequent consolidation step can reference.
    """
    workers: list[dict[str, Any]] = []
    all_succeeded = True
    for result in results:
        worker_record: dict[str, Any] = {
            "stepId": result.step_id,
            "success": result.success,
            "output": result.output,
        }
        if result.error:
            worker_record["error"] = result.error
        workers.append(worker_record)
        if not result.success:
            all_succeeded = False

    return {
        "schemaVersion": "1.0.0",
        "mergeStatus": "complete" if all_succeeded else "partial",
        "workerCount": len(results),
        "successCount": sum(1 for r in results if r.success),
        "failedCount": sum(1 for r in results if not r.success),
        "workers": workers,
    }
