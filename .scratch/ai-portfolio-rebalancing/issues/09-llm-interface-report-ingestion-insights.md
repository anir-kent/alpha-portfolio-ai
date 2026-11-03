# 09: LLM interface, Report ingestion, Insights

**What to build:** A single OpenAI-compatible LLM interface (Anthropic first, gateway-ready) with versioned prompts, model and prompt-version logging, and a recorded-response mode. Report ingestion accepts PDF or text with page references and the LLM extracts structured, cited Insights (sector or Asset Class, direction, confidence, passage). Insights start pending and need Research Analyst approval via the API. Seeds: the two provided PDFs and 2-3 synthetic house views as sample Reports, the hand-transcribed p3 scorecard, and sample Insights approved as human-verified.

**Blocked by:** 02

**Status:** done

- [x] Tests run entirely on recorded responses; live smoke tests run only on demand
- [x] Every LLM call logs model and prompt version to the audit chain
- [x] Uploaded Reports produce pending Insights; only approved Insights are retrievable for tilt use
- [x] Insights carry citations to Report page and passage
- [x] Seeded items are marked human-verified in the audit trail
- [x] Research Analyst role can upload and approve through the API; other roles are denied and audited
