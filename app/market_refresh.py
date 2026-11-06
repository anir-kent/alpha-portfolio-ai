"""Refresh script: the only code in the project that uses the network (ADR-0003).

Pulls prices and metadata from Twelve Data (free tier) into the committed snapshot.
Usage: APP_TWELVE_DATA_API_KEY=... uv run python -m app.market_refresh
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.universe import NAMES, UNIVERSE

API = "https://api.twelvedata.com/time_series"
BATCH = 8  # free tier: 8 credits per minute, one credit per symbol
HISTORY_DAYS = 30
RETRIES = 2


class RefreshError(RuntimeError):
    pass


def _parse(symbol: str, data: dict) -> dict:
    if not isinstance(data, dict) or data.get("status") == "error" or "values" not in data:
        msg = data.get("message") if isinstance(data, dict) else data
        raise RefreshError(f"{symbol}: {msg}")
    meta, values = data["meta"], data["values"]
    if not values:
        raise RefreshError(f"{symbol}: no price data returned")
    history = [{"date": v["datetime"], "close": float(v["close"])} for v in values]
    return {
        "name": NAMES[symbol],
        "exchange": meta.get("exchange", ""),
        "currency": meta.get("currency", "USD"),
        "price": history[0]["close"],
        "price_date": history[0]["date"],
        "history": history,
    }


def refresh_snapshot(api_key: str, out_path, client: httpx.Client | None = None, sleep=time.sleep) -> None:
    if not api_key:
        raise RefreshError("APP_TWELVE_DATA_API_KEY is not set (free key: https://twelvedata.com)")
    client = client or httpx.Client(timeout=30)
    symbols = [u.symbol for u in UNIVERSE]
    batches = [symbols[i : i + BATCH] for i in range(0, len(symbols), BATCH)]
    instruments: dict[str, dict] = {}
    for n, batch in enumerate(batches):
        if n:
            sleep(61)
        params: dict[str, str | int] = {"symbol": ",".join(batch), "interval": "1day", "outputsize": HISTORY_DAYS, "apikey": api_key}
        for attempt in range(RETRIES + 1):
            r = client.get(API, params=params)
            if r.status_code != 429 or attempt == RETRIES:
                break
            sleep(61)  # per-minute credit limit hit: wait for the window to reset
        if r.status_code != 200:
            raise RefreshError(f"{','.join(batch)}: HTTP {r.status_code}")
        body = r.json()
        if isinstance(body, dict) and body.get("status") == "error" and "code" in body:
            raise RefreshError(f"{','.join(batch)}: {body.get('message')}")
        if len(batch) == 1 and "meta" in body:  # single-symbol responses are not keyed by symbol
            body = {batch[0]: body}
        for s in batch:
            instruments[s] = _parse(s, body.get(s))
    snapshot = {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Twelve Data (free tier) via app.market_refresh",
        "instruments": instruments,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2) + "\n")
    os.replace(tmp, out)


if __name__ == "__main__":
    from app.settings import Settings

    s = Settings()
    try:
        refresh_snapshot(s.twelve_data_api_key, s.market_data_snapshot_path)
    except RefreshError as e:
        sys.exit(f"refresh failed, existing snapshot left untouched: {e}")
    print(f"wrote {s.market_data_snapshot_path}")
