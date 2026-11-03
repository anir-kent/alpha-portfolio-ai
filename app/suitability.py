"""Suitability engine: the seven deterministic Suitability Rules (ADR-0001).

Pure: takes Holdings (the shape of `portfolio_view.holdings`), the Client's context and Restrictions, and the limits.
Rules never see the LLM. Each returns pass, warning or breach with rule ID and the numbers behind it. Because the input
is just Holdings, a later ticket can evaluate a proposed post-trade Portfolio with the same call.

Full tax-lot optimisation is out of scope: SR-07 only sums unrealised gains in taxable accounts.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Literal

from app.config_service import SuitabilityLimits
from app.market_data import MarketData
from app.portfolio_view import sector_exposure

Status = Literal["pass", "warning", "breach"]
_ORDER = {"pass": 0, "warning": 1, "breach": 2}
PSEUDO_SECTORS = ("Cash", "Fixed Income")  # look-through buckets for cash and bond funds, not equity sectors
BREACH_RISK, WARNING_RISK = 50.0, 15.0  # priority risk points per breach / warning, capped at 100


@dataclass(frozen=True)
class Finding:
    subject: str  # an Instrument symbol, a sector, or a measure such as "equity" / "cash"
    actual: float  # percent of Portfolio value
    limit: float
    status: Status
    note: str = ""


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    name: str
    status: Status
    message: str
    findings: list[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class ClientContext:
    risk_profile: str
    horizon_years: int
    liquidity_needs_pct: float
    restrictions: list[tuple[str, str]]  # (kind, value): kind is "instrument" or "sector"


def worst(statuses) -> Status:
    return max(statuses, key=_ORDER.__getitem__, default="pass")


def _r(x: float) -> float:
    return round(x, 2)


def _limit_status(actual: float, limit: float, warn_ratio: float) -> Status:
    return "breach" if actual > limit else "warning" if actual >= limit * warn_ratio else "pass"


def _result(rule_id: str, name: str, findings: list[Finding], message_for) -> RuleResult:
    """Keep non-pass findings; when all pass keep the single worst-case one so the numbers stay visible."""
    status = worst(f.status for f in findings)
    shown = [f for f in findings if f.status != "pass"] or sorted(findings, key=lambda f: -f.actual)[:1]
    return RuleResult(rule_id, name, status, message_for(status, shown), shown)


def _equity_share(rows: list[dict], total: float) -> float:
    return sum(r["market_value"] for r in rows if r["asset_class"] == "equity") / total * 100 if total else 0.0


def evaluate(rows: list[dict], client: ClientContext, limits: SuitabilityLimits, market: MarketData) -> list[RuleResult]:
    total = sum(r["market_value"] for r in rows)
    pct = lambda v: v / total * 100 if total else 0.0  # noqa: E731
    wr = limits.warn_ratio
    profile = client.risk_profile
    equity = _equity_share(rows, total)
    exposure = sector_exposure(rows, market)
    results: list[RuleResult] = []

    # SR-01 maximum equity share for the Risk Profile
    cap = limits.max_equity_pct[profile]
    results.append(_result(
        "SR-01", "Maximum equity share", [Finding("equity", _r(equity), cap, _limit_status(equity, cap, wr))],
        lambda st, fs: f"Equity is {_r(equity)}% of the Portfolio against a {cap:g}% cap for a {profile} Risk Profile ({st})",
    ))

    # SR-02 single-position limit (single names; diversified funds are exempt)
    by_symbol: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["kind"] == "equity":
            by_symbol[r["symbol"]] += pct(r["market_value"])
    lim = limits.single_position_pct
    results.append(_result(
        "SR-02", "Single-position limit",
        [Finding(s, _r(w), lim, _limit_status(w, lim, wr)) for s, w in sorted(by_symbol.items())],
        lambda st, fs: (
            "No single-name positions held" if not fs
            else f"{', '.join(f'{f.subject} {f.actual}%' for f in fs)} against a {lim:g}% single-position limit ({st})"
        ),
    ))

    # SR-03 sector concentration with fund look-through
    lim = limits.sector_pct
    results.append(_result(
        "SR-03", "Sector concentration",
        [Finding(e["sector"], _r(e["weight_pct"]), lim, _limit_status(e["weight_pct"], lim, wr))
         for e in exposure if e["sector"] not in PSEUDO_SECTORS],
        lambda st, fs: (
            "No equity sector exposure" if not fs
            else f"{', '.join(f'{f.subject} {f.actual}%' for f in fs)} including look-through against a {lim:g}% sector limit ({st})"
        ),
    ))

    # SR-04 minimum cash: breach below the policy floor, warning when it does not cover stated liquidity needs
    cash = sum(pct(r["market_value"]) for r in rows if r["asset_class"] == "cash")
    floor = limits.min_cash_pct[profile]
    if cash < floor:
        cash_f = Finding("cash", _r(cash), floor, "breach", "below the policy cash floor")
    elif cash < client.liquidity_needs_pct:
        cash_f = Finding("cash", _r(cash), client.liquidity_needs_pct, "warning", "does not cover stated liquidity needs")
    else:
        cash_f = Finding("cash", _r(cash), client.liquidity_needs_pct, "pass")
    results.append(_result(
        "SR-04", "Minimum cash reserve", [cash_f],
        lambda st, fs: f"Cash is {_r(cash)}% against a {floor:g}% floor and {client.liquidity_needs_pct:g}% liquidity needs ({st})",
    ))

    # SR-05 Client Restrictions: direct holdings of a restricted Instrument or sector breach; fund look-through warns
    rest_findings: list[Finding] = []
    held: dict[str, float] = defaultdict(float)
    for r in rows:
        held[r["symbol"]] += pct(r["market_value"])
    sector_of = {r["symbol"]: market.instrument(r["symbol"]).sector for r in rows}  # single names and sector ETFs
    sector_exp = {e["sector"]: e for e in exposure}
    for kind, value in sorted(set(client.restrictions)):
        if kind == "instrument":
            if held.get(value, 0) > 0:
                rest_findings.append(Finding(value, _r(held[value]), 0, "breach", "restricted Instrument held"))
        else:
            direct = {s: _r(w) for s, w in held.items() if sector_of.get(s) == value}
            for s, w in sorted(direct.items()):
                rest_findings.append(Finding(s, w, 0, "breach", f"held directly in restricted sector {value}"))
            via = sector_exp.get(value, {}).get("via_funds_pct", 0.0)
            if via > 0:
                rest_findings.append(Finding(value, _r(via), 0, "warning", "restricted sector reached through funds"))
    results.append(RuleResult(
        "SR-05", "Client Restrictions", worst(f.status for f in rest_findings),
        "No Restriction is violated" if not rest_findings else "; ".join(
            f"{f.subject} {f.actual}%: {f.note}" for f in rest_findings),
        rest_findings,
    ))

    # SR-06 horizon: a short horizon caps equity
    short = client.horizon_years < limits.horizon_short_years
    hcap = limits.horizon_short_equity_max_pct
    h_status: Status = "pass" if not short else _limit_status(equity, hcap, wr)
    results.append(RuleResult(
        "SR-06", "Horizon check", h_status,
        (f"Horizon of {client.horizon_years} years is short (under {limits.horizon_short_years}); equity is "
         f"{_r(equity)}% against a {hcap:g}% cap ({h_status})") if short
        else f"Horizon of {client.horizon_years} years is not short (under {limits.horizon_short_years})",
        [Finding("equity", _r(equity), hcap, h_status)] if short else [Finding("equity", _r(equity), hcap, "pass", "horizon is not short")],
    ))

    # SR-07 taxable-gain warning (warning only; no tax-lot optimisation)
    # Gains only: selling the winners realises them whatever losses sit elsewhere, so losses do not offset.
    gain = sum(max(0.0, r["price"] - r["cost_basis_per_unit"]) * r["quantity"] for r in rows if r["tax_status"] == "taxable")
    gain_pct = pct(gain)
    g_status: Status = "warning" if gain_pct >= limits.taxable_gain_pct else "pass"
    results.append(RuleResult(
        "SR-07", "Taxable-gain warning", g_status,
        f"Unrealised gains (not netted against losses) in taxable accounts are {_r(gain_pct)}% of the Portfolio against a "
        f"{limits.taxable_gain_pct:g}% warning line ({g_status})",
        [Finding("taxable gains", _r(gain_pct), limits.taxable_gain_pct, g_status)],
    ))
    return results


def overall(results: list[RuleResult]) -> Status:
    return worst(r.status for r in results)


def risk_points(results: list[RuleResult]) -> float:
    """0-100 input to the priority risk component: 50 per breaching rule, 15 per warning rule, capped."""
    pts = sum(BREACH_RISK if r.status == "breach" else WARNING_RISK if r.status == "warning" else 0 for r in results)
    return min(100.0, pts)


def to_dicts(results: list[RuleResult]) -> list[dict]:
    return [asdict(r) for r in results]
