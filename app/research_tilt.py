"""Research Tilt: the LLM proposes, the engine disposes (ADR-0001).

For a Portfolio being rebalanced, the LLM is shown the engine's look-through exposure and the *approved* Insights only,
and proposes a tilt in percentage points per Insight. The engine then, deterministically:
- drops proposals for any Insight it did not offer (only approved Insights can influence a tilt);
- ignores the part of a proposal whose sign contradicts the Insight's direction;
- sums per subject (a sector or Asset Class) and clips the sum to +/- `tilt_bound_pp`.
Both the proposed and the allowed tilt are stored and audited. An Asset-Class tilt shifts that class's target weight
(`tilted_targets`); a sector tilt is a switch inside equity (`rebalance.sector_sleeve`). The LLM never produces another
number and never a compliance outcome; if it fails, the Recommendation is the plain rule-based one.
"""

import json
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, portfolio_view, reports
from app.config_service import Config
from app.db import AuditEventRow, ClientRow, InsightRow, RecommendationRow, RecommendationTiltRow
from app.llm import LlmClient, LlmError, LlmRequest, exchange_ref
from app.market_data import MarketData
from app.prompts import RESEARCH_TILT

ENGINE = audit.Actor.system("tilt-engine")
_DIRECTION_SIGN = {"positive": 1, "negative": -1, "neutral": 0}


class ProposedTilt(BaseModel):
    insight_id: int
    impact: str = Field(pattern="^(tailwind|headwind|neutral)$")
    tilt_pp: float = Field(allow_inf_nan=False)


class TiltProposal(BaseModel):
    tilts: list[ProposedTilt]


@dataclass
class TiltEntry:
    subject_kind: str
    subject: str
    exposure_pct: float
    proposed_pp: float
    allowed_pp: float
    reason: str
    insight_ids: list[int]
    clipped: bool  # the bound reduced it (a direction conflict is not a clip)


@dataclass
class Assessment:
    status: str  # ok | failed
    bound_pp: float
    insights: list[InsightRow]
    entries: list[TiltEntry] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    proposed: list[dict] = field(default_factory=list)  # what the LLM said, per Insight, as received
    model: str | None = None
    prompt_version: str = RESEARCH_TILT.label
    error: str | None = None
    exchange: dict = field(default_factory=dict)  # id and hash of the LLM Exchange, for the Audit Event

    def allowed(self, kind: str) -> dict[str, float]:
        return {e.subject: e.allowed_pp for e in self.entries if e.subject_kind == kind and e.allowed_pp}


def clip_tilt(proposed_pp: float, bound_pp: float) -> float:
    return max(-bound_pp, min(bound_pp, proposed_pp))


def exposures(rows: list[dict], market: MarketData) -> dict[str, dict[str, float]]:
    """Engine-computed share of Portfolio value (percent) by Asset Class and by look-through sector."""
    total = sum(r["market_value"] for r in rows)
    by_class: dict[str, float] = {}
    for r in rows:
        by_class[r["asset_class"]] = by_class.get(r["asset_class"], 0.0) + r["market_value"]
    return {
        "asset_class": {k: round(v / total * 100, 2) if total else 0.0 for k, v in sorted(by_class.items())},
        "sector": {e["sector"]: round(e["weight_pct"], 2) for e in portfolio_view.sector_exposure(rows, market)},
    }


def _request(client: ClientRow, exposure: dict, insights: list[InsightRow]) -> LlmRequest:
    payload = {
        "portfolio_id": client.id,
        "risk_profile": client.risk_profile,
        "exposure": exposure,
        "insights": [
            {
                "id": i.id,
                "subject_kind": i.subject_kind,
                "subject": i.subject,
                "direction": i.direction,
                "confidence": i.confidence,
                "report_id": i.report_id,
                "page": i.page,
                "passage": i.passage,
            }
            for i in insights
        ],
    }
    return LlmRequest(
        task=RESEARCH_TILT.name,
        prompt_version=RESEARCH_TILT.label,
        system=RESEARCH_TILT.system,
        user=json.dumps(payload, sort_keys=True),
        schema=TiltProposal.model_json_schema(),
    )


def evaluate(
    proposal: TiltProposal, insights: list[InsightRow], exposure: dict, bound_pp: float
) -> tuple[list[TiltEntry], list[dict]]:
    """The deterministic half: which proposals count, summed per subject and clipped to the bound."""
    by_id = {i.id: i for i in insights}
    groups: dict[tuple[str, str], dict] = {}
    dropped: list[dict] = []
    seen: set[int] = set()
    for t in proposal.tilts:
        insight = by_id.get(t.insight_id)
        if insight is None:
            dropped.append({"insight_id": t.insight_id, "reason": "not an approved Insight offered to the model"})
            continue
        if t.insight_id in seen:
            dropped.append({"insight_id": t.insight_id, "reason": "duplicate proposal for the Insight"})
            continue
        seen.add(t.insight_id)
        g = groups.setdefault(
            (insight.subject_kind, insight.subject), {"proposed": 0.0, "usable": 0.0, "ids": [], "conflict": False}
        )
        g["proposed"] += t.tilt_pp
        g["ids"].append(insight.id)
        sign = _DIRECTION_SIGN[insight.direction]
        if t.tilt_pp == 0 or (sign != 0 and (t.tilt_pp > 0) == (sign > 0)):
            g["usable"] += t.tilt_pp
        else:
            g["conflict"] = True
    entries = []
    for (kind, subject), g in sorted(groups.items()):
        allowed = round(clip_tilt(g["usable"], bound_pp), 2)
        was_clipped = allowed != round(g["usable"], 2)
        notes = []
        if g["conflict"]:
            notes.append("part of the proposal contradicts the Insight direction and was not applied")
        if was_clipped:
            notes.append(f"clipped to the {bound_pp:g} pp bound")
        entries.append(
            TiltEntry(
                subject_kind=kind,
                subject=subject,
                exposure_pct=exposure[kind].get(subject, 0.0),
                proposed_pp=round(g["proposed"], 2),
                allowed_pp=allowed,
                reason="; ".join(notes) or "within the bound",
                insight_ids=g["ids"],
                clipped=was_clipped,
            )
        )
    return entries, dropped


