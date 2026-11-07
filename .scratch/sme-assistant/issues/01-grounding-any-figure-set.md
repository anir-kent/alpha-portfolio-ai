# 01: Prefactor: grounding accepts any figure set and any subject

**What to build:** Generalise the grounding check so it can validate Claims against a figure set that isn't tied to a single Client, and link its stored check and Audit Event to a subject other than a Recommendation or a priority result. This is a prefactor for the Assistant (spec: Checks after the reply, step 2). It changes no behaviour for existing callers.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] The grounding entry point accepts an optional Client and a generic subject reference, alongside the existing Recommendation and run links
- [x] Existing callers (Recommendation memos, priority narratives) produce the same results, stored checks and Audit Events as before
- [x] All existing grounding, governance and recommendation tests pass unchanged
- [x] A test through an existing API shows a check validated against a figure set not tied to a Client stores and reports its results correctly
