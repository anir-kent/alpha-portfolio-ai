"""Recommendations and the Advisor's Decisions (Advisor-only path, no tilt).

A Recommendation is a set of Trade Lines for one Portfolio. Its numbers and post-trade suitability come from the
deterministic engines (ADR-0001). Modifying creates a new linked version; nothing is ever executed, and "approved"
means cleared to act outside this system.

Status: pending_advisor -> pending_compliance (rule breach) -> pending_committee (high-impact) -> approved, with
rejected at any step and superseded when replaced. Which steps apply is app.approvals; Approved needs a human Decision
at every required step.
"""
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import approvals, audit, portfolio_view, rebalance, research_tilt, suitability
from app.config_service import Config
from app.db import AccountRow, AuditEventRow, ClientRow, DecisionRow, RecommendationRow, RestrictionRow, TargetRow
from app.drift import compute_drift
from app.market_data import MarketData
from app.rebalance import TradeLine

ENGINE = audit.Actor.system("rebalancing-engine")
OPEN = ("pending_advisor", "pending_compliance", "pending_committee")  # a new analysis run supersedes these


class DecisionError(Exception):
    """A Decision that cannot be recorded; `status` is the HTTP status to report."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Evaluation:
    trade_lines: list[dict]
    turnover_pct: float
    total_value: float
    suitability: list[suitability.RuleResult]
    post_trade_drift: list[dict]


def _now() -> str:
    return audit.format_ts(datetime.now(UTC))


def client_inputs(db: Session, client_id: str) -> tuple[ClientRow, dict[str, float], list[tuple[str, str]], dict[str, str]]:
    """The Client, Target Allocation, Restrictions and the tax status of each Account."""
    client = db.get_one(ClientRow, client_id)
    targets = {t.asset_class: t.weight for t in db.scalars(select(TargetRow).where(TargetRow.client_id == client_id))}
    restrictions = [(r.kind, r.value) for r in db.scalars(select(RestrictionRow).where(RestrictionRow.client_id == client_id))]
    tax = {a.id: a.tax_status for a in db.scalars(select(AccountRow).where(AccountRow.client_id == client_id))}
    return client, targets, restrictions, tax


def evaluate_lines(
    lines: list[TradeLine], rows: list[dict], client: ClientRow, targets: dict[str, float],
    restrictions: list[tuple[str, str]], tax: dict[str, str], cfg: Config, market: MarketData,
) -> Evaluation:
    """Price the Trade Lines and run the Suitability Rules and drift on the post-trade Portfolio."""
    total = sum(r["market_value"] for r in rows)
    out: list[dict[str, Any]] = []
    for line in lines:
        inst = market.instrument(line.symbol)
        amount = line.quantity * inst.price
        out.append({
            "account_id": line.account_id, "symbol": line.symbol, "name": inst.name, "side": line.side, "quantity": line.quantity,
            "price": inst.price, "currency": inst.currency, "amount": round(amount, 2),
            "pct_of_portfolio": round(amount / total * 100, 2) if total else 0.0,
        })
    gross = sum(x["amount"] for x in out)
    post = rebalance.apply(lines, rows, tax, market)
    post_total = sum(r["market_value"] for r in post)
    by_class: dict[str, float] = {}
    for r in post:
        by_class[r["asset_class"]] = by_class.get(r["asset_class"], 0.0) + r["market_value"]
    actual = {k: v / post_total for k, v in by_class.items()} if post_total else {}
    drift = compute_drift(actual, targets, cfg.tolerance_bands[client.risk_profile])
    suit = suitability.evaluate(
        post, suitability.ClientContext(client.risk_profile, client.horizon_years, client.liquidity_needs_pct, restrictions),
        cfg.suitability, market,
    )
    return Evaluation(
        out, round(gross / 2 / total * 100, 2) if total else 0.0, total, suit,
        [{"asset_class": d.asset_class, "actual_pct": round(d.actual_pct, 2), "target_pct": round(d.target_pct, 2),
          "signed_pp": round(d.signed_pp, 2), "drift_pp": round(d.drift_pp, 2), "status": d.status} for d in drift.classes],
    )


def _summary(drift_rows: list[dict], ev: Evaluation, tilt: "research_tilt.Assessment | None" = None) -> str:
    moves = "; ".join(
        f"{d['asset_class']} {d['actual_pct']:.1f}% vs {d['target_pct']:.1f}% target ({d['signed_pp']:+.1f} pp, {d['status']})"
        for d in drift_rows
    )
    sells = sum(1 for line in ev.trade_lines if line["side"] == "sell")
    applied = [e for e in tilt.entries if e.allowed_pp] if tilt and tilt.status == "ok" else []
    basis = (
        "Rule-based and band-based, with an engine-bounded Research Tilt on "
        + ", ".join(f"{e.subject} ({e.allowed_pp:+.1f} pp)" for e in applied) + "."
        if applied else "Rule-based and band-based; no research tilt applied."
    )
    return (
        f"Rebalance to target: {moves}. {sells} sell and {len(ev.trade_lines) - sells} buy Trade Lines, "
        f"turnover {ev.turnover_pct:.1f}% of the Portfolio. {basis}"
    )


def _row(client_id: str, run_id: int, version: int, parent: RecommendationRow | None, by: str, summary: str, ev: Evaluation) -> RecommendationRow:
    return RecommendationRow(
        client_id=client_id, root_id=parent.root_id if parent else 0, parent_id=parent.id if parent else None, version=version,
        run_id=run_id, status="pending_advisor", created_at=_now(), created_by=by, summary=summary,
        total_value=round(ev.total_value, 2), turnover_pct=ev.turnover_pct, trade_lines_json=json.dumps(ev.trade_lines),
        suitability_status=suitability.overall(ev.suitability), suitability_json=json.dumps(suitability.to_dicts(ev.suitability)),
        post_trade_drift_json=json.dumps(ev.post_trade_drift),
    )


def draft(
    db: Session, *, run_id: int, rows: list[dict], client: ClientRow, targets: dict[str, float],
    restrictions: list[tuple[str, str]], tax: dict[str, str], cfg: Config, market: MarketData, drift,
    tilt: "research_tilt.Assessment | None" = None,
) -> RecommendationRow | None:
    """Version 1 for a Portfolio outside tolerance, or None. Added to the session but not committed.

    An engine-bounded Research Tilt (already clipped, see app.research_tilt) shifts the Asset-Class targets the Trade Lines
    aim at and adds sector switches inside equity; tolerance and post-trade drift are still measured against the real target."""
    restricted = {v for k, v in restrictions if k == "instrument"}
    usable = tilt if tilt is not None and tilt.status == "ok" else None
    aim = research_tilt.tilted_targets(targets, usable.allowed("asset_class"), usable.bound_pp) if usable is not None else targets
    lines = rebalance.plan(rows, aim, restricted, market, drift)
    if not lines:
        return None
    if usable is not None and usable.allowed("sector"):
        post = rebalance.apply(lines, rows, tax, market)
        sleeve = rebalance.sector_sleeve(
            post, usable.allowed("sector"), restricted, {v for k, v in restrictions if k == "sector"}, market,
            sum(r["market_value"] for r in rows),
        )
        lines = rebalance.merge(lines, sleeve)
    ev = evaluate_lines(lines, rows, client, targets, restrictions, tax, cfg, market)
    pre = [{"asset_class": d.asset_class, "actual_pct": d.actual_pct, "target_pct": d.target_pct, "signed_pp": d.signed_pp,
            "status": d.status} for d in drift.classes]
    row = _row(client.id, run_id, 1, None, ENGINE.name, _summary(pre, ev, tilt), ev)
    db.add(row)
    db.flush()
    row.root_id = row.id
    if tilt is not None:
        research_tilt.store(db, row, tilt)
    return row


def last_event_id(db: Session, recommendation_id: int) -> int | None:
    return db.scalar(
        select(AuditEventRow.id).where(AuditEventRow.recommendation_id == str(recommendation_id))
        .order_by(AuditEventRow.id.desc()).limit(1)
    )


def audit_draft(db: Session, rec: RecommendationRow, parents: list[int], actor: audit.Actor = ENGINE) -> int:
    """Audit the drafted Recommendation and its post-trade suitability. Returns the suitability event id."""
    drafted = audit.record(
        db, "recommendation_drafted", actor,
        {"version": rec.version, "run_id": rec.run_id, "trade_lines": json.loads(rec.trade_lines_json),
         "turnover_pct": rec.turnover_pct, "summary": rec.summary},
        parents=parents, portfolio_id=rec.client_id, client_id=rec.client_id, recommendation_id=str(rec.id),
    )
    return _audit_suitability(db, rec, drafted)


def _audit_suitability(db: Session, rec: RecommendationRow, parent: int) -> int:
    return audit.record(
        db, "suitability_evaluated", ENGINE,
        {"run_id": rec.run_id, "status": rec.suitability_status, "scope": "post_trade", "rules": json.loads(rec.suitability_json)},
        parents=[parent], portfolio_id=rec.client_id, client_id=rec.client_id, recommendation_id=str(rec.id),
    )


def open_ids(db: Session) -> list[int]:
    return list(db.scalars(select(RecommendationRow.id).where(RecommendationRow.status.in_(OPEN)).order_by(RecommendationRow.id)))


def supersede(db: Session, ids: list[int], actor: audit.Actor, reason: str, parents=()) -> None:
    """Mark the given Recommendations superseded (a new analysis run makes them stale) and audit each."""
    for rec in db.scalars(select(RecommendationRow).where(RecommendationRow.id.in_(ids)).order_by(RecommendationRow.id)):
        rec.status = "superseded"
        db.flush()
        audit.record(
            db, "recommendation_superseded", actor, {"reason": reason, "version": rec.version},
            parents=[p for p in [last_event_id(db, rec.id), *parents] if p], portfolio_id=rec.client_id,
            client_id=rec.client_id, recommendation_id=str(rec.id),
        )


def decide(
    db: Session, market: MarketData, cfg: Config, rec_id: int, action: str, rationale: str | None,
    lines: list[TradeLine] | None, actor: audit.Actor,
) -> tuple[RecommendationRow, DecisionRow, list[dict]]:
    """Record the Advisor's Decision. Returns (resulting version, decision, rules newly in breach)."""
    rec = db.get(RecommendationRow, rec_id)
    if rec is None:
        raise DecisionError(404, "Recommendation not found")
    if rec.status != "pending_advisor":
        raise DecisionError(409, f"Recommendation is {rec.status.replace('_', ' ')}; only a pending Recommendation can be decided")
    rationale = (rationale or "").strip() or None
    if action in ("reject", "modify") and not rationale:
        raise DecisionError(422, f"A rationale is required to {action} a Recommendation")

    new: RecommendationRow | None = None
    new_ev: Evaluation | None = None
    if action == "modify":
        if not lines:
            raise DecisionError(422, "A modification needs at least one Trade Line")
        client, targets, restrictions, tax = client_inputs(db, rec.client_id)
        rows = portfolio_view.holdings(db, market, rec.client_id)
        try:
            rebalance.validate(lines, rows, set(tax), market)
        except ValueError as e:
            raise DecisionError(422, str(e)) from e
        new_ev = evaluate_lines(lines, rows, client, targets, restrictions, tax, cfg, market)
        new = _row(rec.client_id, rec.run_id, rec.version + 1, rec, actor.name, "", new_ev)
        new.summary = f"Modified by {actor.name} from version {rec.version}: {rationale}"
        resulting = "superseded"
    elif action == "accept":
        resulting = approvals.next_status(approvals.plan(rec, cfg), "advisor")
    else:
        resulting = "rejected"

    rec.status = resulting
    decision = DecisionRow(
        recommendation_id=rec.id, client_id=rec.client_id, action=action, rationale=rationale, actor_name=actor.name,
        actor_role=actor.role or "", created_at=_now(), resulting_status=resulting,
    )
    db.add(decision)
    if new is not None:
        db.add(new)
    db.flush()
    new_breaches: list[dict] = []
    if new is not None:
        assert new_ev is not None  # set together with `new` on modify
        new.root_id = rec.root_id
        decision.resulting_recommendation_id = new.id
        before = {r["rule_id"] for r in json.loads(rec.suitability_json) if r["status"] == "breach"}
        new_breaches = [r for r in suitability.to_dicts(new_ev.suitability) if r["status"] == "breach" and r["rule_id"] not in before]

    d_event = audit.record(
        db, "decision_recorded", actor,
        {"action": action, "rationale": rationale, "version": rec.version, "resulting_status": resulting,
         "resulting_recommendation_id": decision.resulting_recommendation_id},
        parents=[p for p in [last_event_id(db, rec.id)] if p], portfolio_id=rec.client_id, client_id=rec.client_id,
        recommendation_id=str(rec.id),
    )
    if new is not None:
        modified = audit.record(
            db, "recommendation_modified", actor,
            {"parent_recommendation_id": rec.id, "version": new.version, "rationale": rationale,
             "trade_lines": json.loads(new.trade_lines_json), "turnover_pct": new.turnover_pct},
            parents=[d_event], portfolio_id=new.client_id, client_id=new.client_id, recommendation_id=str(new.id),
        )
        _audit_suitability(db, new, modified)
    db.commit()
    return (new or rec), decision, new_breaches


