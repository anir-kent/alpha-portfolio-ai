# 07: Exchange drawer, JSON download and lineage entry points

**What to build:** A reviewer can open any Exchange and read the whole conversation, then carry the exact record away as evidence. Clicking a feed row opens a drawer with tabs for the Prompt, the reply Schema, the Reply (raw and parsed), the Metadata and where the Exchange was Used by. AI nodes in the lineage graph open the same drawer, and the drawer links back to the Recommendation's lineage.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] The drawer has Prompt (system text and user prompt), Schema, Reply (raw text with a parsed view), Metadata (hashes, tokens, latency, model, endpoint host, mode) and Used by (referencing Audit Events and the grounding verdict) tabs
- [ ] Ungrounded Claims are visibly marked next to the reply that produced them
- [ ] "Download JSON" saves the single Exchange including its hash
- [ ] AI nodes in the lineage graph show a "View exchange" action for `llm:read` roles that opens the same drawer; it is absent for roles without `llm:read`
- [ ] The drawer links to the Recommendation's lineage when the Exchange belongs to one
- [ ] The drawer is portalled so the frosted panels never clip it, closes on Escape and on the scrim, and long content scrolls inside it
- [ ] Error Exchanges show the error text and any raw reply that was captured
- [ ] The manual E2E checklist gains items for the drawer, download and lineage link
- [ ] `npm run typecheck` and `npm run build` pass
