# 03: Market-data snapshot and synthetic seeder

**What to build:** A refresh script that pulls prices and instrument metadata (Twelve Data free tier) for a ~30-Instrument universe into a committed snapshot, read at run time through a market-data adapter (ADR-0003). A hand-built look-through reference file for funds. A deterministic seeder that generates ~25 synthetic Clients across four Risk Profiles with Target Allocations, Holdings, Restrictions and taxable/tax-advantaged accounts, including the planted scenarios.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Universe covers the 11 GICS sectors via equities and sector ETFs, plus bond ETFs and a cash proxy
- [ ] App runs fully offline from the committed snapshot; refresh script is the only network user
- [ ] Re-seeding with the same seed produces identical Clients and Holdings
- [ ] Planted scenarios exist: heavy tech, overweight energy, cash drag, restricted-instrument breach, clean Portfolio
- [ ] Look-through sector weights exist for every fund and ETF in the universe
- [ ] Seeder and refresh script documented in the README section on data stance
