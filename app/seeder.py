"""Deterministic synthetic-Client seeder (ADR-0003).

Same seed + same snapshot => identical Clients, Accounts, Holdings, Targets and Restrictions.
Usage: uv run python -m app.seeder [--seed N]
"""
import random
import sys
from datetime import date, timedelta

from sqlalchemy import delete

from app.db import AccountRow, ClientRow, HoldingRow, RestrictionRow, TargetRow
from app.market_data import MarketData

DEFAULT_SEED = 20261102
N_CLIENTS = 25

RISK_PROFILES = ("conservative", "moderate", "growth", "aggressive")
TARGETS = {  # Asset-Class weights per Risk Profile
    "conservative": {"equity": 0.20, "bond": 0.65, "cash": 0.15},
    "moderate": {"equity": 0.45, "bond": 0.45, "cash": 0.10},
    "growth": {"equity": 0.70, "bond": 0.25, "cash": 0.05},
    "aggressive": {"equity": 0.85, "bond": 0.10, "cash": 0.05},
}
HORIZON = {"conservative": (3, 8), "moderate": (5, 12), "growth": (8, 20), "aggressive": (10, 25)}
OBJECTIVES = {
    "conservative": ["Capital preservation", "Income"],
    "moderate": ["Balanced growth and income", "Income"],
    "growth": ["Long-term growth", "Balanced growth and income"],
    "aggressive": ["Maximum long-term growth", "Long-term growth"],
}
FIRST = ["Asha", "Ben", "Chen", "Dana", "Eli", "Farah", "Gus", "Hana", "Ivan", "Jia", "Kofi", "Lena", "Mateo", "Nia", "Omar",
         "Priya", "Quinn", "Rosa", "Sam", "Tara", "Uma", "Vik", "Wen", "Xavi", "Yara", "Zane"]
LAST = ["Almeida", "Brandt", "Castillo", "Dubois", "Ekström", "Fischer", "Gupta", "Haddad", "Ivanova", "Jensen", "Kim",
        "Larsen", "Moreau", "Nakamura", "Okafor", "Petrov", "Quarles", "Rossi", "Silva", "Tanaka"]

# Planted scenarios: fixed Client IDs so tests and demos can assert on them.
PLANTED = {
    "heavy_tech": "C001",
    "overweight_energy": "C002",
    "cash_drag": "C003",
    "restricted_breach": "C004",
    "clean": "C005",
}

# (profile, {symbol: weight of Portfolio value}, restricted instruments, review-due offset in days)
_PLANTED_SPECS = {
    "C001": ("growth", {"AAPL": .15, "MSFT": .15, "NVDA": .12, "XLK": .12, "SPY": .10, "JPM": .03, "JNJ": .03,
                        "AGG": .15, "LQD": .10, "SGOV": .05}, [], -10),
    "C002": ("moderate", {"XOM": .15, "XLE": .15, "SPY": .15, "JNJ": .10, "PG": .05, "AGG": .15, "LQD": .10, "SHY": .10,
                          "SGOV": .05}, [], 5),
    "C003": ("conservative", {"SPY": .10, "XLV": .05, "XLP": .05, "AGG": .25, "SHY": .15, "SGOV": .40}, [], -30),
    "C004": ("growth", {"XOM": .06, "SPY": .30, "AAPL": .08, "MSFT": .08, "JNJ": .06, "JPM": .06, "AGG": .15, "LQD": .10,
                        "SGOV": .05, "XLV": .06}, ["XOM"], 12),
    "C005": ("moderate", {"SPY": .10, "XLV": .06, "XLF": .06, "XLI": .05, "XLP": .05, "XLY": .04, "XLU": .04, "XLRE": .02,
                          "XLC": .03, "AGG": .25, "LQD": .10, "SHY": .10, "SGOV": .10}, [], 30),
}


