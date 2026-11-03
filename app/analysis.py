"""On-demand analysis run: drift and priority for every Portfolio (ADR-0001).

A run replaces the earlier ones as the current result (highest run id wins; history is kept).
CLI: uv run python -m app.analysis
"""
import json
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config_service import get_config
from app.db import AccountRow, AnalysisRunRow, ClientRow, HoldingRow, PriorityResultRow, TargetRow
from app.drift import compute_drift
from app.market_data import MarketData
from app.priority import score_portfolio

SYSTEM = audit.Actor.system("priority-engine")


def _values_by_client(db: Session, market: MarketData) -> dict[str, dict[str, float]]:
    """client_id -> asset class -> market value."""
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for h, a in db.execute(select(HoldingRow, AccountRow).join(AccountRow, HoldingRow.account_id == AccountRow.id)):
        inst = market.instrument(h.symbol)
        out[a.client_id][inst.asset_class] += h.quantity * inst.price
    return out


def run_analysis(db: Session, market: MarketData, actor: audit.Actor) -> tuple[int, int]:
    """Score every Portfolio. Returns (run_id, portfolios scored)."""
    cfg = get_config(db)
    as_of = date.fromisoformat(market.as_of[:10])
    values = _values_by_client(db, market)
    targets: dict[str, dict[str, float]] = defaultdict(dict)
    for t in db.scalars(select(TargetRow)):
        targets[t.client_id][t.asset_class] = t.weight
    clients = list(db.scalars(select(ClientRow).order_by(ClientRow.id)))

    run = AnalysisRunRow(
        started_at=audit.format_ts(datetime.now(timezone.utc)), actor_name=actor.name, as_of=as_of.isoformat(),
        config_json=cfg.model_dump_json(),
    )
    db.add(run)
    db.flush()
    scored = []
    for c in clients:
        by_class = values.get(c.id, {})
        total = sum(by_class.values())
        actual = {k: v / total for k, v in by_class.items()} if total else {}
        band = cfg.tolerance_bands[c.risk_profile]
        drift = compute_drift(actual, targets[c.id], band)
        days_past_due = (as_of - date.fromisoformat(c.review_due)).days
        s = score_portfolio(drift, band, cfg.priority_weights, days_past_due=days_past_due, sla_days=cfg.sla_days)
        components = [{"name": x.name, "raw": round(x.raw, 2), "weight": x.weight, "points": round(x.points, 2)} for x in s.components]
        drift_out = [
            {"asset_class": d.asset_class, "actual_pct": round(d.actual_pct, 2), "target_pct": round(d.target_pct, 2),
             "signed_pp": round(d.signed_pp, 2), "drift_pp": round(d.drift_pp, 2), "status": d.status}
            for d in drift.classes
        ]
        db.add(PriorityResultRow(
            run_id=run.id, client_id=c.id, score=round(s.score, 2), label=s.label, risk_profile=c.risk_profile,
            review_due=c.review_due, days_past_due=days_past_due, sla_breached=s.sla_breached,
            portfolio_drift_pp=round(drift.portfolio_drift_pp, 2), total_value=round(total, 2),
            components_json=json.dumps(components), drift_json=json.dumps(drift_out),
        ))
        scored.append((c, s, components, drift.portfolio_drift_pp))
    db.flush()

    started = audit.record(
        db, "analysis_run_started", actor,
        {"run_id": run.id, "as_of": run.as_of, "portfolios": len(clients), "config": json.loads(run.config_json)},
    )
    for c, s, components, pd in scored:
        audit.record(
            db, "priority_scored", SYSTEM,
            {"run_id": run.id, "score": round(s.score, 2), "label": s.label, "components": components,
             "portfolio_drift_pp": round(pd, 2), "days_past_due": s.days_past_due, "sla_breached": s.sla_breached},
            parents=[started], portfolio_id=c.id, client_id=c.id,
        )
    run.completed = True
    db.commit()
    return run.id, len(clients)


def main(settings=None) -> int:
    from app.db import make_session_factory
    from app.settings import Settings

    settings = settings or Settings()
    market = MarketData.load(settings.market_data_snapshot_path, settings.fund_lookthrough_path)
    with make_session_factory(settings.database_url)() as db:
        run_id, n = run_analysis(db, market, audit.Actor.system("cli"))
    print(f"analysis run {run_id}: scored {n} portfolios")
    return n


if __name__ == "__main__":
    main()
