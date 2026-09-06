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
        self.assertEqual(len(state.inspiration_hints), 4)

        state = self.service.answer(state, AnswerInput(option_id="distant"))
        self.assertEqual(state.status, "ready")
        self.assertIsNone(state.question)
        self.assertTrue(
            any(item.origin == "user" and "远处身影" in item.text for item in state.draft.visual_language)
        )
        self.assertEqual(len(state.inspiration_hints), 4)

        result = self.service.compile(state)
        self.assertIn("红伞", result.prompt)
        self.assertIn("远处身影", result.prompt)

    def test_exploratory_mode_does_not_interrupt_with_a_question(self):
        state = self.service.start("漂浮在云海上的图书馆", CreationMode.exploratory)
        self.assertEqual(state.status, "ready")
        self.assertIsNone(state.question)
        self.assertEqual(state.questions_asked, 0)

    def test_revision_becomes_confirmed_user_content(self):
        state = self.service.start("安静的森林", CreationMode.exploratory)
        revised = self.service.revise(state, "画面里必须有一条浅水溪")
        self.assertIn("画面里必须有一条浅水溪", revised.draft.constraints.must_keep)
        self.assertIn("浅水溪", revised.understanding)

    def test_follow_up_reply_changes_with_the_new_content(self):
        state = self.service.start("云海上的古城", CreationMode.exploratory)
        first_reply = state.understanding
        revised = self.service.revise(state, "加入一只穿过云层的鲸鱼")
        self.assertNotEqual(first_reply, revised.understanding)
        self.assertIn("鲸鱼", revised.understanding)

    def test_narrative_input_gets_scene_context_without_inventing_narrator(self):
        state = self.service.start(
            "我暗恋的女孩回头偷偷看了我一眼，被我发现后眼里满是尴尬和害羞",
            CreationMode.collaborative,
        )
        self.assertIsNotNone(state.draft.scene_context)
        self.assertIn("暗恋", state.draft.scene_context.text)
        self.assertNotIn("少年", state.draft.scene_context.text)

    def test_invalid_option_is_rejected(self):
        state = self.service.start("山顶上的白色灯塔", CreationMode.collaborative)
        with self.assertRaisesRegex(ValueError, "option_id"):
            self.service.answer(state, AnswerInput(option_id="missing"))

    def test_refresh_hints_returns_four_new_examples_without_changing_draft(self):
        state = self.service.start("云海上的古城", CreationMode.exploratory)
        previous_examples = [item.example for item in state.inspiration_hints]
        previous_draft = state.draft.model_dump()

        refreshed = self.service.refresh_hints(state, previous_examples)

        self.assertEqual(len(refreshed.inspiration_hints), 4)
        self.assertTrue(set(previous_examples).isdisjoint(item.example for item in refreshed.inspiration_hints))
        self.assertEqual(refreshed.draft.model_dump(), previous_draft)


if __name__ == "__main__":
    unittest.main()
