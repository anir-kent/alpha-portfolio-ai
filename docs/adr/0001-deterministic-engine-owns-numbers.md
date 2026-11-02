# Deterministic engine owns numbers and suitability; the LLM only interprets and explains

All drift, priority, trade amounts and suitability pass/warning/breach outcomes are computed by deterministic code. The LLM extracts Insights from Reports, links them to portfolio exposures, proposes Research Tilts (which the engine bounds and validates), and writes rationale and advisor memos. Every LLM claim must cite a Report passage or an engine figure, and ungrounded claims are flagged and kept out of the memo.

## Considered Options

- **LLM-driven optimisation**: rejected. It would make numbers and compliance outcomes non-reproducible and unauditable, and it conflicts with the spec's "must not become a black-box trading engine".
- **Mean-variance optimiser**: rejected. Neither provided PDF supplies expected returns or covariances, so inputs would be invented, breaking the grounding rule.

## Consequences

Rebalancing is rule-based and band-based, with a bounded, configurable Research Tilt. Tests can assert exact numbers on seeded scenarios, and the LLM can be swapped (or replayed from recordings) without changing any compliance outcome.
