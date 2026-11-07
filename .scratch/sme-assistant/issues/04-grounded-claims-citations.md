# 04: Grounded Claims and citation chips

**What to build:** Every Claim in an Answer is grounding-checked against the engine figures in the Screen Context and the Report passages it cites. Ungrounded Claims are shown with an inline marker, and citation chips let the user open the Report passage or jump to the figure's source screen. See spec: Checks after the reply (grounding), Frontend.

**Blocked by:** 01, 02

**Status:** resolved

- [x] Claims whose figures match Screen Context figures, and whose Report citations quote a real page verbatim, come back grounded
- [x] Claims citing figures absent from the Screen Context, or with mismatched numbers, come back flagged ungrounded and stay in the Answer
- [x] The grounding check is linked to the Assistant turn and appears through the existing grounding read paths
- [x] Grounding finishes before the Answer is returned; nothing is shown before it
- [x] The drawer shows citation chips (a Report citation opens the passage, an engine figure goes to its screen) and an "ungrounded" marker per flagged Claim
- [x] Manual E2E checklist items: a citation chip opens the passage, an ungrounded marker shows (a live Report chip needs a context with Report passages: ticket 06)
