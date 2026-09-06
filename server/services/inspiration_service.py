"""Application logic for understanding, refining, and compiling an idea."""

from copy import deepcopy
import re

from ..models import (
    AnswerInput,
    CompiledPrompt,
    CreationMode,
    DraftConstraints,
    DraftStatement,
    HintBatch,
    InspirationHint,
    InspirationState,
    KeyQuestion,
    QuestionOption,
    TurnResult,
    VisualDraft,
)
from ..prompts import (
    ANSWER_SYSTEM_PROMPT,
    COMPILE_SYSTEM_PROMPT,
    REFRESH_HINTS_SYSTEM_PROMPT,
    REVISE_SYSTEM_PROMPT,
    START_SYSTEM_PROMPT,
)
from .model_gateway import ModelGateway, ModelGatewayError


class InspirationService:
    def __init__(self, gateway: ModelGateway | None = None):
        self.gateway = gateway or ModelGateway()

    def start(self, idea: str, mode: CreationMode) -> InspirationState:
        idea = idea.strip()
        if self.gateway.is_mock:
            result = self._mock_start(idea, mode)
        else:
            raw = self.gateway.call_json(
                START_SYSTEM_PROMPT,
                {"idea": idea, "mode": mode.value},
                response_model=TurnResult,
            )
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
                    "inspiration_hints": [item.model_dump() for item in state.inspiration_hints],
                    "question": state.question.model_dump(),
                    "answer": answer_text,
                    "answer_was_delegated_to_ai": answer.use_ai_decide,
                    "remaining_questions": max(0, 2 - state.questions_asked),
                },
                response_model=TurnResult,
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
                    "inspiration_hints": [item.model_dump() for item in state.inspiration_hints],
                    "instruction": instruction,
                },
                response_model=TurnResult,
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
            response_model=CompiledPrompt,
        )
        return CompiledPrompt.model_validate(raw)

    def refresh_hints(self, state: InspirationState, excluded_examples: list[str]) -> InspirationState:
        # Refreshing suggestions must not mutate any confirmed draft content.
        excluded = list(dict.fromkeys([*excluded_examples, *(item.example for item in state.inspiration_hints)]))
        if self.gateway.is_mock:
            hints = self._mock_hints(state.original_idea, excluded)
        else:
            raw = self.gateway.call_json(
                REFRESH_HINTS_SYSTEM_PROMPT,
                {
                    "original_idea": state.original_idea,
                    "mode": state.mode.value,
                    "draft": state.draft.model_dump(),
                    "current_hints": [item.model_dump() for item in state.inspiration_hints],
                    "excluded_examples": excluded[-40:],
                },
                response_model=HintBatch,
            )
            hints = HintBatch.model_validate(raw).inspiration_hints
        updated = state.model_copy(deep=True)
        updated.inspiration_hints = hints
        return updated

    @staticmethod
    def _state_from_turn(
        idea: str,
        mode: CreationMode,
        result: TurnResult,
        previous_questions: int,
    ) -> InspirationState:
        # Enforce the product-level question budget even if the model proposes another question.
        question = result.question if previous_questions < 2 and mode != CreationMode.exploratory else None
        questions_asked = previous_questions + (1 if question else 0)
        return InspirationState(
            original_idea=idea,
            mode=mode,
            understanding=result.understanding,
            draft=result.draft,
            question=question,
            inspiration_hints=result.inspiration_hints,
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
            if any(word in idea for word in ("女孩", "男孩", "人物", "一个人", "少年", "老人")):
                question = KeyQuestion(
                    id="subject_presence",
                    prompt="你希望这位人物怎样进入观众的视线？",
                    why_it_matters="人物与环境的关系，会决定画面更像肖像还是一个故事瞬间。",
                    options=[
                        QuestionOption(id="portrait", label="先看见人物", effect="突出神态、衣着与细小动作"),
                        QuestionOption(id="in_scene", label="人在环境中", effect="人物与场景各占一半，兼顾故事与氛围"),
                        QuestionOption(id="distant", label="成为远处身影", effect="让空间和环境承担主要情绪"),
                    ],
                )
            else:
                question = KeyQuestion(
                    id="visual_focus",
                    prompt="这幅画最希望观众先注意到什么？",
                    why_it_matters="明确第一视觉焦点，能避免宏大场景变成没有重点的背景堆叠。",
                    options=[
                        QuestionOption(id="landmark", label="标志性的主体", effect="用一个建筑、物件或生物建立清晰焦点"),
                        QuestionOption(id="space", label="空间本身", effect="强调尺度、层次和环境的沉浸感"),
                        QuestionOption(id="mystery", label="隐藏的线索", effect="加入克制的小细节，让观众产生探索欲"),
                    ],
                )

        return TurnResult(
            understanding=f"我先抓住了这个画面的核心：{idea}。目前主体方向已经明确，接下来可以从观看重点和氛围细节中选一处补全，不需要一次回答很多问题。",
            draft=VisualDraft(
                scene_context=InspirationService._mock_scene_context(idea),
                core_intent=DraftStatement(text=idea, origin="user", status="confirmed"),
                facts=[DraftStatement(text=idea, origin="user", status="confirmed")],
                visual_language=visual_language,
                constraints=DraftConstraints(),
            ),
            question=question,
            inspiration_hints=InspirationService._mock_hints(idea),
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
            understanding=f"收到，这一轮把“{answer_text}”确定为画面的表达方向。它会改变视觉重心，但不会改动你已经描述的主体和场景。",
            draft=draft,
            question=None,
            inspiration_hints=InspirationService._mock_hints(
                f"{state.original_idea} {answer_text}",
                [item.example for item in state.inspiration_hints],
            ),
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
        updated_context = InspirationService._mock_scene_context(f"{state.original_idea}。{instruction}")
        if updated_context:
            draft.scene_context = updated_context
        clauses = [item.strip() for item in re.split(r"[，,；;。]", instruction) if item.strip()]
        for clause in clauses:
            if "不要" in clause or "避免" in clause:
                if clause not in draft.constraints.avoid:
                    draft.constraints.avoid.append(clause)
            elif "必须" in clause or "保留" in clause:
                if clause not in draft.constraints.must_keep:
                    draft.constraints.must_keep.append(clause)
            else:
                if not any(item.text == clause for item in draft.facts):
                    draft.facts.append(DraftStatement(text=clause, origin="user", status="confirmed"))
        return TurnResult(
            understanding=f"这次我记下了你的补充：“{instruction}”。它已经作为确定信息进入草稿，之前的核心画面保持不变。",
            draft=draft,
            question=None,
            inspiration_hints=InspirationService._mock_hints(
                f"{state.original_idea} {instruction}",
                [item.example for item in state.inspiration_hints],
            ),
        )

    @staticmethod
    def _mock_hints(idea: str, excluded_examples: list[str] | None = None) -> list[InspirationHint]:
        # A larger deterministic pool lets offline mode exercise replacement and refill behavior.
        candidates = [
            InspirationHint(
                id="light_time",
                label="光线与时刻",
                suggestion="时间会直接决定轮廓、阴影和画面的情绪温度。",
                example="清晨的侧光穿过薄雾，建筑边缘泛着柔和金色",
            ),
            InspirationHint(
                id="viewpoint",
                label="观看方式",
                suggestion="选择观众站在哪里，能让主体和空间关系更明确。",
                example="从略低的位置向上看，让主体显得高远而有压迫感",
            ),
            InspirationHint(
                id="color_relation",
                label="色彩关系",
                suggestion="只确定一组主色与点缀色，就能减少画面的随机感。",
                example="以低饱和青灰为主，只用一点暖金色引导视线",
            ),
            InspirationHint(
                id="emotion",
                label="情绪气息",
                suggestion="情绪不是风格标签，它会影响天气、光线与空间密度。",
                example="整体安静而神秘，像故事即将发生前的一秒",
            ),
            InspirationHint(
                id="action_moment",
                label="动作瞬间",
                suggestion="一个将要发生或刚刚结束的动作，能让静态画面产生故事感。",
                example="主体刚停下脚步，衣角仍被身后的风轻轻掀起",
            ),
            InspirationHint(
                id="spatial_depth",
                label="空间层次",
                suggestion="前中后景的遮挡关系能让空间更真实、更有纵深。",
                example="近处虚化的枝叶遮住一角，远处轮廓逐渐隐入雾中",
            ),
            InspirationHint(
                id="material_detail",
                label="材质细节",
                suggestion="抓住一种表面质感，可以让主体更容易被准确生成。",
                example="潮湿表面映出零碎光点，边缘带着细小水珠",
            ),
            InspirationHint(
                id="environment_motion",
                label="环境变化",
                suggestion="让环境产生轻微变化，可以加强画面的现场感。",
                example="一阵风掠过画面，薄雾和散落的叶片向同一方向移动",
            ),
            InspirationHint(
                id="visual_focus",
                label="视觉焦点",
                suggestion="用明暗或清晰度建立唯一焦点，避免各处平均用力。",
                example="只有主体的眼睛处于清晰亮部，其余区域柔和退后",
            ),
            InspirationHint(
                id="weather_trace",
                label="天气痕迹",
                suggestion="不必直接描述天气，用留下的痕迹也能传递环境状态。",
                example="雨刚停，空气里仍有细雾，地面保留着浅浅倒影",
            ),
            InspirationHint(
                id="scale_contrast",
                label="尺度对比",
                suggestion="大小关系可以快速建立宏大、亲密或孤独的感受。",
                example="让人物只占画面很小一部分，周围空间显得格外辽阔",
            ),
            InspirationHint(
                id="quiet_clue",
                label="故事线索",
                suggestion="加入一个克制的小线索，会让观众自然联想画面之外的故事。",
                example="角落留着一盏仍亮着的灯，像有人刚刚离开",
            ),
        ]
        excluded = set(excluded_examples or [])
        available = [item for item in candidates if item.example not in excluded]
        if len(available) < 4:
            available.extend(item for item in candidates if item.example in excluded)
        return available[:4]

    @staticmethod
    def _mock_scene_context(idea: str) -> DraftStatement | None:
        if "暗恋" in idea and "女孩" in idea:
            text = "叙述者暗恋一名女孩；女孩回头偷看叙述者时被察觉，尴尬和害羞来自这次突然的视线相遇。"
        elif any(word in idea for word in ("回头", "发现", "遇见", "等待", "离开", "追逐", "看了")):
            text = f"这是一个具有前后关系的瞬间：{idea}。画面需要保留动作发生后紧接着出现的情绪变化。"
        else:
            return None
        return DraftStatement(text=text, origin="user", status="confirmed")


__all__ = ["InspirationService", "ModelGatewayError"]
