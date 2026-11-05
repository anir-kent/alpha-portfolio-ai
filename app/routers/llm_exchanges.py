import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import LlmExchangeRow
from app.deps import get_db, require

router = APIRouter(prefix="/api/llm", tags=["llm"])


class ExchangeOut(BaseModel):
    id: int
    created_at: str
    task: str
    prompt_version: str
    model: str | None
    mode: Literal["live", "recorded"]
    endpoint_host: str | None
    system_text: str
    user_prompt: str
    reply_schema: dict
    messages: list[dict] | None
    raw_reply: str | None
    parsed_content: dict | None
    usage: dict | None
    latency_ms: int | None
    outcome: Literal["ok", "error"]
    error: str | None
    hash: str


def _loads(text: str | None):
    return None if text is None else json.loads(text)


def exchange_out(r: LlmExchangeRow) -> ExchangeOut:
    return ExchangeOut(
        id=r.id, created_at=r.created_at, task=r.task, prompt_version=r.prompt_version, model=r.model, mode=r.mode,
        endpoint_host=r.endpoint_host, system_text=r.system_text, user_prompt=r.user_prompt,
        reply_schema=json.loads(r.reply_schema_json), messages=_loads(r.messages_json), raw_reply=r.raw_reply,
        parsed_content=_loads(r.parsed_content_json), usage=_loads(r.usage_json), latency_ms=r.latency_ms,
        outcome=r.outcome, error=r.error, hash=r.hash,
    )


@router.get("/exchanges/{exchange_id}", response_model=ExchangeOut, operation_id="getLlmExchange",
            dependencies=[Depends(require("llm:read"))])
def get_exchange(exchange_id: int, db: Session = Depends(get_db)):
    row = db.get(LlmExchangeRow, exchange_id)
    if row is None:
        raise HTTPException(404, "LLM exchange not found")
    return exchange_out(row)
