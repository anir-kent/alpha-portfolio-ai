# 07: The other Screen Contexts

**What to build:** The Assistant works on every remaining screen, so the drawer is useful wherever an SME is. See spec: Screen identity and Screen Context.

**Blocked by:** 02

**Status:** resolved

- [x] Approvals: pending items and their status
- [x] Audit: the selected Audit Events
- [x] Exchanges: the selected Exchange, included only for users with `llm:read`; other roles get no Exchange body in the prompt
- [x] Governance: the model card
- [x] Config and Health: the platform brief only, answering "how does the platform work" Questions
- [x] Each screen publishes its screen identity (and any selected item) to the drawer, and the drawer stays open across navigation
- [x] Each context draws from the same services as its screen and respects the role's permissions per section
- [x] Manual E2E checklist item: the drawer opens, closes and persists across navigation
