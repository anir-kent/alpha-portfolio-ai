"""Band-based rebalancing: Trade Lines that return a Portfolio to its Target Allocation (ADR-0001).

Pure and deterministic; no tilt yet. A Portfolio is rebalanced only when some Asset Class is outside its Tolerance Band
(drift status "breach"). Then every Asset Class moves to target:
- overweight classes are sold pro rata to the market value of their holdings;
- underweight classes are bought pro rata across the class's existing non-restricted funds (never more of a single
  name), or the class's default fund when there is none.
A class within 0.5 points of target is left alone. Quantities are whole units rounded down, so a little drift can remain. No tax-lot optimisation.
"""
from dataclasses import dataclass
from typing import Literal

from app.drift import PortfolioDrift
from app.market_data import MarketData

Side = Literal["buy", "sell"]
DEFAULT_FUND = {"equity": "SPY", "bond": "AGG", "cash": "SGOV"}
DE_MINIMIS_PCT = 0.5  # a class within this many points of target is left alone (rounding residue is not a trade)
_EPS = 1e-9


@dataclass(frozen=True)
class TradeLine:
    account_id: str
    symbol: str
    side: Side
    quantity: int


def outside_tolerance(drift: PortfolioDrift) -> bool:
    return any(c.status == "breach" for c in drift.classes)


def plan(
    rows: list[dict], targets: dict[str, float], restricted: set[str], market: MarketData, drift: PortfolioDrift
) -> list[TradeLine]:
    """Trade Lines for a Portfolio outside tolerance; empty when it is within its Tolerance Bands."""
    if not outside_tolerance(drift):
        return []
    total = sum(r["market_value"] for r in rows)
    sells: list[TradeLine] = []
    buys: list[TradeLine] = []
    for cls in sorted({r["asset_class"] for r in rows} | set(targets)):
        members = [r for r in rows if r["asset_class"] == cls]
        value = sum(r["market_value"] for r in members)
        delta = targets.get(cls, 0.0) * total - value
        if abs(delta) < total * DE_MINIMIS_PCT / 100:
            continue
        if delta < 0:
            for r in members:
                amount = -delta * r["market_value"] / value
                qty = min(r["quantity"], int(amount / r["price"] + _EPS))
                if qty > 0:
                    sells.append(TradeLine(r["account_id"], r["symbol"], "sell", qty))
        elif delta > 0:
            buys += _buys(cls, delta, members, restricted, rows, market)
    key = lambda l: (l.symbol, l.account_id)  # noqa: E731
    return sorted(sells, key=key) + sorted(buys, key=key)


def _buys(cls: str, amount: float, members: list[dict], restricted: set[str], rows: list[dict], market: MarketData) -> list[TradeLine]:
    funds = [r for r in members if r["kind"] != "equity" and r["symbol"] not in restricted]
    if funds:
        value = sum(r["market_value"] for r in funds)
        recipients = [(r["account_id"], r["symbol"], r["price"], r["market_value"] / value) for r in funds]
    else:
        symbol = DEFAULT_FUND[cls]
        if symbol in restricted or not rows:
            return []
        accounts = {r["account_id"]: r["tax_status"] for r in rows}
        account = next((a for a in sorted(accounts) if accounts[a] == "tax_advantaged"), sorted(accounts)[0])
        recipients = [(account, symbol, market.instrument(symbol).price, 1.0)]
    out = []
    for account, symbol, price, share in recipients:
        qty = int(amount * share / price + _EPS)
        if qty > 0:
            out.append(TradeLine(account, symbol, "buy", qty))
    return out


def validate(lines: list[TradeLine], rows: list[dict], accounts: set[str], market: MarketData) -> None:
    """Raise ValueError (message safe to show the Advisor) when a set of Trade Lines is not executable on this Portfolio."""
    if not lines:
        raise ValueError("A modification needs at least one Trade Line")
    held = {(r["account_id"], r["symbol"]): r["quantity"] for r in rows}
    seen: set[tuple[str, str]] = set()
    for l in lines:
        key = (l.account_id, l.symbol)
        try:
            market.instrument(l.symbol)
        except KeyError:
            raise ValueError(f"Unknown Instrument {l.symbol}")
        if l.account_id not in accounts:
            raise ValueError(f"Unknown account {l.account_id} for this Portfolio")
        if l.quantity <= 0:
            raise ValueError(f"Quantity for {l.symbol} must be a positive whole number")
        if key in seen:
            raise ValueError(f"Duplicate Trade Line for {l.symbol} in {l.account_id}")
        seen.add(key)
        if l.side == "sell" and l.quantity > held.get(key, 0):
            raise ValueError(f"Cannot sell {l.quantity} {l.symbol} in {l.account_id}: more than held ({held.get(key, 0)})")


def apply(lines: list[TradeLine], rows: list[dict], tax_status: dict[str, str], market: MarketData) -> list[dict]:
    """The Holdings after the Trade Lines, in the shape suitability.evaluate takes. New units carry a cost basis at price."""
    out = [dict(r) for r in rows]
    index = {(r["account_id"], r["symbol"]): r for r in out}
    for l in lines:
        inst = market.instrument(l.symbol)
        r = index.get((l.account_id, l.symbol))
        if r is None:
            r = {
                "symbol": inst.symbol, "name": inst.name, "asset_class": inst.asset_class, "kind": inst.kind,
                "account_id": l.account_id, "tax_status": tax_status[l.account_id], "quantity": 0, "price": inst.price,
                "market_value": 0.0, "cost_basis_per_unit": inst.price,
            }
            out.append(r)
            index[(l.account_id, l.symbol)] = r
        if l.side == "buy":
            r["cost_basis_per_unit"] = (r["quantity"] * r["cost_basis_per_unit"] + l.quantity * inst.price) / (r["quantity"] + l.quantity)
            r["quantity"] += l.quantity
        else:
            r["quantity"] -= l.quantity
        r["market_value"] = r["quantity"] * r["price"]
    return [r for r in out if r["quantity"] > 0]
