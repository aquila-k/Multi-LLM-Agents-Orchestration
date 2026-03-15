from __future__ import annotations

import unittest

from agentorch_ctx.runtime.normalizer import normalize_response
from agentorch_ctx.runtime.validator import validate_artifacts


class ValidatorUnitTest(unittest.TestCase):
    def test_passes_patch_apply_readiness_when_operation_is_safe(self) -> None:
        request = {
            "schema_version": "1.0.0",
            "task_id": "task-1",
            "source": {"path": "/tmp/task.md", "kind": "markdown"},
            "workflow_intent": "impl",
            "summary": "Implement parser",
            "targets": {},
            "constraints": {},
            "output": {
                "preferred_mode": "patch",
                "allowed_modes": ["patch"],
                "operations_required": True,
            },
            "artifacts": {},
            "operator_context": {"summary": "test"},
            "selectors": {},
            "assembly_options": {
                "prompt_version": "1.0.0",
                "schema_version": "1.0.0",
                "concise_shell_summary": True,
            },
            "metadata": {
                "created_at": "2026-03-08T00:00:00Z",
                "source_canonicalized_at": "2026-03-08T00:00:00Z",
                "host": "claude_code",
                "cwd": "/tmp",
            },
        }
        response = {
            "schema_version": "1.0.0",
            "task_id": "task-1",
            "status": "success",
            "mode": "patch",
            "summary": "Safe patch generated",
            "warnings": [],
            "issues": [],
            "payload": {
                "operations": [
                    {
                        "operationId": "op-1",
                        "kind": "patch",
                        "targetPath": "agentorch_ctx/runtime/parser.py",
                        "mode": "patch",
                        "baseFingerprint": "abc123",
                        "expectedExistingPathState": "present",
                        "riskLevel": "low",
                        "requiresApproval": False,
                        "scopeCheck": "passed",
                        "confidence": 0.91,
                        "sourceRunRefs": ["run-1"],
                        "validationRefs": [],
                        "estimatedChangedLines": 20,
                        "estimatedChangedBytes": 512,
                    }
                ]
            },
            "metadata": {
                "provider": "codex",
                "adapter_version": "1.0.0",
                "started_at": "2026-03-08T00:00:00Z",
                "completed_at": "2026-03-08T00:01:00Z",
                "run_ref": "run-1",
                "shell_digest_ref": "digest-1",
            },
        }
        normalized = normalize_response(
            task_id="task-1",
            parsed_response={**response, "meaningful": True, "parser_confidence": 0.98},
            source_response_ref="response-1",
        )
        validation = validate_artifacts(
            request=request,
            response=response,
            normalized=normalized,
            execution={"shell_summary": "ready", "shell_digest_ref": "digest-1"},
        )
        self.assertEqual(validation["overall_outcome"], "passed")
        self.assertTrue(validation["apply_readiness"]["ready"])
        self.assertEqual(validation["apply_readiness"]["codes"], [])

    def test_blocks_apply_when_scope_and_approval_requirements_fail(self) -> None:
        request = {
            "schema_version": "1.0.0",
            "task_id": "task-2",
            "source": {"path": "/tmp/task.md", "kind": "markdown"},
            "workflow_intent": "impl",
            "summary": "Dangerous change",
            "targets": {},
            "constraints": {},
            "output": {
                "preferred_mode": "patch",
                "allowed_modes": ["patch", "delete_file"],
                "operations_required": True,
            },
            "artifacts": {},
            "operator_context": {"summary": "test"},
            "selectors": {},
            "assembly_options": {
                "prompt_version": "1.0.0",
                "schema_version": "1.0.0",
                "concise_shell_summary": True,
            },
            "metadata": {
                "created_at": "2026-03-08T00:00:00Z",
                "source_canonicalized_at": "2026-03-08T00:00:00Z",
                "host": "claude_code",
                "cwd": "/tmp",
            },
        }
        response = {
            "schema_version": "1.0.0",
            "task_id": "task-2",
            "status": "partial",
            "mode": "delete_file",
            "summary": "Delete requested",
            "warnings": [],
            "issues": [],
            "payload": {
                "operations": [
                    {
                        "operationId": "op-1",
                        "kind": "delete",
                        "targetPath": ".git/config",
                        "mode": "delete_file",
                        "baseFingerprint": "mismatch",
                        "expectedExistingPathState": "conflict",
                        "riskLevel": "high",
                        "requiresApproval": True,
                        "scopeCheck": "failed",
                        "confidence": 0.6,
                        "sourceRunRefs": ["run-2"],
                        "validationRefs": [],
                        "estimatedChangedLines": 5,
                        "estimatedChangedBytes": 40,
                    }
                ]
            },
            "metadata": {
                "provider": "codex",
                "adapter_version": "1.0.0",
                "started_at": "2026-03-08T00:00:00Z",
                "completed_at": "2026-03-08T00:01:00Z",
                "run_ref": "run-2",
                "shell_digest_ref": "digest-2",
            },
        }
        normalized = normalize_response(
            task_id="task-2",
            parsed_response={**response, "meaningful": True, "parser_confidence": 0.7},
            source_response_ref="response-2",
        )
        validation = validate_artifacts(
            request=request,
            response=response,
            normalized=normalized,
            execution={"shell_summary": "blocked", "shell_digest_ref": "digest-2"},
            forbidden_paths=[".git"],
        )
        self.assertEqual(validation["overall_outcome"], "failed_but_meaningful")
        self.assertFalse(validation["apply_readiness"]["ready"])
        self.assertIn(
            "APPLY_MODE_REQUIRES_APPROVAL", validation["apply_readiness"]["codes"]
        )
        self.assertIn("APPLY_SCOPE_FAILED", validation["apply_readiness"]["codes"])
        self.assertIn("APPLY_FORBIDDEN_PATH", validation["apply_readiness"]["codes"])
        self.assertIn(
            "APPLY_DELETE_REQUIRES_APPROVAL", validation["apply_readiness"]["codes"]
        )


if __name__ == "__main__":
    unittest.main()
