"""On-demand analysis run: drift and priority for every Portfolio (ADR-0001).

A run replaces the earlier ones as the current result (highest run id wins; history is kept).
CLI: uv run python -m app.analysis
"""
import json
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, narrative, portfolio_view, priority_narrative, rebalance, recommendations, reports, research_tilt, suitability
from app.config_service import get_config
from app.db import AnalysisRunRow, ClientRow, PriorityResultRow, RestrictionRow, SuitabilityResultRow, TargetRow
from app.drift import compute_drift
from app.llm import LlmClient, build_llm
from app.market_data import MarketData
from app.opportunity import opportunity_raw, relevant_insights
from app.priority import score_portfolio
from app.run_steps import AI_STEP_KEYS, NullReporter, RunStepReporter, run_ai_steps, run_step

SYSTEM = audit.Actor.system("priority-engine")


def open_run(db: Session, market: MarketData, actor: audit.Actor) -> AnalysisRunRow:
    """Add a new, not yet completed Analysis Run row (flushed, not committed)."""
    run = AnalysisRunRow(
        started_at=audit.format_ts(datetime.now(timezone.utc)), actor_name=actor.name, as_of=market.as_of[:10],
        config_json=get_config(db).model_dump_json(),
    )
    db.add(run)
    db.flush()
    return run


