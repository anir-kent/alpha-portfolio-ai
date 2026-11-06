# 07: The other Screen Contexts

**What to build:** The Assistant works on every remaining screen, so the drawer is useful wherever an SME is. See spec: Screen identity and Screen Context.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Approvals: pending items and their status
- [ ] Audit: the selected Audit Events
- [ ] Exchanges: the selected Exchange, included only for users with `llm:read`; other roles get no Exchange body in the prompt
- [ ] Governance: the model card
- [ ] Config and Health: the platform brief only, answering "how does the platform work" Questions
- [ ] Each screen publishes its screen identity (and any selected item) to the drawer, and the drawer stays open across navigation
- [ ] Each context draws from the same services as its screen and respects the role's permissions per section
- [ ] Manual E2E checklist item: the drawer opens, closes and persists across navigation
