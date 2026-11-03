"""Approval policy: which steps a Recommendation needs, and what follows each Decision.

Advisor always; Compliance only when a Suitability Rule is in breach; Investment Committee only when high-impact
(turnover or any single Trade Line at or above the configured thresholds). Pure functions of the Recommendation and
the config: nothing here touches the database.
"""
import json
from dataclasses import dataclass

from app.config_service import ApprovalThresholds, Config
from app.db import RecommendationRow
from app.market_data import MarketData

STEPS = ("advisor", "compliance", "committee")
PENDING_FOR = {"advisor": "pending_advisor", "compliance": "pending_compliance", "committee": "pending_committee"}
STEP_OF = {v: k for k, v in PENDING_FOR.items()}


@dataclass(frozen=True)
class Plan:
    needs_compliance: bool
    high_impact: bool
    thresholds: ApprovalThresholds
    reasons: list[str]  # why the Recommendation is high-impact; empty when it is not

    @property
    def required_steps(self) -> list[str]:
        return ["advisor", *(["compliance"] if self.needs_compliance else []), *(["committee"] if self.high_impact else [])]


def plan(rec: RecommendationRow, cfg: Config) -> Plan:
    t = cfg.approval_thresholds
    reasons = []
    if rec.turnover_pct >= t.turnover_pct:
        reasons.append(f"Turnover {rec.turnover_pct:.1f}% of the Portfolio is at or above the {t.turnover_pct:g}% threshold")
    for l in json.loads(rec.trade_lines_json):
        if l["pct_of_portfolio"] >= t.trade_line_pct:
            reasons.append(
                f"{l['side']} {l['symbol']} is {l['pct_of_portfolio']:.1f}% of the Portfolio, at or above the "
                f"{t.trade_line_pct:g}% single Trade Line threshold"
            )
    return Plan(rec.suitability_status == "breach", bool(reasons), t, reasons)


def next_status(p: Plan, after: str) -> str:
    """The status once `after` (a step) has been passed by a human Decision. Approved only when no step remains."""
    # Later steps in workflow order that are still required. Tolerates `after` no longer being required, which
    # happens when thresholds change while a Recommendation waits at that step.
    remaining = [s for s in p.required_steps if STEPS.index(s) > STEPS.index(after)]
    return PENDING_FOR[remaining[0]] if remaining else "approved"


def affected_lines(subject: str, trade_lines: list[dict], market: MarketData) -> list[dict]:
    """The Trade Lines that bear on a rule finding: the Instrument itself, or those in the sector or asset class
    (look-through included) the finding is about."""
    out = []
    for l in trade_lines:
        inst = market.instrument(l["symbol"])
        if subject in (inst.symbol, inst.asset_class, inst.sector) or subject in market.sector_weights(inst.symbol):
            out.append(l)
        elif subject == "taxable gains" and l["side"] == "sell":
            out.append(l)
    return out
