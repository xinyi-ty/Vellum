"""Public API models for the Vellum inspiration workflow."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CreationMode(StrEnum):
    faithful = "faithful"
    collaborative = "collaborative"
    exploratory = "exploratory"


class DraftStatement(BaseModel):
    text: str = Field(..., min_length=1, max_length=600)
    origin: Literal["user", "assistant"]
    status: Literal["confirmed", "suggested"]


class DraftConstraints(BaseModel):
    must_keep: list[str] = Field(default_factory=list, max_length=12)
    avoid: list[str] = Field(default_factory=list, max_length=12)


class VisualDraft(BaseModel):
    scene_context: DraftStatement | None = None
    core_intent: DraftStatement
    facts: list[DraftStatement] = Field(default_factory=list, max_length=12)
    visual_language: list[DraftStatement] = Field(default_factory=list, max_length=12)
    constraints: DraftConstraints = Field(default_factory=DraftConstraints)


class QuestionOption(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=80)
    effect: str = Field(..., min_length=1, max_length=240)


class KeyQuestion(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    prompt: str = Field(..., min_length=1, max_length=240)
    why_it_matters: str = Field(..., min_length=1, max_length=240)
    options: list[QuestionOption] = Field(..., min_length=2, max_length=3)


class InspirationHint(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=40)
    suggestion: str = Field(..., min_length=1, max_length=240)
    example: str = Field(..., min_length=1, max_length=240)


class InspirationState(BaseModel):
    original_idea: str = Field(..., min_length=1, max_length=4000)
    mode: CreationMode = CreationMode.collaborative
    understanding: str = Field(..., min_length=1, max_length=1000)
    draft: VisualDraft
    question: KeyQuestion | None = None
    inspiration_hints: list[InspirationHint] = Field(default_factory=list, max_length=4)
    questions_asked: int = Field(0, ge=0, le=2)
    status: Literal["needs_input", "ready"]

    @model_validator(mode="after")
    def validate_status(self):
        if self.status == "needs_input" and self.question is None:
            raise ValueError("needs_input state requires a question")
        if self.status == "ready" and self.question is not None:
            raise ValueError("ready state cannot include a question")
        return self


class StartInspirationRequest(BaseModel):
    idea: str = Field(..., min_length=1, max_length=4000)
    mode: CreationMode = CreationMode.collaborative


class AnswerInput(BaseModel):
    option_id: str | None = Field(None, max_length=80)
    text: str | None = Field(None, max_length=1000)
    use_ai_decide: bool = False

    @model_validator(mode="after")
    def validate_answer(self):
        supplied = int(bool(self.option_id)) + int(bool(self.text and self.text.strip())) + int(self.use_ai_decide)
        if supplied != 1:
            raise ValueError("provide exactly one of option_id, text, or use_ai_decide")
        return self


class AnswerQuestionRequest(BaseModel):
    state: InspirationState
    answer: AnswerInput


class ReviseDraftRequest(BaseModel):
    state: InspirationState
    instruction: str = Field(..., min_length=1, max_length=2000)


class RefreshHintsRequest(BaseModel):
    state: InspirationState
    excluded_examples: list[str] = Field(default_factory=list, max_length=40)


class CompilePromptRequest(BaseModel):
    state: InspirationState


class CompiledPrompt(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    negative_prompt: str = Field(default="", max_length=3000)
    creative_summary: str = Field(..., min_length=1, max_length=1000)


class TurnResult(BaseModel):
    understanding: str
    draft: VisualDraft
    question: KeyQuestion | None = None
    inspiration_hints: list[InspirationHint] = Field(..., min_length=4, max_length=4)


class HintBatch(BaseModel):
    inspiration_hints: list[InspirationHint] = Field(..., min_length=4, max_length=4)
