"""Application logic for understanding, refining, and compiling an idea."""

from copy import deepcopy
import re

from ..models import (
    AnswerInput,
    CompiledPrompt,
    CreationMode,
    DraftConstraints,
    DraftStatement,
    InspirationState,
    KeyQuestion,
    QuestionOption,
    TurnResult,
    VisualDraft,
)
from ..prompts import ANSWER_SYSTEM_PROMPT, COMPILE_SYSTEM_PROMPT, REVISE_SYSTEM_PROMPT, START_SYSTEM_PROMPT
from .model_gateway import ModelGateway, ModelGatewayError


class InspirationService:
    def __init__(self, gateway: ModelGateway | None = None):
        self.gateway = gateway or ModelGateway()

    def start(self, idea: str, mode: CreationMode) -> InspirationState:
        idea = idea.strip()
        if self.gateway.is_mock:
            result = self._mock_start(idea, mode)
        else:
            raw = self.gateway.call_json(START_SYSTEM_PROMPT, {"idea": idea, "mode": mode.value})
            result = TurnResult.model_validate(raw)
        return self._state_from_turn(idea, mode, result, previous_questions=0)

    def answer(self, state: InspirationState, answer: AnswerInput) -> InspirationState:
        if state.status != "needs_input" or state.question is None:
            raise ValueError("the current state has no question to answer")

        answer_text = self._resolve_answer(state.question, answer)
        if self.gateway.is_mock:
            result = self._mock_answer(state, answer_text, answer.use_ai_decide)
        else:
            raw = self.gateway.call_json(
                ANSWER_SYSTEM_PROMPT,
                {
                    "original_idea": state.original_idea,
                    "mode": state.mode.value,
                    "understanding": state.understanding,
                    "draft": state.draft.model_dump(),
                    "question": state.question.model_dump(),
                    "answer": answer_text,
                    "answer_was_delegated_to_ai": answer.use_ai_decide,
                    "remaining_questions": max(0, 2 - state.questions_asked),
                },
            )
            result = TurnResult.model_validate(raw)
        if answer.use_ai_decide:
            result.question = None
        return self._state_from_turn(
            state.original_idea,
            state.mode,
            result,
            previous_questions=state.questions_asked,
        )

    def revise(self, state: InspirationState, instruction: str) -> InspirationState:
        instruction = instruction.strip()
        if self.gateway.is_mock:
            result = self._mock_revise(state, instruction)
        else:
            raw = self.gateway.call_json(
                REVISE_SYSTEM_PROMPT,
                {
                    "original_idea": state.original_idea,
                    "mode": state.mode.value,
                    "understanding": state.understanding,
                    "draft": state.draft.model_dump(),
                    "instruction": instruction,
                },
            )
            result = TurnResult.model_validate(raw)
            result.question = None
        return self._state_from_turn(
            state.original_idea,
            state.mode,
            result,
            previous_questions=state.questions_asked,
        )

    def compile(self, state: InspirationState) -> CompiledPrompt:
        if self.gateway.is_mock:
            return self._mock_compile(state)
        raw = self.gateway.call_json(
            COMPILE_SYSTEM_PROMPT,
            {
                "original_idea": state.original_idea,
                "mode": state.mode.value,
                "understanding": state.understanding,
                "draft": state.draft.model_dump(),
            },
            max_tokens=2400,
        )
        return CompiledPrompt.model_validate(raw)

    @staticmethod
    def _state_from_turn(
        idea: str,
        mode: CreationMode,
        result: TurnResult,
        previous_questions: int,
    ) -> InspirationState:
        question = result.question if previous_questions < 2 and mode != CreationMode.exploratory else None
        questions_asked = previous_questions + (1 if question else 0)
        return InspirationState(
            original_idea=idea,
            mode=mode,
            understanding=result.understanding,
            draft=result.draft,
            question=question,
            questions_asked=questions_asked,
            status="needs_input" if question else "ready",
        )

    @staticmethod
    def _resolve_answer(question: KeyQuestion, answer: AnswerInput) -> str:
        if answer.use_ai_decide:
            return "交给云笺，选择与当前创作意图最一致的方向"
        if answer.text and answer.text.strip():
            return answer.text.strip()
        option = next((item for item in question.options if item.id == answer.option_id), None)
        if option is None:
            raise ValueError("option_id does not belong to the current question")
        return f"{option.label}：{option.effect}"

    @staticmethod
    def _mock_start(idea: str, mode: CreationMode) -> TurnResult:
        visual_language = []
        if mode != CreationMode.faithful:
            visual_language.append(
                DraftStatement(
                    text="使用清晰的主体层级，让环境服务于核心情绪",
                    origin="assistant",
                    status="suggested",
                )
            )

        question = None
        if mode != CreationMode.exploratory:
            question = KeyQuestion(
                id="viewpoint_distance",
                prompt="你希望观众离画面主体多近？",
                why_it_matters="距离会决定画面更强调主体细节，还是主体与环境的关系。",
                options=[
                    QuestionOption(id="close", label="靠近主体", effect="突出神态、材质与细小动作"),
                    QuestionOption(id="balanced", label="保持适中", effect="同时交代主体和周围环境"),
                    QuestionOption(id="wide", label="拉远观察", effect="让空间关系承担更多情绪表达"),
                ],
            )

        return TurnResult(
            understanding=f"你希望把“{idea}”整理成一幅重点清楚、可以直接生成的画面。",
            draft=VisualDraft(
                core_intent=DraftStatement(text=idea, origin="user", status="confirmed"),
                facts=[DraftStatement(text=idea, origin="user", status="confirmed")],
                visual_language=visual_language,
                constraints=DraftConstraints(),
            ),
            question=question,
        )

    @staticmethod
    def _mock_answer(state: InspirationState, answer_text: str, delegated: bool) -> TurnResult:
        draft = deepcopy(state.draft)
        draft.visual_language.append(
            DraftStatement(
                text=answer_text,
                origin="assistant" if delegated else "user",
                status="suggested" if delegated else "confirmed",
            )
        )
        return TurnResult(
            understanding=f"{state.understanding} 画面的观看方式已经确定。",
            draft=draft,
            question=None,
        )

    @staticmethod
    def _mock_compile(state: InspirationState) -> CompiledPrompt:
        parts = [state.draft.core_intent.text]
        for statement in [*state.draft.facts, *state.draft.visual_language]:
            if statement.text not in parts:
                parts.append(statement.text)
        if state.draft.constraints.must_keep:
            parts.append("必须保留：" + "、".join(state.draft.constraints.must_keep))
        return CompiledPrompt(
            prompt="，".join(parts),
            negative_prompt="、".join(state.draft.constraints.avoid),
            creative_summary=state.understanding,
        )

    @staticmethod
    def _mock_revise(state: InspirationState, instruction: str) -> TurnResult:
        draft = deepcopy(state.draft)
        clauses = [item.strip() for item in re.split(r"[，,；;。]", instruction) if item.strip()]
        for clause in clauses:
            if "不要" in clause or "避免" in clause:
                draft.constraints.avoid.append(clause)
            elif "必须" in clause or "保留" in clause:
                draft.constraints.must_keep.append(clause)
            else:
                draft.facts.append(DraftStatement(text=clause, origin="user", status="confirmed"))
        return TurnResult(
            understanding=f"{state.understanding} 已按你的补充更新草稿。",
            draft=draft,
            question=None,
        )


__all__ = ["InspirationService", "ModelGatewayError"]
