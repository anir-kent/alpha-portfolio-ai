"""Recommendation rationale and advisor memo (ADR-0001).

The LLM writes cited claims about a Recommendation from the engine's figures and approved research passages. Every claim goes
through the grounding validator. The Advisor sees all claims, flagged ones included; the memo is assembled here, by the
engine, from the engine's own figures plus the *grounded* claims only. A failing LLM leaves the Recommendation untouched.
"""
import json
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, grounding, recommendations, reports
from app.db import RecommendationNarrativeRow, RecommendationRow, RecommendationTiltRow
from app.llm import LlmClient, LlmError, LlmRequest, exchange_ref
from app.prompts import RECOMMENDATION_NARRATIVE


class NarrativeReply(BaseModel):
    claims: list[grounding.Claim]


def _request(db: Session, rec: RecommendationRow) -> LlmRequest:
    tilt = db.get(RecommendationTiltRow, rec.id)
    payload = {
        "portfolio_id": rec.client_id,
        "figures": grounding.engine_figures(db, rec),
        "tilts": json.loads(tilt.entries_json) if tilt and tilt.status == "ok" else [],
        "insights": [
            {"id": i.id, "subject": i.subject, "direction": i.direction, "report_id": i.report_id, "page": i.page,
             "passage": i.passage}
            for i in reports.approved_insights(db)
        ],
    }
    return LlmRequest(
        task=RECOMMENDATION_NARRATIVE.name, prompt_version=RECOMMENDATION_NARRATIVE.label,
        system=RECOMMENDATION_NARRATIVE.system, user=json.dumps(payload, sort_keys=True),
        schema=NarrativeReply.model_json_schema(),
    )


def citation_label(c) -> str:
    return f"{c.report_id} p.{c.page}" if isinstance(c, grounding.ReportCitation) else c.figure


def build_memo(rec: RecommendationRow, tilt: RecommendationTiltRow | None, results: list[grounding.ClaimResult]) -> str:
    """Deterministic: engine figures first, then only the grounded claims with their citations."""
    lines = json.loads(rec.trade_lines_json)
    sells = sum(1 for l in lines if l["side"] == "sell")
    out = [
        f"Advisor memo: Portfolio {rec.client_id}, Recommendation version {rec.version}.",
        f"Engine: {len(lines)} Trade Lines ({sells} sell, {len(lines) - sells} buy), turnover {rec.turnover_pct:.1f}% of "
        f"${rec.total_value:,.0f}; post-trade suitability {rec.suitability_status}.",
    ]
    if tilt and tilt.status == "ok":
        for e in json.loads(tilt.entries_json):
            out.append(
                f"Research Tilt on {e['subject']} (bound {tilt.bound_pp:g} pp): AI proposed {e['proposed_pp']:+.1f} pp, "
                f"engine allowed {e['allowed_pp']:+.1f} pp."
            )
    kept = grounding.memo_claims(results)
    if kept:
        out.append("Supported by cited research:")
        out += [f"- {r.text} [{'; '.join(citation_label(c) for c in r.citations)}]" for r in kept]
    return "\n".join(out)


def generate(db: Session, llm: LlmClient, rec: RecommendationRow) -> RecommendationNarrativeRow:
    now = audit.format_ts(datetime.now(timezone.utc))
    scope = dict(portfolio_id=rec.client_id, client_id=rec.client_id, recommendation_id=str(rec.id))
    response = None
    try:
        response = llm.complete(_request(db, rec))
        reply = NarrativeReply.model_validate(response.content)
    except (LlmError, ValidationError) as e:
        row = RecommendationNarrativeRow(
            recommendation_id=rec.id, status="failed", error=str(e)[:300], prompt_version=RECOMMENDATION_NARRATIVE.label,
            created_at=now,
        )
        db.add(row)
        db.commit()
        audit.record(
            db, "memo_generated", audit.Actor.system("memo-writer", prompt_version=RECOMMENDATION_NARRATIVE.label),
            {"status": "failed", "error": row.error, **exchange_ref(e if isinstance(e, LlmError) else response)}, parents=[p for p in [recommendations.last_event_id(db, rec.id)] if p], **scope,
        )
        return row
    check_id, results = grounding.validate(db, rec, reply.claims)
    memo = build_memo(rec, db.get(RecommendationTiltRow, rec.id), results)
    row = RecommendationNarrativeRow(
        recommendation_id=rec.id, status="complete", check_id=check_id, model=response.model,
        prompt_version=response.prompt_version, created_at=now, memo=memo,
    )
    db.add(row)
    db.commit()
    audit.record(
        db, "memo_generated", audit.Actor.system("memo-writer", model=response.model, prompt_version=response.prompt_version),
        {"status": "complete", "check_id": check_id, "summary": grounding.summarise(results), "memo_chars": len(memo), **exchange_ref(response)},
        parents=[p for p in [recommendations.last_event_id(db, rec.id)] if p], **scope,
    )
    return row


def generate_for_run(db: Session, llm: LlmClient, run_id: int) -> int:
    """A memo for each of the run's Recommendations that had approved research in play. Returns how many failed."""
    recs = db.scalars(
        select(RecommendationRow).join(RecommendationTiltRow, RecommendationTiltRow.recommendation_id == RecommendationRow.id)
        .where(RecommendationRow.run_id == run_id).order_by(RecommendationRow.id)
    ).all()
    return sum(generate(db, llm, rec).status == "failed" for rec in recs)
