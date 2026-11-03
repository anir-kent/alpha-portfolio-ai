import socket
from pathlib import Path

import pytest

from app.market_data import GICS_SECTORS, MarketData

DATA = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT = DATA / "market_snapshot.json"
LOOKTHROUGH = DATA / "fund_lookthrough.json"


@pytest.fixture
def md():
    return MarketData.load(SNAPSHOT, LOOKTHROUGH)


def test_universe_has_about_thirty_instruments_with_prices(md):
    assert 28 <= len(md.instruments()) <= 32
    assert all(i.price > 0 for i in md.instruments())


def test_universe_covers_all_gics_sectors_via_equities_and_sector_etfs(md):
    eq = {i.sector for i in md.instruments() if i.kind == "equity"}
    etf = {i.sector for i in md.instruments() if i.kind == "fund" and i.sector}
    assert eq == set(GICS_SECTORS)
    assert etf == set(GICS_SECTORS)


def test_universe_has_bond_etfs_and_a_cash_proxy(md):
    classes = {i.asset_class for i in md.instruments()}
    assert classes == {"equity", "bond", "cash"}
    assert len([i for i in md.instruments() if i.asset_class == "bond"]) >= 3
    assert len([i for i in md.instruments() if i.asset_class == "cash"]) == 1


def test_every_fund_has_look_through_weights_summing_to_one(md):
    funds = [i for i in md.instruments() if i.kind == "fund"]
    assert funds
    for f in funds:
        w = md.sector_weights(f.symbol)
        assert w, f.symbol
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-6), f.symbol


def test_single_stock_is_fully_in_its_own_sector(md):
    assert md.sector_weights("XOM") == {"Energy": 1.0}


def test_broad_etf_look_through_exposes_hidden_tech(md):
    assert md.sector_weights("SPY")["Information Technology"] > 0.2


def test_load_and_lookup_never_touch_the_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket.socket, "connect", boom)
    m = MarketData.load(SNAPSHOT, LOOKTHROUGH)
    assert m.instrument("AAPL").price > 0


def test_missing_snapshot_fails_with_clear_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="refresh"):
        MarketData.load(tmp_path / "nope.json", LOOKTHROUGH)