# (step, action) -> (stored Decision action, approves?, audit event type)
STEP_ACTIONS = {
    ("compliance", "approve"): ("approve_exception", True, "exception_approved"),
    ("compliance", "block"): ("block", False, "exception_blocked"),
    ("committee", "approve"): ("committee_approve", True, "decision_recorded"),
    ("committee", "reject"): ("committee_reject", False, "decision_recorded"),
}


def decide_step(
    db: Session, cfg: Config, rec_id: int, step: str, action: str, rationale: str | None, actor: audit.Actor,
) -> tuple[RecommendationRow, DecisionRow]:
    """Record a Compliance or Investment Committee Decision. Only a Recommendation waiting at exactly that step can
    be decided, so the order cannot be skipped; a rationale is mandatory and the Decision is audited."""
    rec = db.get(RecommendationRow, rec_id)
    if rec is None:
        raise DecisionError(404, "Recommendation not found")
    stored, approves, event_type = STEP_ACTIONS[(step, action)]
    if rec.status != approvals.PENDING_FOR[step]:
        waiting = rec.status.replace("_", " ")
        raise DecisionError(409, f"Recommendation is {waiting}; it is not waiting for a {step} Decision")
    rationale = (rationale or "").strip() or None
    if not rationale:
        raise DecisionError(422, f"A rationale is required to {action} at the {step} step")

    resulting = approvals.next_status(approvals.plan(rec, cfg), step) if approves else "rejected"
    rec.status = resulting
    decision = DecisionRow(
        recommendation_id=rec.id, client_id=rec.client_id, action=stored, rationale=rationale, actor_name=actor.name,
        actor_role=actor.role or "", created_at=_now(), resulting_status=resulting,
    )
    db.add(decision)
    db.flush()
    payload = {"action": stored, "rationale": rationale, "version": rec.version, "resulting_status": resulting}
    if event_type == "decision_recorded":
        payload["resulting_recommendation_id"] = None
    audit.record(
        db, event_type, actor, payload, parents=[p for p in [last_event_id(db, rec.id)] if p], portfolio_id=rec.client_id,
        client_id=rec.client_id, recommendation_id=str(rec.id),
    )
    db.commit()
    return rec, decision
