"""Queue narrative: a short, cited "why this client, why now" per priority result (ADR-0001).

The score is already final when this runs; the LLM sees the engine's figures and the approved Insights on sectors the
Portfolio holds, and writes claims. Every claim goes through the grounding validator. The summary shown on the queue is
assembled here, by the engine, from the *grounded* claims only; flagged claims stay visible beside it, marked as flagged.
A failing LLM leaves the queue row exactly as it was.
"""
import json
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, grounding, portfolio_view, reports
from app.db import AuditEventRow, PriorityNarrativeRow, PriorityResultRow
from app.llm import LlmClient, LlmError, LlmRequest
from app.market_data import MarketData
from app.narrative import citation_label
from app.opportunity import relevant_insights
from app.prompts import PRIORITY_NARRATIVE


class NarrativeReply(BaseModel):
    claims: list[grounding.Claim]


def figures(result: PriorityResultRow, sector_pct: dict[str, float]) -> dict[str, float]:
    """Every number the engine produced for this queue row, by name."""
    f = {
        "priority_score": result.score, "portfolio_drift_pp": result.portfolio_drift_pp,
        "days_past_due": float(result.days_past_due), "total_value": result.total_value,
    }
    for c in json.loads(result.components_json):
        for key in ("raw", "weight", "points"):
            f[f"component.{c['name']}.{key}"] = c[key]
    for d in json.loads(result.drift_json):
        for key in ("actual_pct", "target_pct", "signed_pp", "drift_pp"):
            f[f"drift.{d['asset_class']}.{key}"] = d[key]
    for sector, pct in sector_pct.items():
        f[f"exposure.sector.{sector}"] = round(pct, 2)
    return f


def _request(result: PriorityResultRow, fig: dict[str, float], insights: list) -> LlmRequest:
    payload = {
        "portfolio_id": result.client_id, "risk_profile": result.risk_profile, "figures": fig,
        "insights": [
            {"id": i.id, "subject": i.subject, "direction": i.direction, "confidence": i.confidence,
             "report_id": i.report_id, "page": i.page, "passage": i.passage}
            for i in insights
        ],
    }
    return LlmRequest(
        task=PRIORITY_NARRATIVE.name, prompt_version=PRIORITY_NARRATIVE.label, system=PRIORITY_NARRATIVE.system,
        user=json.dumps(payload, sort_keys=True), schema=NarrativeReply.model_json_schema(),
    )


def build_summary(results: list[grounding.ClaimResult]) -> str | None:
    """Deterministic: only grounded claims, each with its citations. None when nothing was grounded."""
    kept = grounding.memo_claims(results)
    if not kept:
        return None
    return " ".join(f"{r.text} [{'; '.join(citation_label(c) for c in r.citations)}]" for r in kept)


def _scored_event_id(db: Session, run_id: int, client_id: str) -> int | None:
    events = db.scalars(
        select(AuditEventRow).where(AuditEventRow.type == "priority_scored", AuditEventRow.client_id == client_id)
        .order_by(AuditEventRow.id.desc())
    )
    return next((e.id for e in events if json.loads(e.payload_json).get("run_id") == run_id), None)


def generate(db: Session, llm: LlmClient, result: PriorityResultRow, market: MarketData) -> PriorityNarrativeRow | None:
    """None (and no LLM call) when no approved Insight is relevant to the Portfolio's holdings."""
    now = audit.format_ts(datetime.now(timezone.utc))
    scope = dict(portfolio_id=result.client_id, client_id=result.client_id)
    sector_pct = portfolio_view.sector_pct(portfolio_view.holdings(db, market, result.client_id), market)
    insights = relevant_insights(sector_pct, reports.approved_insights(db))
    if not insights:
        return None
    offered = [i.id for i in insights]
    scored = _scored_event_id(db, result.run_id, result.client_id)
    parents = [scored] if scored else []
    fig = figures(result, sector_pct)
    try:
        response = llm.complete(_request(result, fig, insights))
        reply = NarrativeReply.model_validate(response.content)
    except (LlmError, ValidationError) as e:
        row = PriorityNarrativeRow(
            run_id=result.run_id, client_id=result.client_id, status="failed", error=str(e)[:300],
            prompt_version=PRIORITY_NARRATIVE.label, created_at=now,
        )
        db.add(row)
        db.commit()
        audit.record(
            db, "priority_narrative_generated", audit.Actor.system("priority-narrator", prompt_version=PRIORITY_NARRATIVE.label),
            {"run_id": result.run_id, "status": "failed", "error": row.error, "insight_ids": offered}, parents=parents, **scope,
        )
        return row
    check_id, results = grounding.validate_figures(
        db, reply.claims, fig, client_id=result.client_id, run_id=result.run_id, parents=parents,
    )
    row = PriorityNarrativeRow(
        run_id=result.run_id, client_id=result.client_id, status="complete", check_id=check_id, model=response.model,
        prompt_version=response.prompt_version, created_at=now, summary=build_summary(results),
    )
    db.add(row)
    db.commit()
    audit.record(
        db, "priority_narrative_generated",
        audit.Actor.system("priority-narrator", model=response.model, prompt_version=response.prompt_version),
        {"run_id": result.run_id, "status": "complete", "check_id": check_id, "summary": grounding.summarise(results),
         "insight_ids": offered},
        parents=parents, **scope,
    )
    return row


def generate_for_run(db: Session, llm: LlmClient, run_id: int, market: MarketData) -> None:
    for result in db.scalars(select(PriorityResultRow).where(PriorityResultRow.run_id == run_id).order_by(PriorityResultRow.client_id)).all():
        generate(db, llm, result, market)
