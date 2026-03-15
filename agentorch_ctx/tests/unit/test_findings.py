from __future__ import annotations

import unittest

from agentorch_ctx.runtime.findings import (
    extract_findings,
    findings_summary,
    has_blocking_findings,
    merge_findings_across_iterations,
)


class FindingsUnitTest(unittest.TestCase):
    def test_extract_findings_coerces_string_entries(self) -> None:
        findings = extract_findings({"findings": ["Issue A", "Issue B"]})

        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["id"], "F001")
        self.assertEqual(findings[0]["severity"], "Mid")
        self.assertEqual(findings[0]["description"], "Issue A")
        self.assertFalse(findings[0]["fixable"])
        self.assertEqual(findings[0]["iteration"], 0)
        self.assertEqual(findings[0]["sourceRef"], "")

    def test_extract_findings_handles_dict_entries(self) -> None:
        findings = extract_findings(
            {
                "findings": [
                    {
                        "id": "SEC-1",
                        "severity": "critical",
                        "description": "Secret exposure",
                        "fixable": True,
                        "fix_operations": [{"operation_id": "op-1"}],
                        "location": "src/a.py:10",
                    }
                ]
            }
        )

        self.assertEqual(findings[0]["id"], "SEC-1")
        self.assertEqual(findings[0]["severity"], "Critical")
        self.assertEqual(findings[0]["description"], "Secret exposure")
        self.assertTrue(findings[0]["fixable"])
        self.assertEqual(findings[0]["fix_operations"], [{"operation_id": "op-1"}])
        self.assertEqual(findings[0]["location"], "src/a.py:10")
        self.assertEqual(findings[0]["iteration"], 0)
        self.assertEqual(findings[0]["sourceRef"], "")

    def test_extract_findings_supports_payload_shape_and_aliases(self) -> None:
        findings = extract_findings(
            {
                "payload": {
                    "findings": [
                        {
                            "severity": "high",
                            "desc": "Use safer escaping",
                            "fix_available": True,
                            "operations": [{"operation_id": "op-fix"}],
                            "file": "src/view.py",
                        }
                    ]
                }
            }
        )

        self.assertEqual(findings[0]["id"], "F001")
        self.assertEqual(findings[0]["severity"], "High")
        self.assertEqual(findings[0]["description"], "Use safer escaping")
        self.assertTrue(findings[0]["fixable"])
        self.assertEqual(findings[0]["fix_operations"], [{"operation_id": "op-fix"}])
        self.assertEqual(findings[0]["location"], "src/view.py")
        self.assertEqual(findings[0]["iteration"], 0)
        self.assertEqual(findings[0]["sourceRef"], "")

    def test_extract_findings_returns_empty_for_non_list_findings(self) -> None:
        self.assertEqual(extract_findings({"findings": {"id": "bad"}}), [])

    def test_has_blocking_findings_detects_critical_and_high(self) -> None:
        self.assertTrue(has_blocking_findings([{"severity": "Critical"}]))
        self.assertTrue(has_blocking_findings([{"severity": "High"}]))
        self.assertFalse(has_blocking_findings([{"severity": "Mid"}]))
        self.assertFalse(has_blocking_findings([]))

    def test_findings_summary_counts_by_severity(self) -> None:
        summary = findings_summary(
            [
                {"severity": "Critical"},
                {"severity": "High"},
                {"severity": "High"},
                {"severity": "Low"},
            ]
        )

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["by_severity"]["Critical"], 1)
        self.assertEqual(summary["by_severity"]["High"], 2)
        self.assertEqual(summary["by_severity"]["Low"], 1)
        self.assertEqual(summary["blocking_count"], 3)

    def test_merge_findings_across_iterations_resolves_fixed(self) -> None:
        merged = merge_findings_across_iterations(
            [
                [
                    {
                        "id": "SEC-1",
                        "severity": "High",
                        "description": "Unsanitized input",
                        "iteration": 0,
                        "sourceRef": "R0_standard_review",
                    }
                ],
                [],
            ]
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["id"], "SEC-1")
        self.assertEqual(merged[0]["status"], "resolved")
        self.assertEqual(merged[0]["iteration"], 1)
        self.assertEqual(merged[0]["sourceRef"], "R0_standard_review")


if __name__ == "__main__":
    unittest.main()
