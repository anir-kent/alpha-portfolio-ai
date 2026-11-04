"""Grounding validator: every LLM claim must be traceable (spec: responsible GenAI usage, ADR-0001).

A claim is grounded only if it carries at least one citation, every Report citation names a real Report and page and
quotes it verbatim, every engine citation names a figure the engine produced for the Recommendation, and every number
in the claim text equals a cited engine figure at the precision the claim states. A claim that calls a view on an asset
(sector, Asset Class or Instrument) also needs a Report citation: engine figures alone cannot support a view.

Ungrounded claims are never dropped: they are flagged with the reasons, kept out of memos (`memo_claims`) and stay
visible to the Advisor.
"""
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Iterable, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.db import GroundingResultRow, PriorityResultRow, RecommendationRow, ReportPageRow, ReportRow
from app.reports import passage_on_page

VALIDATOR = audit.Actor.system("grounding-validator")

IssueCode = Literal[
    "uncited", "report_not_found", "page_not_found", "quote_not_found", "unknown_engine_figure",
    "number_mismatch", "asset_call_needs_report",
]


class ReportCitation(BaseModel):
    kind: Literal["report"]
    report_id: str
    page: int
    quote: str


class EngineCitation(BaseModel):
    kind: Literal["engine"]
    figure: str


Citation = Annotated[ReportCitation | EngineCitation, Field(discriminator="kind")]


class Claim(BaseModel):
    text: str
    asset: str | None = None  # the sector, Asset Class or Instrument the claim takes a view on, if any
    citations: list[Citation] = []


class Issue(BaseModel):
    code: IssueCode
    message: str


class ClaimResult(BaseModel):
    index: int
    text: str
    asset: str | None
    citations: list[Citation]
    grounded: bool
    issues: list[Issue]


def memo_claims(results: Iterable[ClaimResult]) -> list[ClaimResult]:
    """The only claims a memo may use."""
    return [r for r in results if r.grounded]


def summarise(results: Iterable) -> dict[str, int]:
    grounded = [r.grounded for r in results]
    return {"total": len(grounded), "grounded": sum(grounded), "ungrounded": len(grounded) - sum(grounded)}


# --- engine figures ---------------------------------------------------------------------------------------------

def engine_figures(db: Session, rec: RecommendationRow) -> dict[str, float]:
    """Every number the engine produced for this Recommendation, by name."""
    f: dict[str, float] = {
        "total_value": rec.total_value, "turnover_pct": rec.turnover_pct,
        "trade_line_count": float(len(json.loads(rec.trade_lines_json))),
    }
    for line in json.loads(rec.trade_lines_json):
        base = f"trade_line.{line['symbol']}"
        for key in ("amount", "quantity", "pct_of_portfolio"):  # one symbol may trade in several Accounts
            f[f"{base}.{key}"] = f.get(f"{base}.{key}", 0.0) + line[key]
        f.setdefault(f"{base}.price", line["price"])
    for scope, rows in (("post_trade_drift", json.loads(rec.post_trade_drift_json)),):
        for d in rows:
            for key in ("actual_pct", "target_pct", "signed_pp", "drift_pp"):
                f[f"{scope}.{d['asset_class']}.{key}"] = d[key]
    prio = db.get(PriorityResultRow, (rec.run_id, rec.client_id))
    if prio is not None:
        f["priority_score"], f["portfolio_drift_pp"] = prio.score, prio.portfolio_drift_pp
        f["days_past_due"] = float(prio.days_past_due)
        for d in json.loads(prio.drift_json):
            for key in ("actual_pct", "target_pct", "signed_pp", "drift_pp"):
                f[f"drift.{d['asset_class']}.{key}"] = d[key]
    return f


_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?|(?<![\w.])\.\d+")


def numbers_in(text: str) -> list[tuple[str, float, int]]:
    """(as written, value, decimals stated) for each number in the text. Thousands separators are ignored."""
    out = []
    for m in _NUMBER.finditer(text):
        raw = m.group().rstrip(",")
        clean = raw.replace(",", "")
        out.append((raw, float(clean), len(clean.split(".")[1]) if "." in clean else 0))
    return out


def number_matches(value: float, decimals: int, figures: Iterable[float]) -> bool:
    """Equal to some engine figure when rounded to the stated precision (sign is not compared: wording carries it)."""
    return any(round(abs(f), decimals) == round(value, decimals) for f in figures)


