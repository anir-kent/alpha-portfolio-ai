# Audit trail is a single append-only, hash-chained table with lineage links

Every Audit Event (report ingested, insight, recommendation, suitability result, decision, exception, access denied) is appended to one global table. Each row stores its actor (user, or system with model and prompt version), payload, parent event IDs for lineage (insight → recommendation → decision) and the previous row's hash. A verify endpoint walks the chain and reports the first break.

## Considered Options

- **Ordinary mutable tables with timestamps**: rejected. Nothing would show tampering, and the Auditor persona needs evidence rather than assertion.
- **Event-sourcing framework**: rejected. Too heavy for a demonstrator, and the domain state does not need to be rebuilt from events.
- **One chain per Portfolio**: rejected. System-level events (report ingestion, model changes) belong to no single Portfolio.

## Consequences

Writes to the chain are serialised, which is acceptable at demonstrator scale. Audit rows are never updated or deleted, so corrections are new events.
