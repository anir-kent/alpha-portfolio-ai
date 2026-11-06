"""Portfolio drill-down read model: Holdings, look-through sector exposure, Client context.

Numbers come from the deterministic engines (ADR-0001); this module only assembles them.
"""
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import AccountRow, HoldingRow
from app.market_data import MarketData


def holdings(db: Session, market: MarketData, client_id: str) -> list[dict]:
    """The Client's Holdings across all Accounts, valued at snapshot prices, largest first."""
    rows = db.execute(
        select(HoldingRow, AccountRow).join(AccountRow, HoldingRow.account_id == AccountRow.id)
        .where(AccountRow.client_id == client_id)
    )
    out: list[dict[str, Any]] = []
    for h, a in rows:
        inst = market.instrument(h.symbol)
        out.append({
            "symbol": h.symbol, "name": inst.name, "asset_class": inst.asset_class, "kind": inst.kind,
            "account_id": a.id, "tax_status": a.tax_status, "quantity": h.quantity, "price": inst.price,
            "market_value": h.quantity * inst.price, "cost_basis_per_unit": h.cost_basis_per_unit,
        })
    out.sort(key=lambda r: (-r["market_value"], r["symbol"], r["account_id"]))
    return out


def sector_pct(rows: list[dict], market: MarketData) -> dict[str, float]:
    """Look-through weight per sector, percent of Portfolio value."""
    return {e["sector"]: e["weight_pct"] for e in sector_exposure(rows, market)}


def sector_exposure(rows: list[dict], market: MarketData) -> list[dict]:
    """Look-through exposure per sector as a share of Portfolio value, split into direct and via funds."""
    total = sum(r["market_value"] for r in rows)
    direct: dict[str, float] = defaultdict(float)
    via_funds: dict[str, float] = defaultdict(float)
    for r in rows:
        bucket = direct if r["kind"] == "equity" else via_funds
        for sector, w in market.sector_weights(r["symbol"]).items():
            bucket[sector] += r["market_value"] * w
    if not total:
        return []
    return sorted(
        ({"sector": s, "weight_pct": (direct[s] + via_funds[s]) / total * 100,
          "direct_pct": direct[s] / total * 100, "via_funds_pct": via_funds[s] / total * 100}
         for s in set(direct) | set(via_funds)),
        key=lambda e: (-e["weight_pct"], e["sector"]),
    )
