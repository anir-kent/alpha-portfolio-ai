from collections import defaultdict

import pytest
from sqlalchemy import select

from app.db import AccountRow, ClientRow, HoldingRow, RestrictionRow, TargetRow, make_session_factory
from app.market_data import MarketData
from app.seeder import PLANTED, seed_clients
from tests.test_market_data import LOOKTHROUGH, SNAPSHOT

PROFILES = {"conservative", "moderate", "growth", "aggressive"}


@pytest.fixture(scope="module")
def md():
    return MarketData.load(SNAPSHOT, LOOKTHROUGH)


@pytest.fixture
def sf(tmp_path):
    return make_session_factory(f"sqlite:///{tmp_path / 's.db'}")


def dump(sf):
    with sf() as db:
        return [
            [tuple(getattr(r, c.name) for c in r.__table__.columns) for r in db.scalars(select(m).order_by(*m.__table__.primary_key.columns))]
            for m in (ClientRow, AccountRow, HoldingRow, TargetRow, RestrictionRow)
        ]


def portfolio(sf, md, client_id):
    """Returns (values by symbol, total, target by asset class, restrictions)."""
    with sf() as db:
        rows = db.execute(
            select(HoldingRow, AccountRow).join(AccountRow, HoldingRow.account_id == AccountRow.id)
            .where(AccountRow.client_id == client_id)
        ).all()
        values = defaultdict(float)
        for h, _ in rows:
            values[h.symbol] += h.quantity * md.instrument(h.symbol).price
        target = {t.asset_class: t.weight for t in db.scalars(select(TargetRow).where(TargetRow.client_id == client_id))}
        restr = [(r.kind, r.value) for r in db.scalars(select(RestrictionRow).where(RestrictionRow.client_id == client_id))]
    return dict(values), sum(values.values()), target, restr


def class_weights(md, values, total):
    w = defaultdict(float)
    for s, v in values.items():
        w[md.instrument(s).asset_class] += v / total
    return w


def sector_weights(md, values, total):
    w = defaultdict(float)
    for s, v in values.items():
        for sec, x in md.sector_weights(s).items():
            w[sec] += v / total * x
    return w


def test_seeds_about_25_clients_across_four_risk_profiles_and_both_account_types(sf, md):
    seed_clients(sf, md)
    with sf() as db:
        clients = list(db.scalars(select(ClientRow)))
        assert 24 <= len(clients) <= 26
        assert {c.risk_profile for c in clients} == PROFILES
        assert {a.tax_status for a in db.scalars(select(AccountRow))} == {"taxable", "tax_advantaged"}
        for c in clients:
            tgt = [t.weight for t in db.scalars(select(TargetRow).where(TargetRow.client_id == c.id))]
            assert sum(tgt) == pytest.approx(1.0)


def test_same_seed_gives_identical_clients_and_holdings(tmp_path, md):
    a = make_session_factory(f"sqlite:///{tmp_path / 'a.db'}")
    b = make_session_factory(f"sqlite:///{tmp_path / 'b.db'}")
    seed_clients(a, md, seed=7)
    seed_clients(b, md, seed=7)
    assert dump(a) == dump(b)


def test_reseeding_same_database_replaces_rather_than_duplicates(sf, md):
    seed_clients(sf, md, seed=7)
    first = dump(sf)
    seed_clients(sf, md, seed=7)
    assert dump(sf) == first


def test_different_seed_changes_the_generated_clients(sf, md):
    seed_clients(sf, md, seed=7)
    first = dump(sf)
    seed_clients(sf, md, seed=8)
    assert dump(sf) != first


def test_heavy_tech_scenario(sf, md):
    seed_clients(sf, md)
    v, t, *_ = portfolio(sf, md, PLANTED["heavy_tech"])
    assert sector_weights(md, v, t)["Information Technology"] > 0.40


def test_overweight_energy_scenario(sf, md):
    seed_clients(sf, md)
    v, t, target, _ = portfolio(sf, md, PLANTED["overweight_energy"])
    assert sector_weights(md, v, t)["Energy"] > 0.25
    assert class_weights(md, v, t)["equity"] > target["equity"] + 0.10


def test_cash_drag_scenario(sf, md):
    seed_clients(sf, md)
    v, t, target, _ = portfolio(sf, md, PLANTED["cash_drag"])
    assert class_weights(md, v, t)["cash"] > target["cash"] + 0.20


def test_restricted_instrument_breach_scenario(sf, md):
    seed_clients(sf, md)
    v, t, _, restr = portfolio(sf, md, PLANTED["restricted_breach"])
    restricted = {val for kind, val in restr if kind == "instrument"}
    assert restricted and restricted & set(v)


def test_nobody_else_holds_a_restricted_instrument(sf, md):
    seed_clients(sf, md)
    with sf() as db:
        ids = [c for c in db.scalars(select(ClientRow.id)) if c != PLANTED["restricted_breach"]]
    for cid in ids:
        v, _, _, restr = portfolio(sf, md, cid)
        assert not {val for kind, val in restr if kind == "instrument"} & set(v), cid


def test_clean_portfolio_is_on_target_diversified_and_unrestricted(sf, md):
    seed_clients(sf, md)
    v, t, target, restr = portfolio(sf, md, PLANTED["clean"])
    cw = class_weights(md, v, t)
    assert all(abs(cw[k] - target[k]) < 0.01 for k in target)
    assert max(x for sym, x in v.items() if md.instrument(sym).asset_class == "equity") / t <= 0.10
    assert max(x for k, x in sector_weights(md, v, t).items() if k in md_gics()) <= 0.30
    assert not {val for kind, val in restr if kind == "instrument"} & set(v)


def md_gics():
    from app.market_data import GICS_SECTORS

    return set(GICS_SECTORS)
