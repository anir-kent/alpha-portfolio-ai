# 02: Audit Events anchor an ordered LLM Trajectory

**What to build:** An Auditor can verify a Trajectory, meaning several LLM Exchanges behind one outcome, as a tamper-evident unit. Every LLM Exchange records the Trajectory it belongs to and its position in it, and both are covered by its content hash. Every Audit Event that references model output carries an ordered list of `{exchange_id, exchange_hash}`. Chain verification proves the list is complete, unaltered and in order. Today's steps each write a list of one on the current client. ADR-0004 as amended by ADR-0010; spec: "Capture", "Audit anchoring", "Verification".

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] Hand-written, idempotent migration adds Trajectory id and position to LLM Exchanges. Rows written before it stay valid and are treated as single-Exchange Trajectories
- [x] Trajectory id and position are part of the Exchange content hash
- [x] The helper that builds an Audit Event's Exchange reference returns an ordered `exchanges` list from a response, an error, or a sequence of them. Every existing caller writes a list of one with no other change
- [x] Verification recomputes every Exchange in each list, checks one shared Trajectory id with positions 0..n-1 in list order, and reports the first altered, missing or reordered Exchange against its Audit Event
- [x] Events with the legacy single `exchange_id`/`exchange_hash` and events with no reference still verify, as today
- [x] The LLM Exchanges API exposes Trajectory id and position. Generated OpenAPI schema and frontend types are updated
- [x] Tamper tests cover a Trajectory of one and of three (built in the test): edit one Exchange, swap two positions, delete the middle Exchange, plus legacy events verifying
