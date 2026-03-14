from __future__ import annotations

import unittest

from collab.runtime.parser import parse_provider_output


class ParserUnitTest(unittest.TestCase):
    def test_parses_fenced_json_payload(self) -> None:
        raw_output = """
Result:
```json
{
  "status": "success",
  "mode": "patch",
  "summary": "Structured patch result",
  "payload": {
    "operations": [
      {
        "operationId": "op-1",
        "targetPath": "collab/runtime/file.py",
        "mode": "patch"
      }
    ]
  }
}
```
"""
        parsed = parse_provider_output(raw_output)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["mode"], "patch")
        self.assertEqual(parsed["summary"], "Structured patch result")
        self.assertTrue(parsed["meaningful"])
        self.assertGreaterEqual(parsed["parser_confidence"], 0.95)

    def test_falls_back_to_report_only_for_plain_text(self) -> None:
        parsed = parse_provider_output("Need operator review before continuing.")
        self.assertEqual(parsed["mode"], "report_only")
        self.assertEqual(parsed["status"], "partial")
        self.assertTrue(parsed["meaningful"])
        self.assertEqual(
            parsed["payload"]["report"], "Need operator review before continuing."
        )


if __name__ == "__main__":
    unittest.main()
