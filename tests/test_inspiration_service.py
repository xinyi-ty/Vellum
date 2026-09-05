import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["USE_MOCK"] = "true"

from server.models import AnswerInput, CreationMode
from server.services.inspiration_service import InspirationService


class InspirationFlowTests(unittest.TestCase):
    def setUp(self):
        self.service = InspirationService()

    def test_collaborative_flow_answers_one_question_and_compiles(self):
        state = self.service.start("雨夜里撑红伞的女孩", CreationMode.collaborative)

        self.assertEqual(state.status, "needs_input")
        self.assertEqual(state.questions_asked, 1)
        self.assertEqual(state.draft.core_intent.origin, "user")
        self.assertIsNotNone(state.question)

        state = self.service.answer(state, AnswerInput(option_id="wide"))
        self.assertEqual(state.status, "ready")
        self.assertIsNone(state.question)
        self.assertTrue(
            any(item.origin == "user" and "拉远观察" in item.text for item in state.draft.visual_language)
        )

        result = self.service.compile(state)
        self.assertIn("红伞", result.prompt)
        self.assertIn("拉远观察", result.prompt)

    def test_exploratory_mode_does_not_interrupt_with_a_question(self):
        state = self.service.start("漂浮在云海上的图书馆", CreationMode.exploratory)
        self.assertEqual(state.status, "ready")
        self.assertIsNone(state.question)
        self.assertEqual(state.questions_asked, 0)

    def test_revision_becomes_confirmed_user_content(self):
        state = self.service.start("安静的森林", CreationMode.exploratory)
        revised = self.service.revise(state, "画面里必须有一条浅水溪")
        self.assertIn("画面里必须有一条浅水溪", revised.draft.constraints.must_keep)

    def test_invalid_option_is_rejected(self):
        state = self.service.start("山顶上的白色灯塔", CreationMode.collaborative)
        with self.assertRaisesRegex(ValueError, "option_id"):
            self.service.answer(state, AnswerInput(option_id="missing"))


if __name__ == "__main__":
    unittest.main()
