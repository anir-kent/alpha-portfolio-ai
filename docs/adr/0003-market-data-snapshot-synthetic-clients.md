# Real market data from a committed snapshot behind an adapter; clients are synthetic and seeded

Prices and instrument metadata come from an open source (Twelve Data free tier), fetched by a refresh script into a committed snapshot that the app reads at run time, behind a market-data adapter. Clients, holdings, targets and restrictions are generated synthetically by a seeded script, with planted scenarios (heavy tech, overweight energy, cash drag, restricted-instrument breach, clean portfolio).

## Considered Options

- **Live API calls at run time**: rejected. Free-tier rate limits and network dependence would make the demo and tests flaky.
- **Real or scraped client data**: rejected. The spec limits the demonstrator to synthetic, anonymised or client-consented data.

## Consequences

Demos and tests are repeatable offline. Fund sector look-through weights come from a small hand-built reference file because the free tier does not provide them. The README must state the real-market / synthetic-client split.
