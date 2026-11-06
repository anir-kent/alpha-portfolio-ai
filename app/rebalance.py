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
    key = lambda line: (line.symbol, line.account_id)  # noqa: E731
    return sorted(sells, key=key) + sorted(buys, key=key)


def _buys(
    cls: str, amount: float, members: list[dict], restricted: set[str], rows: list[dict], market: MarketData
) -> list[TradeLine]:
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


BROAD_EQUITY_FUND = "SPY"


def merge(*sets: list[TradeLine]) -> list[TradeLine]:
    """One Trade Line per (account, symbol): opposite sides net against each other."""
    net: dict[tuple[str, str], int] = {}
    for lines in sets:
        for line in lines:
            net[(line.account_id, line.symbol)] = net.get((line.account_id, line.symbol), 0) + (
                line.quantity if line.side == "buy" else -line.quantity
            )
    sells = [TradeLine(a, s, "sell", -q) for (a, s), q in net.items() if q < 0]
    buys = [TradeLine(a, s, "buy", q) for (a, s), q in net.items() if q > 0]
    key = lambda line: (line.symbol, line.account_id)  # noqa: E731
    return sorted(sells, key=key) + sorted(buys, key=key)


def sector_sleeve(
    rows: list[dict],
    sector_tilts_pp: dict[str, float],
    restricted: set[str],
    restricted_sectors: set[str],
    market: MarketData,
    total: float,
) -> list[TradeLine]:
    """Switches inside equity for sector tilts, sized on `total` (the Portfolio value) and priced from `rows` (the Holdings
    after the Asset-Class trades). A positive tilt sells the broad equity fund and buys the sector ETF in the same Account;
    a negative one sells held sector ETF and buys the broad fund. Limited to what is held; an Asset-Class weight is unchanged.
    """
    broad = market.instrument(BROAD_EQUITY_FUND)
    spy_held = {r["account_id"]: r["quantity"] for r in rows if r["symbol"] == broad.symbol}
    out: list[TradeLine] = []
    for sector, pp in sorted(sector_tilts_pp.items()):
        etf = next((i for i in market.instruments() if i.kind == "fund" and i.sector == sector), None)
        if (
            etf is None
            or pp == 0
            or sector in restricted_sectors
            or etf.symbol in restricted
            or broad.symbol in restricted
        ):
            continue
        amount = abs(pp) / 100 * total
        if pp > 0:
            pool = {a: q for a, q in sorted(spy_held.items()) if q > 0}
            value = sum(q * broad.price for q in pool.values())
            take = min(amount, value)
            for account, held in pool.items():
                sell = min(held, int(take * (held * broad.price / value) / broad.price + 1e-9)) if value else 0
                buy = int(sell * broad.price / etf.price + 1e-9)
                if sell > 0 and buy > 0:
                    out += [TradeLine(account, broad.symbol, "sell", sell), TradeLine(account, etf.symbol, "buy", buy)]
                    spy_held[account] -= sell
        else:
            held = {r["account_id"]: r["quantity"] for r in rows if r["symbol"] == etf.symbol}
            value = sum(q * etf.price for q in held.values())
            take = min(amount, value)
            for account, qty in sorted(held.items()):
                sell = min(qty, int(take * (qty * etf.price / value) / etf.price + 1e-9)) if value else 0
                buy = int(sell * etf.price / broad.price + 1e-9)
                if sell > 0 and buy > 0:
                    out += [TradeLine(account, etf.symbol, "sell", sell), TradeLine(account, broad.symbol, "buy", buy)]
                    spy_held[account] = spy_held.get(account, 0) + buy
    return out


def validate(lines: list[TradeLine], rows: list[dict], accounts: set[str], market: MarketData) -> None:
    """Raise ValueError (message safe to show the Advisor) when a set of Trade Lines is not executable on this Portfolio."""
    if not lines:
        raise ValueError("A modification needs at least one Trade Line")
    held = {(r["account_id"], r["symbol"]): r["quantity"] for r in rows}
    seen: set[tuple[str, str]] = set()
    for line in lines:
        key = (line.account_id, line.symbol)
        try:
            market.instrument(line.symbol)
        except KeyError:
            raise ValueError(f"Unknown Instrument {line.symbol}") from None
        if line.account_id not in accounts:
            raise ValueError(f"Unknown account {line.account_id} for this Portfolio")
        if line.quantity <= 0:
            raise ValueError(f"Quantity for {line.symbol} must be a positive whole number")
        if key in seen:
            raise ValueError(f"Duplicate Trade Line for {line.symbol} in {line.account_id}")
        seen.add(key)
        if line.side == "sell" and line.quantity > held.get(key, 0):
            raise ValueError(
                f"Cannot sell {line.quantity} {line.symbol} in {line.account_id}: more than held ({held.get(key, 0)})"
            )


def apply(lines: list[TradeLine], rows: list[dict], tax_status: dict[str, str], market: MarketData) -> list[dict]:
    """The Holdings after the Trade Lines, in the shape suitability.evaluate takes. New units carry a cost basis at price."""
    out = [dict(r) for r in rows]
    index = {(r["account_id"], r["symbol"]): r for r in out}
    for line in lines:
        inst = market.instrument(line.symbol)
        r = index.get((line.account_id, line.symbol))
        if r is None:
            r = {
                "symbol": inst.symbol,
                "name": inst.name,
                "asset_class": inst.asset_class,
                "kind": inst.kind,
                "account_id": line.account_id,
                "tax_status": tax_status[line.account_id],
                "quantity": 0,
                "price": inst.price,
                "market_value": 0.0,
                "cost_basis_per_unit": inst.price,
            }
            out.append(r)
            index[(line.account_id, line.symbol)] = r
        if line.side == "buy":
            r["cost_basis_per_unit"] = (r["quantity"] * r["cost_basis_per_unit"] + line.quantity * inst.price) / (
                r["quantity"] + line.quantity
            )
            r["quantity"] += line.quantity
        else:
            r["quantity"] -= line.quantity
        r["market_value"] = r["quantity"] * r["price"]
    return [r for r in out if r["quantity"] > 0]
