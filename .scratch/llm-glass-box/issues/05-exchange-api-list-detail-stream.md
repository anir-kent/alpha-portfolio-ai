# 05: Exchange API: list, detail and live stream

**What to build:** Roles with `llm:read` can query Exchanges and watch new ones arrive. A paginated newest-first list supports the review filters; the detail view includes where the Exchange was used and the grounding verdict on the resulting Claims; a server-sent event stream pushes new Exchanges as they complete and resumes without gaps after a dropped connection. Everything is refused, and audited, for any other role.

**Blocked by:** 03

**Status:** done

- [x] The list returns summary rows only (no bulk text) newest first, with the linked Recommendation or Portfolio taken from the referencing Audit Event, and supports pagination
- [x] The list filters by task, prompt version, mode, outcome and date range, in any combination
- [x] The detail returns the full record plus the referencing Audit Events and the grounding verdict joined through the event's check id
- [x] The stream emits each new Exchange once, in id order, at about one-second latency, and honours the standard last-event-id resume header so a reconnect misses nothing and repeats nothing
- [x] The stream needs no in-process publisher and works from the session cookie
- [x] Every endpoint is gated on `llm:read`; Advisor, Relationship Manager and other roles are refused and the refusal appears as an `access_denied` Audit Event
- [x] Tests run through the HTTP API, covering filters, pagination, resume, grounding join and refusals
- [x] The generated OpenAPI client is regenerated and `npm run typecheck` passes
