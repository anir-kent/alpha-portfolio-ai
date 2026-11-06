# 03: Live stream: Run Steps pushed over server-sent events, with reconnect

**What to build:** The modal stops polling. Each Run Step change is pushed from the backend, so a step shows as done within one stream poll of the backend finishing it. The stream follows the LLM Exchange stream's pattern: auth session freed, keepalives, standard reconnect. The difference is that each event carries the full run snapshot, so a reconnecting client only needs the latest one. If the connection drops, the modal shows that it is reconnecting and recovers on its own. If the stream is refused or gone, it falls back to the snapshot endpoint. Contract in the spec at `.scratch/run-analysis-progress/spec.md`.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] `GET /analysis/runs/{id}/events` serves `text/event-stream`, sends a `progress` event with the full snapshot on connect and on every change (combined at the stream poll interval), and uses the run's sequence number as the event id
- [ ] The stream sends the final snapshot when the run gets an outcome, then closes. Connecting to an already finished run sends its final snapshot and closes
- [ ] A reconnect carrying `Last-Event-ID` equal to the current sequence number does not send the unchanged snapshot again
- [ ] Keepalives are sent while nothing changes, and the stream frees its auth session the way the Exchange stream does
- [ ] Requires `analysis:run`; denial is `403` and is audited
- [ ] API tests, using the existing stream-reading pattern and a blocking fake LLM: events arrive in sequence order, the frozen mid-run state is visible on the stream, the stream closes after the outcome, and `Last-Event-ID` resume works
- [ ] The modal uses `EventSource` with credentials and shows connecting, live, reconnecting and unavailable states. When the stream is unavailable it falls back to polling the snapshot, and the latest snapshot always replaces what is shown
- [ ] `npm run typecheck` and `npm run build` pass; the manual E2E checklist gains an item for steps ticking without polling and for recovering after the API restarts mid-watch
