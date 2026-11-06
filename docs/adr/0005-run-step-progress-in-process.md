# Run Step progress is held in process memory, and only one Analysis Run is in flight at a time

The Run Analysis modal shows each Run Step as soon as the backend finishes it. That progress is kept in an in-memory registry inside the API process and pushed to the browser over server-sent events. It is not written to the database while the run is going. The scoring part of an Analysis Run stays one transaction. That transaction holds SQLite's only write lock until it commits (ADR-0004), so no other session can write progress rows that a reader would see. The `analysis_runs` row is created and committed before scoring starts, which gives the browser a durable id at once. When the run ends, its outcome and Run Step results are saved on that row: completed, completed with warnings, failed, or interrupted. One process-wide lock lets only one Analysis Run be in flight. A second start returns `409` with the id of the run in flight, and the modal attaches to it.

## Considered Options

- **Commit each stage separately so progress can be read from the database**: rejected. It gives up the all-or-nothing run. A crash partway through would leave a half-scored run that the Queue, the supersede logic and the audit chain would all have to understand.
- **WAL mode with a second connection writing progress rows**: rejected. WAL lets readers run alongside the writer, but writing progress still needs a second writer, so it hits the same lock.
- **Redis or another external broker for progress**: deferred. It only pays off once there is more than one API process. The registry sits behind a small interface so a broker can replace it without changing the stream contract.
- **Run Step events as Audit Events**: rejected. Step timings are operational telemetry, not business facts. The chain already records the run start, each priority score and each Recommendation draft, and putting telemetry in it can never be undone (ADR-0002).

## Consequences

The design assumes a single API process. Adding workers means replacing the registry first. Each stream event carries the whole run state, keyed by a sequence number for that run, so a reconnecting client only needs the latest event. Updates are combined at the stream's poll interval, so "done" reaches the screen within one poll of the step finishing. A process restart loses the in-flight run: its scoring transaction never commits, and on startup any row still not completed is marked interrupted, so the one-in-flight check cannot get stuck. The scoring transaction still blocks other writers (Decisions, Insight approvals) for as long as it runs, exactly as before. Showing progress does not make that any worse.
