from __future__ import annotations

import unittest

from collab.runtime.question_artifact import (
    build_question_artifact,
    ingest_answered_questions,
)


class QuestionArtifactUnitTest(unittest.TestCase):
    def test_build_question_artifact_auto_ids(self) -> None:
        artifact = build_question_artifact(
            task_id="t1",
            phase="plan",
            questions=[
                {"text": "What scope?", "reason": "Need to decide scope"},
                {"text": "Which DB?", "reason": "DB choice needed"},
            ],
        )
        self.assertEqual(artifact["schemaVersion"], "1.0.0")
        self.assertEqual(artifact["taskId"], "t1")
        self.assertEqual(artifact["phase"], "plan")
        self.assertEqual(artifact["status"], "pending")
        self.assertEqual(len(artifact["questions"]), 2)
        self.assertEqual(artifact["questions"][0]["id"], "Q001")
        self.assertEqual(artifact["questions"][1]["id"], "Q002")

    def test_build_question_artifact_with_choices(self) -> None:
        artifact = build_question_artifact(
            task_id="t1",
            phase="plan",
            step="P0_plan_outline",
            questions=[
                {
                    "text": "Which DB?",
                    "reason": "DB choice needed",
                    "choices": [
                        {
                            "label": "PostgreSQL",
                            "description": "Recommended",
                            "recommended": True,
                        },
                        {"label": "MySQL", "description": "Alternative"},
                    ],
                },
            ],
        )
        q = artifact["questions"][0]
        self.assertEqual(len(q["choices"]), 2)
        self.assertTrue(q["choices"][0]["recommended"])

    def test_ingest_answered_questions_marks_answered(self) -> None:
        artifact = build_question_artifact(
            task_id="t1",
            phase="plan",
            questions=[
                {"text": "What scope?", "reason": "Need scope"},
                {"text": "Which DB?", "reason": "DB needed"},
            ],
        )
        updated = ingest_answered_questions(
            question_artifact=artifact,
            answers={"Q001": "Full scope", "Q002": "PostgreSQL"},
        )
        self.assertEqual(updated["status"], "answered")
        self.assertEqual(updated["questions"][0]["answer"], "Full scope")
        self.assertIn("answeredAt", updated["questions"][0])

    def test_ingest_partial_answers(self) -> None:
        artifact = build_question_artifact(
            task_id="t1",
            phase="plan",
            questions=[
                {"text": "Q1?", "reason": "r1"},
                {"text": "Q2?", "reason": "r2"},
            ],
        )
        updated = ingest_answered_questions(
            question_artifact=artifact,
            answers={"Q001": "answer1"},
        )
        self.assertEqual(updated["status"], "partially_answered")
        self.assertEqual(updated["questions"][0]["answer"], "answer1")
        self.assertNotIn("answer", updated["questions"][1])

    def test_build_with_explicit_ids(self) -> None:
        artifact = build_question_artifact(
            task_id="t1",
            phase="plan",
            questions=[{"id": "Q100", "text": "Custom?", "reason": "custom"}],
        )
        self.assertEqual(artifact["questions"][0]["id"], "Q100")


if __name__ == "__main__":
    unittest.main()
