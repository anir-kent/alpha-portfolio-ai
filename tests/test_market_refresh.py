import json

import httpx
import pytest

from app.market_data import MarketData
from app.market_refresh import RefreshError, refresh_snapshot
from app.universe import UNIVERSE
from tests.test_market_data import LOOKTHROUGH


def _series(symbol, last):
    return {
        "meta": {"symbol": symbol, "currency": "USD", "exchange": "NYSE", "type": "ETF"},
        "values": [
            {"datetime": "2026-11-02", "close": str(last)},
            {"datetime": "2026-10-30", "close": str(last - 1)},
        ],
        "status": "ok",
    }


def _handler(fail=None, calls=None):
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apikey"] == "k"
        symbols = request.url.params["symbol"].split(",")
        if calls is not None:
            calls.append(symbols)
        body = {s: _series(s, 100.0 + i) for i, s in enumerate(symbols)}
        if fail:
            body[fail] = {"code": 404, "message": "symbol not found", "status": "error"}
        return httpx.Response(200, json=body)

    return handle


def _run(tmp_path, handler, sleeps=None):
    out = tmp_path / "snap.json"
    client = httpx.Client(transport=httpx.MockTransport(handler))
    refresh_snapshot(
        api_key="k", out_path=out, client=client, sleep=(sleeps.append if sleeps is not None else lambda s: None)
    )
    return out


def test_refresh_writes_a_snapshot_the_adapter_can_load(tmp_path):
    out = _run(tmp_path, _handler())
    md = MarketData.load(out, LOOKTHROUGH)
    assert len(md.instruments()) == len(UNIVERSE)
    assert md.instrument("AAPL").price > 0
    assert "twelve" in md.source.lower()
    assert len(json.loads(out.read_text())["instruments"]["AAPL"]["history"]) == 2


def test_refresh_respects_free_tier_rate_limit(tmp_path):
    calls, sleeps = [], []
    _run(tmp_path, _handler(calls=calls), sleeps)
    assert max(len(c) for c in calls) <= 8
    assert len(sleeps) == len(calls) - 1 and all(s >= 60 for s in sleeps)


def test_refresh_never_writes_a_partial_snapshot(tmp_path):
    out = tmp_path / "snap.json"
    out.write_text("previous")
    client = httpx.Client(transport=httpx.MockTransport(_handler(fail="XOM")))
    with pytest.raises(RefreshError, match="XOM"):
        refresh_snapshot(api_key="k", out_path=out, client=client, sleep=lambda s: None)
    assert out.read_text() == "previous"


def test_snapshot_names_come_from_the_universe_since_the_api_has_none(tmp_path):
    md = MarketData.load(_run(tmp_path, _handler()), LOOKTHROUGH)
    assert md.instrument("XOM").name == "Exxon Mobil Corp"


def test_refresh_waits_and_retries_when_rate_limited(tmp_path):
    state, sleeps = {"n": 0}, []

    def handle(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, json={"code": 429, "status": "error", "message": "limit"})
        return _handler()(request)

    out = _run(tmp_path, handle, sleeps)
    assert sleeps[0] >= 60
    assert len(MarketData.load(out, LOOKTHROUGH).instruments()) == len(UNIVERSE)