def run_analysis(
    db: Session, market: MarketData, actor: audit.Actor, llm: LlmClient | None = None,
    reporter: RunStepReporter | None = None, run_id: int | None = None,
) -> tuple[int, int]:
    """Score every Portfolio. Returns (run_id, portfolios scored). With an `llm`, a Portfolio being rebalanced also gets an
    engine-bounded Research Tilt from approved Insights (a failing LLM only means no tilt). A `reporter` is told about
    each Run Step as it goes (ADR-0005); without one, progress goes nowhere. `run_id` names a run row already committed
    by `open_run` (the background run); without one, the row is added in this run's transaction."""
    reporter = reporter or NullReporter()
    with run_step(reporter, "load_inputs"):
        cfg = get_config(db)
        as_of = date.fromisoformat(market.as_of[:10])
        restrictions: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for r in db.scalars(select(RestrictionRow)):
            restrictions[r.client_id].append((r.kind, r.value))
        targets: dict[str, dict[str, float]] = defaultdict(dict)
        for t in db.scalars(select(TargetRow)):
            targets[t.client_id][t.asset_class] = t.weight
        clients = list(db.scalars(select(ClientRow).order_by(ClientRow.id)))

        run = db.get_one(AnalysisRunRow, run_id) if run_id is not None else open_run(db, market, actor)
        run.as_of, run.config_json = as_of.isoformat(), cfg.model_dump_json()  # what this run actually used
        db.flush()
        insights = reports.approved_insights(db)  # the only research that can raise a score
        stale = recommendations.open_ids(db)  # superseded once this run is on record
    with run_step(reporter, "score_portfolios"):
        reporter.portfolios_scored(0, len(clients))
        scored = []
        opportunity_ids: dict[str, list[int]] = {}  # the approved Insights behind each Portfolio's Opportunity
        for c in clients:
            rows = portfolio_view.holdings(db, market, c.id)
            by_class: dict[str, float] = defaultdict(float)
            for h in rows:
                by_class[h["asset_class"]] += h["market_value"]
            total = sum(by_class.values())
            actual = {k: v / total for k, v in by_class.items()} if total else {}
            band = cfg.tolerance_bands[c.risk_profile]
            drift = compute_drift(actual, targets[c.id], band)
            days_past_due = (as_of - date.fromisoformat(c.review_due)).days
            suit = suitability.evaluate(
                rows,
                suitability.ClientContext(c.risk_profile, c.horizon_years, c.liquidity_needs_pct, restrictions[c.id]),
                cfg.suitability, market,
            )
            sector_pct = portfolio_view.sector_pct(rows, market)
            s = score_portfolio(
                drift, band, cfg.priority_weights, days_past_due=days_past_due, sla_days=cfg.sla_days,
                suitability_risk=suitability.risk_points(suit),
                opportunity=opportunity_raw(sector_pct, insights),
            )
            opportunity_ids[c.id] = [i.id for i in relevant_insights(sector_pct, insights)]
            components = [
                {"name": x.name, "raw": round(x.raw, 2), "weight": x.weight, "points": round(x.points, 2)}
                for x in s.components
            ]
            drift_out = [
                {"asset_class": d.asset_class, "actual_pct": round(d.actual_pct, 2),
                 "target_pct": round(d.target_pct, 2), "signed_pp": round(d.signed_pp, 2),
                 "drift_pp": round(d.drift_pp, 2), "status": d.status}
                for d in drift.classes
            ]
            db.add(PriorityResultRow(
                run_id=run.id, client_id=c.id, score=round(s.score, 2), label=s.label, risk_profile=c.risk_profile,
                review_due=c.review_due, days_past_due=days_past_due, sla_breached=s.sla_breached,
                portfolio_drift_pp=round(drift.portfolio_drift_pp, 2), total_value=round(total, 2),
                components_json=json.dumps(components), drift_json=json.dumps(drift_out),
            ))
            suit_out = suitability.to_dicts(suit)
            db.add(SuitabilityResultRow(
                run_id=run.id, client_id=c.id, status=suitability.overall(suit), results_json=json.dumps(suit_out),
            ))
            tilt = None
            if llm is not None and rebalance.outside_tolerance(drift):
                tilt = research_tilt.assess(
                    db, llm.bind(db) if hasattr(llm, "bind") else llm, client=c, rows=rows, market=market, cfg=cfg,
                )
            rec = recommendations.draft(
                db, run_id=run.id, rows=rows, client=c, targets=targets[c.id], restrictions=restrictions[c.id],
                tax={h["account_id"]: h["tax_status"] for h in rows}, cfg=cfg, market=market, drift=drift, tilt=tilt,
            )
            scored.append((c, s, components, drift.portfolio_drift_pp, suitability.overall(suit), suit_out, rec, tilt))
            reporter.portfolios_scored(len(scored), len(clients))
    with run_step(reporter, "record_run"):
        db.flush()

        started = audit.record(
            db, "analysis_run_started", actor,
            {"run_id": run.id, "as_of": run.as_of, "portfolios": len(clients), "config": json.loads(run.config_json)},
        )
        recommendations.supersede(
            db, stale, SYSTEM, "A newer analysis run replaced this Recommendation", parents=[started],
        )
        for c, s, components, pd, suit_status, suit_out, rec, tilt in scored:
            evaluated = audit.record(
                db, "suitability_evaluated", SYSTEM, {"run_id": run.id, "status": suit_status, "rules": suit_out},
                parents=[started], portfolio_id=c.id, client_id=c.id,
            )
            audit.record(
                db, "priority_scored", SYSTEM,
                {"run_id": run.id, "score": round(s.score, 2), "label": s.label, "components": components,
                 "portfolio_drift_pp": round(pd, 2), "days_past_due": s.days_past_due, "sla_breached": s.sla_breached,
                 "opportunity_insight_ids": opportunity_ids[c.id]},
                parents=[started, evaluated], portfolio_id=c.id, client_id=c.id,
            )
            if rec is not None:
                tilted = [research_tilt.audit_assessment(db, rec, tilt)] if tilt is not None else []
                recommendations.audit_draft(db, rec, parents=[started, evaluated, *tilted])
        run.completed = True
        if run_id is None:  # a run with no background runner to record its outcome (the CLI, the seeder)
            run.outcome, run.finished_at = "completed", audit.format_ts(datetime.now(timezone.utc))
        db.commit()
    if llm is None:
        for key in AI_STEP_KEYS:
            reporter.step_skipped(key)
    else:  # after the run is on record: a failing LLM cannot undo it
        run_ai_steps(reporter, [
            ("priority_narratives", lambda: priority_narrative.generate_for_run(db, llm, run.id, market)),
            ("recommendation_narratives", lambda: narrative.generate_for_run(db, llm, run.id)),
        ], recover=db.rollback)
    return run.id, len(clients)


def main(settings=None) -> int:
    from app.db import make_session_factory
    from app.settings import Settings

    settings = settings or Settings()
    market = MarketData.load(settings.market_data_snapshot_path, settings.fund_lookthrough_path)
    with make_session_factory(settings.database_url)() as db:
        run_id, n = run_analysis(db, market, audit.Actor.system("cli"), build_llm(settings))
    print(f"analysis run {run_id}: scored {n} portfolios")
    return n


if __name__ == "__main__":
    main()