def assess(
    db: Session, llm: LlmClient, *, client: ClientRow, rows: list[dict], market: MarketData, cfg: Config
) -> Assessment | None:
    """Ask the LLM for a tilt and bound it. None when there is nothing approved to tilt on (no LLM call is made)."""
    insights = reports.approved_insights(db)
    if not insights:
        return None
    exposure = exposures(rows, market)
    result = Assessment(status="failed", bound_pp=cfg.tilt_bound_pp, insights=insights)
    response = None
    try:
        response = llm.complete(_request(client, exposure, insights))
        proposal = TiltProposal.model_validate(response.content)
    except (LlmError, ValidationError) as e:
        result.error = str(e)[:300]
        result.exchange = exchange_ref(e if isinstance(e, LlmError) else response)
        return result
    result.exchange = exchange_ref(response)
    result.status, result.model, result.prompt_version = "ok", response.model, response.prompt_version
    result.proposed = [{"insight_id": t.insight_id, "proposed_pp": t.tilt_pp} for t in proposal.tilts]
    result.entries, result.dropped = evaluate(proposal, insights, exposure, cfg.tilt_bound_pp)
    return result


def tilted_targets(targets: dict[str, float], class_tilts_pp: dict[str, float], bound_pp: float) -> dict[str, float]:
    """Target Allocation after Asset-Class tilts: tilted classes move by their pp, the others absorb the offset pro rata.
    If stacked tilts would push any class's target more than `bound_pp` from its original, all tilts are scaled back so none does."""
    tilts = {c: pp for c, pp in class_tilts_pp.items() if c in targets and pp}
    if not tilts:
        return dict(targets)

    def shifted(scale: float) -> dict[str, float]:
        shift = sum(tilts.values()) * scale / 100
        others = sum(w for c, w in targets.items() if c not in tilts) or 1.0
        out = {c: w + tilts[c] * scale / 100 if c in tilts else w - shift * w / others for c, w in targets.items()}
        out = {c: max(0.0, w) for c, w in out.items()}
        total = sum(out.values())
        return {c: w / total for c, w in out.items()}

    out = shifted(1.0)
    moved = max(abs(out[c] - targets[c]) for c in targets) * 100
    return shifted(bound_pp / moved) if moved > bound_pp + 1e-9 else out


def entry_dicts(a: Assessment) -> list[dict]:
    return [
        {
            "subject_kind": e.subject_kind,
            "subject": e.subject,
            "exposure_pct": e.exposure_pct,
            "proposed_pp": e.proposed_pp,
            "allowed_pp": e.allowed_pp,
            "clipped": e.clipped,
            "reason": e.reason,
            "insight_ids": e.insight_ids,
        }
        for e in a.entries
    ]


def store(db: Session, rec: RecommendationRow, a: Assessment) -> None:
    db.add(
        RecommendationTiltRow(
            recommendation_id=rec.id,
            status=a.status,
            error=a.error,
            bound_pp=a.bound_pp,
            model=a.model,
            prompt_version=a.prompt_version,
            entries_json=json.dumps(entry_dicts(a)),
            dropped_json=json.dumps(a.dropped),
        )
    )
    db.flush()


def _insight_event_ids(db: Session, insights: list[InsightRow]) -> list[int]:
    """The audit events that made each Insight usable: its approval (else its extraction), so lineage reaches the Report."""
    wanted = {i.id: i for i in insights}
    found: dict[int, int] = {}
    for ev in db.scalars(
        select(AuditEventRow).where(AuditEventRow.type == "insight_approved").order_by(AuditEventRow.id)
    ):
        found[json.loads(ev.payload_json).get("insight_id")] = ev.id
    return sorted({found.get(i, wanted[i].extract_event_id) for i in wanted})


def audit_assessment(db: Session, rec: RecommendationRow, a: Assessment) -> int:
    """Record the LLM's proposal and, for a usable one, the engine's bounded outcome. Returns the last event id."""
    scope = dict(portfolio_id=rec.client_id, client_id=rec.client_id, recommendation_id=str(rec.id))
    llm_actor = audit.Actor.system("tilt-proposer", model=a.model, prompt_version=a.prompt_version)
    parents = _insight_event_ids(db, a.insights)
    if a.status != "ok":
        return audit.record(
            db,
            "research_tilt_proposed",
            llm_actor,
            {"status": "failed", "error": a.error, "insight_ids": [i.id for i in a.insights], **a.exchange},
            parents=parents,
            **scope,
        )
    names = {i.id: i.subject for i in a.insights}
    proposed = audit.record(
        db,
        "research_tilt_proposed",
        llm_actor,
        {"status": "ok", "tilts": [{**p, "subject": names.get(p["insight_id"])} for p in a.proposed], **a.exchange},
        parents=parents,
        **scope,
    )
    return audit.record(
        db,
        "research_tilt_applied",
        ENGINE,
        {"bound_pp": a.bound_pp, "dropped": a.dropped, "tilts": entry_dicts(a)},
        parents=[proposed],
        **scope,
    )
