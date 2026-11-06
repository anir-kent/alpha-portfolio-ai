"""Opportunity component of the priority score: deterministic, from look-through sector exposure and approved Insights (ADR-0001).

A sector with an approved positive or negative Insight is a reason to talk to the client (add or reduce); a neutral view is
not. Each such sector counts once, at the Portfolio's look-through weight in it. The sum saturates at OPPORTUNITY_FULL_PCT
points of Portfolio value. The LLM plays no part.
"""
from collections.abc import Iterable

OPPORTUNITY_FULL_PCT = 30.0


def relevant_insights(sector_pct: dict[str, float], insights: Iterable) -> list:
    """The Insights that give this Portfolio an Opportunity: a non-neutral view on a sector it holds."""
    return [i for i in insights if i.subject_kind == "sector" and i.direction != "neutral" and sector_pct.get(i.subject, 0.0) > 0]


def opportunity_raw(sector_pct: dict[str, float], insights: Iterable) -> float:
    """0-100. `sector_pct` is look-through exposure by sector in percent of Portfolio value; `insights` must be approved ones."""
    exposure = sum(sector_pct[s] for s in {i.subject for i in relevant_insights(sector_pct, insights)})
    return max(0.0, min(100.0, 100 * exposure / OPPORTUNITY_FULL_PCT))