# --- validation -------------------------------------------------------------------------------------------------

def _check_report_citation(db: Session, c: ReportCitation) -> Issue | None:
    if db.get(ReportRow, c.report_id) is None:
        return Issue(code="report_not_found", message=f"Report {c.report_id} does not exist")
    page = db.get(ReportPageRow, (c.report_id, c.page))
    if page is None:
        return Issue(code="page_not_found", message=f"Report {c.report_id} has no page {c.page}")
    if not passage_on_page(c.quote, page.text):
        return Issue(code="quote_not_found", message=f"Quote does not appear on {c.report_id} page {c.page}")
    return None


def validate_claim(db: Session, claim: Claim, index: int, figures: dict[str, float]) -> ClaimResult:
    issues: list[Issue] = []
    if not claim.citations:
        issues.append(Issue(code="uncited", message="Claim has no citation"))
    for c in claim.citations:
        if isinstance(c, ReportCitation):
            issue = _check_report_citation(db, c)
        elif c.figure not in figures:
            issue = Issue(code="unknown_engine_figure", message=f"The engine produced no figure named '{c.figure}'")
        else:
            issue = None
        if issue:
            issues.append(issue)
    if claim.asset and claim.citations and not any(isinstance(c, ReportCitation) for c in claim.citations):
        issues.append(Issue(code="asset_call_needs_report", message=f"A view on {claim.asset} needs a Report citation"))
    cited = [figures[c.figure] for c in claim.citations if isinstance(c, EngineCitation) and c.figure in figures]
    for raw, value, decimals in numbers_in(claim.text):  # a number must match a figure the claim itself cites
        if not number_matches(value, decimals, cited):
            issues.append(Issue(code="number_mismatch", message=f"{raw} does not match a cited engine figure"))
    return ClaimResult(
        index=index, text=claim.text, asset=claim.asset, citations=claim.citations, grounded=not issues, issues=issues,
    )


def validate(db: Session, rec: RecommendationRow, claims: list[Claim]) -> tuple[str, list[ClaimResult]]:
    """Validate, store and audit one batch of claims. Returns (check id, one result per claim in order)."""
    figures = engine_figures(db, rec)
    results = [validate_claim(db, c, i, figures) for i, c in enumerate(claims)]
    check_id = "GRD-" + uuid.uuid4().hex[:8]
    now = audit.format_ts(datetime.now(timezone.utc))
    db.add_all(
        GroundingResultRow(
            check_id=check_id, recommendation_id=rec.id, client_id=rec.client_id, claim_index=r.index, text=r.text,
            asset=r.asset, citations_json=json.dumps([c.model_dump() for c in r.citations]), grounded=r.grounded,
            issues_json=json.dumps([i.model_dump() for i in r.issues]), created_at=now,
        )
        for r in results
    )
    db.commit()
    scope = dict(portfolio_id=rec.client_id, client_id=rec.client_id, recommendation_id=str(rec.id))
    checked = audit.record(
        db, "grounding_checked", VALIDATOR,
        {"check_id": check_id, "summary": summarise(results), "figure_count": len(figures)}, **scope,
    )
    for r in results:
        if not r.grounded:
            audit.record(
                db, "claim_ungrounded", VALIDATOR,
                {"check_id": check_id, "claim_index": r.index, "text": r.text, "asset": r.asset,
                 "issues": [i.model_dump() for i in r.issues]},
                parents=[checked], **scope,
            )
    return check_id, results


def latest_results(db: Session, recommendation_id: int) -> list[ClaimResult]:
    """All results (grounded or not) of the most recent check, in claim order."""
    check_id = db.scalar(
        select(GroundingResultRow.check_id).where(GroundingResultRow.recommendation_id == recommendation_id)
        .order_by(GroundingResultRow.id.desc()).limit(1)
    )
    if check_id is None:
        return []
    rows = db.scalars(select(GroundingResultRow).where(GroundingResultRow.check_id == check_id).order_by(GroundingResultRow.claim_index))
    return [
        ClaimResult(
            index=r.claim_index, text=r.text, asset=r.asset, citations=json.loads(r.citations_json), grounded=r.grounded,
            issues=json.loads(r.issues_json),
        )
        for r in rows
    ]
