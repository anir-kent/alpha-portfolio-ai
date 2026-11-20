---
status: accepted, amended by ADR-0010 (Audit Events anchor an ordered list of Exchanges) and ADR-0011 (capture by a LangChain callback, not at the HTTP transport; each Exchange names its Graph Node; the pipeline is live only)
---

# LLM Exchanges are stored in their own append-only table and anchored in the audit chain by hash

Every call through the LLM interface is captured as an LLM Exchange: successful and failed calls alike, all live. The Exchange stores the messages sent, the raw reply text before parsing, token usage and latency (ADR-0011 captures them as LangChain sent and received them). Exchanges written before recorded mode was removed carry the stored mode "recorded" and no usage or latency; the mode stays in their hash so chain verification still passes. Exchanges live in a separate append-only table rather than inside Audit Event payloads, because prompts carry report passages and portfolio figures and would bloat the chain. Each Exchange has a content hash, and the Audit Event that the calling code already writes references the Exchange by id and hash, so altering an Exchange breaks the chain check.

## Considered Options

- **Full prompt and reply inside the Audit Event payload**: rejected. Simpler, but it makes every chain write and the verify walk heavy, and it mixes business records with bulk text.
- **Separate table with no link to the chain**: rejected. The Exchange would be editable without detection, which defeats the purpose of showing an Auditor what the model actually saw and said.
- **Capture live calls only**: this was rejected while a replay mode existed, so that the glass box would not be empty when the system was demonstrated. With replay removed (ADR-0011) every call is live and captured.

## Consequences

One immutable row is written per call as soon as the reply or error is in, before the caller writes its Audit Event. A caller already inside a write transaction (the analysis run, which asks for Research Tilts mid-run) binds the capture client to its own session, so the Exchange is written in that transaction behind a savepoint; SQLite cannot take a second writer. Its outcome is transport-level only (reply parsed, or error); a reply the caller later rejects stays `ok` on the Exchange and the Audit Event records the rejection. The grounding verdict is not copied onto the Exchange; it is joined through the Audit Event's check id. If an Exchange cannot be saved the call fails (fail closed), so an unrecorded model output never reaches an Advisor; the existing "AI step failed" path absorbs it. Chain verification also recomputes the hash of every Exchange an event references and reports the first mismatch or missing row. Exchanges are kept verbatim with no size cap and no deletion, matching ADR-0002; retention and archival are a production concern.

Raw Exchange text is stored verbatim, which is acceptable only because clients are synthetic (ADR-0003); a production deployment needs a redaction step before persistence. Credentials are never stored, since the API key travels only in the request header. Reading raw Exchanges needs its own permission, held by the auditor, compliance_officer and platform_owner roles; advisors see only a summary through the lineage view. Capture wraps the LLM interface, so call sites are unchanged and correlate to Exchanges through the Audit Events they already write. Events written before capture carry no Exchange reference and are not backfilled; verification treats that as pre-capture, not as a break. Prompts must stay free of client names and emails, which is what lets the `llm:read` permission stand apart from `client:pii`; a test guards it. The glass box is read-only evidence: no re-running or editing prompts from the UI.
