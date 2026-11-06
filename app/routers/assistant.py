"""Assistant API (sme-assistant spec, API contract). Every endpoint requires `assistant:use`."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import assistant
from app.assistant import Conversation, Turn
from app.db import SessionRow, User
from app.deps import find_session, get_db, get_llm, get_market, require
from app.llm import LlmClient
from app.market_data import MarketData
from app.screen_context import ScreenIdentity

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def _session(db: Session, request: Request) -> SessionRow:
    session = find_session(db, request)
    if session is None:  # expired between authentication and here
        raise HTTPException(401, "Not authenticated")
    return session


class QuestionIn(BaseModel):
    question: str = Field(min_length=1)
    screen: ScreenIdentity


@router.post("/questions", response_model=Turn, operation_id="askAssistant")
def ask(
    body: QuestionIn,
    request: Request,
    user: User = Depends(require("assistant:use")),
    db: Session = Depends(get_db),
    llm: LlmClient = Depends(get_llm),
    market: MarketData = Depends(get_market),
):
    session = _session(db, request)
    pairs = request.app.state.settings.assistant_history_pairs
    return assistant.ask(db, llm, market, user, session, body.question.strip(), body.screen, pairs)


@router.get(
    "/conversation",
    response_model=Conversation,
    responses={204: {"description": "No Question asked yet in this login session"}},
    operation_id="getAssistantConversation",
)
def conversation(request: Request, _: User = Depends(require("assistant:use")), db: Session = Depends(get_db)):
    """The current login session's Conversation, turns in order, for rendering after a reload."""
    conv = assistant.current_conversation(db, _session(db, request))
    return conv if conv is not None else Response(status_code=204)
