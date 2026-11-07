# 06: Queue and Recommendation Screen Contexts

**What to build:** The Assistant answers on the Queue and Recommendation screens, the two contexts SMEs will question hardest. The Queue context respects a row budget and says what it cut. The Recommendation context carries the full rationale, with Report passages marked as untrusted, and supports asking about one selected item such as a Trade Line. See spec: Screen identity and Screen Context.

**Blocked by:** 02

**Status:** resolved

- [x] The Queue Screen Context holds the prioritised Portfolios with drift and priority figures, at most 25 rows (configurable) by the Queue's own sort, with a "showing 25 of N" note when cut
- [x] The Recommendation Screen Context holds Trade Lines, Suitability outcomes, Research Tilts, linked Insights with their Report passages, and grounded Claims
- [x] Report passages are fenced as untrusted data in the prompt; an adversarial passage doesn't override an out-of-scope verdict
- [x] A selected-item id is included only if it belongs to the screen's entity; a foreign item gets the Out-of-Scope Refusal
- [x] Sections the role can't read are absent from the prompt; no Client names or emails appear
- [x] The Queue and Recommendation screens publish their screen identity and selected item to the drawer
