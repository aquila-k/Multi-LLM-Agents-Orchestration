from __future__ import annotations

import unittest

from collab.runtime.approval_model import (
    DANGEROUS_OPERATION_TYPES,
    build_approval_decision,
    build_approval_request,
    classify_operation_type,
    requires_approval,
    scope_match,
)


class ApprovalModelUnitTest(unittest.TestCase):
    def test_classify_delete_mode_as_file_delete(self) -> None:
        self.assertEqual(
            classify_operation_type({"mode": "delete", "kind": "patch"}),
            "file_delete",
        )

    def test_classify_rename_kind_as_file_rename(self) -> None:
        self.assertEqual(
            classify_operation_type({"mode": "patch", "kind": "rename"}),
            "file_rename",
        )

    def test_classify_dependency_danger_class(self) -> None:
        self.assertEqual(
            classify_operation_type(
                {"mode": "patch", "danger_class": "dependency_add"}
            ),
            "dependency_add",
        )

    def test_classify_regular_patch_as_none(self) -> None:
        self.assertIsNone(classify_operation_type({"mode": "patch", "kind": "patch"}))

    def test_requires_approval_for_file_delete_without_preapproval(self) -> None:
        self.assertTrue(
            requires_approval(
                {"mode": "delete", "kind": "delete"}, approved_operations=[]
            )
        )

    def test_requires_approval_false_for_regular_patch(self) -> None:
        self.assertFalse(
            requires_approval(
                {"mode": "patch", "kind": "patch"}, approved_operations=[]
            )
        )

    def test_requires_approval_false_when_preapproved(self) -> None:
        self.assertFalse(
            requires_approval(
                {"mode": "patch", "danger_class": "dependency_add"},
                approved_operations=[
                    {"decision": "approved", "operationType": "dependency_add"}
                ],
            )
        )

    def test_build_approval_request_contains_required_fields(self) -> None:
        request = build_approval_request(
            task_id="task-1",
            phase="impl",
            step_id="I2_generate",
            operation_type="dependency_add",
            scope={"targetDependencies": ["pytest"]},
            rationale="Adding test dependency for CI checks",
        )
        self.assertEqual(request["schemaVersion"], "1.0.0")
        self.assertEqual(request["taskId"], "task-1")
        self.assertEqual(request["operationType"], "dependency_add")
        self.assertIn("scope", request)
        self.assertIn("rationale", request)

    def test_build_approval_decision_contains_decision(self) -> None:
        decision = build_approval_decision(
            task_id="task-1",
            approval_request_ref="artifacts/approval-request.json",
            decision="approved",
        )
        self.assertEqual(decision["decision"], "approved")
        self.assertEqual(decision["taskId"], "task-1")
        self.assertTrue(decision["decidedAt"].endswith("Z"))

    def test_build_approval_request_includes_operation_types(self) -> None:
        request = build_approval_request(
            task_id="task-2",
            phase="impl",
            step_id="apply",
            operation_type="large_diff",
            scope={"affectedPaths": ["pyproject.toml"]},
            rationale="Dangerous operations require approval.",
            operation_types=["dependency_add", "lockfile_update"],
            max_files=2,
            max_bytes=512,
            valid_phases=["impl"],
        )
        self.assertEqual(
            request["operationTypes"], ["dependency_add", "lockfile_update"]
        )
        self.assertEqual(request["maxFiles"], 2)
        self.assertEqual(request["maxBytes"], 512)
        self.assertEqual(request["validPhases"], ["impl"])

    def test_build_approval_decision_includes_approval_mode(self) -> None:
        decision = build_approval_decision(
            task_id="task-2",
            approval_request_ref="artifacts/approval-request.json",
            decision="approved",
            approval_mode="bundle",
            scope_level="prefix",
            scope_match_policy="prefix_match",
            granted_by_user_explicitly=True,
            valid_until_phase="review",
        )
        self.assertEqual(decision["approvalMode"], "bundle")
        self.assertEqual(decision["scopeLevel"], "prefix")
        self.assertEqual(decision["scopeMatchPolicy"], "prefix_match")
        self.assertTrue(decision["grantedByUserExplicitly"])
        self.assertEqual(decision["validUntilPhase"], "review")

    def test_scope_match_operation_level_approved(self) -> None:
        operation = {
            "mode": "patch",
            "danger_class": "dependency_add",
            "target_path": "pyproject.toml",
        }
        decision = {
            "decision": "approved",
            "approvalMode": "operation",
            "operationType": "dependency_add",
            "scopeMatchPolicy": "strict",
            "scope": {"affectedPaths": ["pyproject.toml"]},
        }
        self.assertTrue(scope_match(operation, decision))

    def test_scope_match_bundle_without_explicit_grant_fails(self) -> None:
        operation = {
            "mode": "patch",
            "danger_class": "dependency_add",
            "target_path": "pyproject.toml",
        }
        decision = {
            "decision": "approved",
            "approvalMode": "bundle",
            "grantedByUserExplicitly": False,
        }
        self.assertFalse(scope_match(operation, decision))

    def test_scope_match_operation_level_rejected(self) -> None:
        operation = {
            "mode": "patch",
            "danger_class": "dependency_add",
            "target_path": "pyproject.toml",
        }
        decision = {
            "decision": "rejected",
            "approvalMode": "operation",
            "operationType": "dependency_add",
        }
        self.assertFalse(scope_match(operation, decision))

    def test_dangerous_operation_catalog_has_expected_size(self) -> None:
        self.assertGreaterEqual(len(DANGEROUS_OPERATION_TYPES), 15)


if __name__ == "__main__":
    unittest.main()
