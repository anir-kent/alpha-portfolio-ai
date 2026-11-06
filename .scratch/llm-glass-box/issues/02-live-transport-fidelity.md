# 02: Live transport fidelity

**What to build:** A live LLM call stores exactly what crossed the wire, so the glass box shows what the model really saw and said rather than a reconstruction. The Exchange gains the exact messages sent (including the schema text appended to the system message), the raw reply text before parsing, token usage, latency, endpoint host and the live label. A replay stores what it can and marks tokens and latency as not available (replayed). Credentials never appear in any stored record.

**Blocked by:** 01

**Status:** done

- [x] A live-mode Exchange (exercised through the existing mock-transport pattern) stores the exact request messages, the raw reply text before JSON parsing, token usage, latency and the endpoint host, and is labelled `live`
- [x] A recorded-mode Exchange labels tokens and latency as not available (replayed) rather than showing zero
- [x] A provider error or timeout produces an error Exchange with the failure text and, where known, the HTTP status
- [x] A reply that is not valid JSON produces an error Exchange that keeps the raw text
- [x] The API key and request headers never appear in any stored Exchange or in any endpoint response
- [x] The Exchange content hash covers the new fields and the response from the single-Exchange endpoint exposes them to `llm:read` roles
- [x] Tests run through the HTTP API with no network
