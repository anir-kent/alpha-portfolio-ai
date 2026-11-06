"""Advisor-facing summary of the AI steps behind a Recommendation (ADR-0004).

Derived from the Exchange each step's Audit Event references. It carries only what lets a reader judge how far to rely on
a step: mode, latency, grounded counts and the transport outcome. No system text, prompt or reply text ever leaves here;
the Exchange id is included only when the caller may open the Exchange (`llm:read`).
"""
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import AuditEventRow, LlmExchangeRow

STEP_OF_EVENT = {"research_tilt_proposed": "tilt", "memo_generated": "memo"}
REASON_CHARS = 200


@dataclass
class AiStep:
    step: str  # tilt | memo
    mode: str  # live | recorded
    latency_ms: int | None
    telemetry: str  # measured | not_available_replayed
    outcome: str  # ok | failed
    reason: str | None  # why a failed step failed, cut short
    grounded: int | None  # Claims the validator accepted; None for a step that makes no Claims
    ungrounded: int | None
    exchange_id: int | None = None


def summaries(db: Session, recommendation_id: int, *, include_exchange_id: bool) -> list[AiStep]:
    latest: dict[str, AuditEventRow] = {}
    for ev in db.scalars(select(AuditEventRow).where(
        AuditEventRow.recommendation_id == str(recommendation_id), AuditEventRow.type.in_(STEP_OF_EVENT),
    ).order_by(AuditEventRow.id)):
        latest[STEP_OF_EVENT[ev.type]] = ev
    out = []
    for step, ev in latest.items():
        exchange_id, _ = audit.exchange_reference(ev.payload_json)
        exchange = db.get(LlmExchangeRow, exchange_id) if exchange_id is not None else None
        if exchange is None:
            continue  # pre-capture event: nothing to summarise
        payload = json.loads(ev.payload_json)
        failed = payload.get("status") == "failed"
        counts = payload.get("summary") or {}
        reason = (exchange.error or payload.get("error") or "")[:REASON_CHARS] if failed else None
        out.append(AiStep(
            step=step, mode=exchange.mode, latency_ms=exchange.latency_ms,
            telemetry="measured" if exchange.mode == "live" else "not_available_replayed",
            outcome="failed" if failed else "ok", reason=reason or None,
            grounded=counts.get("grounded") if not failed else None,
            ungrounded=counts.get("ungrounded") if not failed else None,
            exchange_id=exchange.id if include_exchange_id else None,
        ))
    return out
