# Portfolio Rebalancing

Advisor-assist platform; it never executes trades. Vocabulary: `GLOSSARY.md`. Decisions: `docs/adr/`.

## Data stance

**Market data is real; Clients are synthetic** (ADR-0003). No real client data is used anywhere.

- **Market data snapshot** (`data/market_snapshot.json`, committed). ~30 Instruments: 13 equities and 11 sector ETFs covering the 11 GICS sectors, SPY, 4 bond ETFs and a cash proxy (SGOV). The app reads it through `app.market_data.MarketData` and runs fully offline; the refresh script is the only code that uses the network.
  - Refresh: `APP_TWELVE_DATA_API_KEY=<free key> uv run python -m app.market_refresh`. Respects the free tier (8 symbols per minute, so it takes about 4 minutes) and leaves the existing snapshot untouched if any symbol fails.
  - **The snapshot currently committed is a bootstrap placeholder** (`source` starts with `bootstrap-estimate`): approximate prices, not fetched data. Run the refresh once and commit the result.
- **Fund look-through** (`data/fund_lookthrough.json`, hand-built). Sector weights for every fund and ETF, because the free tier provides none. Sector ETFs are 100% their sector, bond funds are `Fixed Income`, the cash proxy is `Cash`.
- **Synthetic Clients** (`uv run python -m app.seeder [--seed N]`). Deterministic: the same seed and snapshot give identical Clients, Accounts, Holdings, Target Allocations and Restrictions. Re-running replaces all Client data. Generates 25 Clients across four Risk Profiles with taxable and tax-advantaged accounts. Planted scenarios have fixed IDs: `C001` heavy tech, `C002` overweight energy, `C003` cash drag, `C004` restricted-instrument breach (holds XOM, restricted), `C005` clean Portfolio. Review-due dates are relative to the snapshot date.