def _quantities(weights: dict[str, float], total: float, market: MarketData) -> dict[str, int]:
    q = {s: int(total * w // market.instrument(s).price) for s, w in weights.items()}
    return {s: n for s, n in q.items() if n > 0}


def _random_weights(rng: random.Random, profile: str, market: MarketData, banned: set[str]) -> dict[str, float]:
    t = TARGETS[profile]
    eq = min(0.95, max(0.05, t["equity"] + rng.uniform(-0.08, 0.08)))
    cash = max(0.01, t["cash"] + rng.uniform(-0.03, 0.04))
    class_w = {"equity": eq, "cash": cash, "bond": max(0.0, 1 - eq - cash)}
    weights: dict[str, float] = {}
    for cls, w in class_w.items():
        pool = [i.symbol for i in market.instruments() if i.asset_class == cls and i.symbol not in banned]
        picks = rng.sample(pool, min(len(pool), rng.randint(4, 7) if cls == "equity" else rng.randint(1, 3)))
        raw = [rng.uniform(0.5, 1.5) for _ in picks]
        for s, r in zip(picks, raw, strict=True):
            weights[s] = w * r / sum(raw)
    return weights


def seed_clients(session_factory, market: MarketData, seed: int = DEFAULT_SEED) -> None:
    """Replace all synthetic Client data with a deterministic set for this seed."""
    rng = random.Random(seed)
    today = date.fromisoformat(market.as_of[:10])
    planted_ids = list(PLANTED.values())
    clients, accounts, holdings, targets, restrictions = [], [], [], [], []

    for n in range(1, N_CLIENTS + 1):
        cid = f"C{n:03d}"
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        spec = _PLANTED_SPECS.get(cid)
        if spec:
            profile, weights, restricted, due_offset = spec
            tax_kinds = ["taxable", "tax_advantaged"]
        else:
            profile = RISK_PROFILES[n % 4]
            restricted = []
            banned: set[str] = set()
            if rng.random() < 0.3:
                if rng.random() < 0.5:
                    sector = rng.choice(["Energy", "Financials", "Consumer Staples"])
                    restrictions.append(RestrictionRow(client_id=cid, kind="sector", value=sector))
                    banned |= {i.symbol for i in market.instruments() if market.sector_weights(i.symbol).get(sector, 0) > 0}
                else:
                    sym = rng.choice(["XOM", "NVDA", "JPM", "PG"])
                    restricted = [sym]
                    banned.add(sym)
            weights = _random_weights(rng, profile, market, banned)
            due_offset = rng.randint(-45, 90)
            tax_kinds = rng.choice([["taxable"], ["tax_advantaged"], ["taxable", "tax_advantaged"]])
        for sym in restricted:
            restrictions.append(RestrictionRow(client_id=cid, kind="instrument", value=sym))

        lo, hi = HORIZON[profile]
        clients.append(ClientRow(
            id=cid, name=name, email=f"{cid.lower()}@clients.example.invalid", risk_profile=profile,
            objective=rng.choice(OBJECTIVES[profile]), horizon_years=rng.randint(lo, hi),
            liquidity_needs_pct=round(rng.uniform(5, 15) if profile == "conservative" else rng.uniform(0, 10), 1),
            review_due=(today + timedelta(days=due_offset)).isoformat(),
        ))
        for cls, w in TARGETS[profile].items():
            targets.append(TargetRow(client_id=cid, asset_class=cls, weight=w))
        acct_ids = {k: f"{cid}-{'TX' if k == 'taxable' else 'TA'}" for k in tax_kinds}
        accounts += [AccountRow(id=a, client_id=cid, tax_status=k) for k, a in acct_ids.items()]

        total = rng.randrange(1_000_000, 5_000_000, 50_000) if spec else rng.randrange(250_000, 3_000_000, 25_000)
        for sym, qty in _quantities(weights, total, market).items():
            account = acct_ids[rng.choice(tax_kinds)]
            basis = round(market.instrument(sym).price * rng.uniform(0.55, 1.10), 2)
            holdings.append(HoldingRow(account_id=account, symbol=sym, quantity=qty, cost_basis_per_unit=basis))

    assert len(clients) == N_CLIENTS and all(p in {c.id for c in clients} for p in planted_ids)
    with session_factory() as db:
        for m in (HoldingRow, AccountRow, RestrictionRow, TargetRow, ClientRow):
            db.execute(delete(m))
        db.add_all(clients + accounts + targets + restrictions)
        db.flush()
        db.add_all(holdings)
        db.commit()


if __name__ == "__main__":
    from app.db import make_session_factory
    from app.settings import Settings

    s = Settings()
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else DEFAULT_SEED
    seed_clients(make_session_factory(s.database_url), MarketData.load(s.market_data_snapshot_path, s.fund_lookthrough_path), seed)
    print(f"seeded {N_CLIENTS} synthetic clients (seed {seed}) into {s.database_url}")
