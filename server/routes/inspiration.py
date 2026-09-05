"""HTTP endpoints for the stateless Vellum inspiration workflow."""

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from ..models import (
    AnswerQuestionRequest,
    CompilePromptRequest,
    CompiledPrompt,
    InspirationState,
    ReviseDraftRequest,
    StartInspirationRequest,
)
from ..services.inspiration_service import InspirationService, ModelGatewayError

router = APIRouter(prefix="/inspirations", tags=["inspiration"])


def get_service() -> InspirationService:
    return InspirationService()


@router.post("", response_model=InspirationState)
def start_inspiration(request: StartInspirationRequest):
    try:
        return get_service().start(request.idea, request.mode)
    except (ModelGatewayError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/answer", response_model=InspirationState)
def answer_question(request: AnswerQuestionRequest):
    try:
        return get_service().answer(request.state, request.answer)
    except (ModelGatewayError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/compile", response_model=CompiledPrompt)
def compile_prompt(request: CompilePromptRequest):
    try:
        return get_service().compile(request.state)
    except (ModelGatewayError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/revise", response_model=InspirationState)
def revise_draft(request: ReviseDraftRequest):
    try:
        return get_service().revise(request.state, request.instruction)
    except (ModelGatewayError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
