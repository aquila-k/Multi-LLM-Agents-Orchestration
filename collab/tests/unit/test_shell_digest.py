from __future__ import annotations

import unittest

from collab.runtime.shell_digest import (
    bind_shell_digest_ref,
    derive_shell_digest,
    ingest_shell_digest,
)


class ShellDigestUnitTest(unittest.TestCase):
    def test_derives_blocked_digest_from_stop_and_confirm_summary(self) -> None:
        digest = derive_shell_digest(
            task_id="task-1",
            concise_summary="Intake accepted for task-1 but STOP_AND_CONFIRM is required before phase=impl step=apply-gate.",
            execution_record_ref="exec-1",
        )
        self.assertEqual(digest["status"], "blocked")
        self.assertEqual(digest["stop_reason"], "approval required")
        self.assertEqual(digest["resume_hint"], "apply-gate")
        self.assertEqual(len(digest["facts"]), 2)

    def test_ingests_shell_digest_into_known_information(self) -> None:
        known_information = {
            "latest_shell_digestion_summary": {"summary": "", "shell_digest_ref": ""},
            "entries": [],
            "updated_at": "2026-03-08T00:00:00Z",
        }
        digest = derive_shell_digest(
            task_id="task-2",
            concise_summary="Intake accepted for task-2; phase=plan step=intake is ready.",
            execution_record_ref="exec-2",
        )
        digest = bind_shell_digest_ref(
            shell_digest=digest,
            shell_digest_ref="shell-digest-2",
        )
        updated = ingest_shell_digest(
            known_information=known_information, shell_digest=digest
        )
        self.assertIn("phase=plan", updated["entries"][0]["value"])
        self.assertEqual(
            updated["latest_shell_digestion_summary"]["summary"],
            digest["concise_summary"],
        )
        self.assertEqual(
            updated["latest_shell_digestion_summary"]["shell_digest_ref"],
            "shell-digest-2",
        )


if __name__ == "__main__":
    unittest.main()
