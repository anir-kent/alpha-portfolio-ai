# 06: Review a batch from the keyboard

**What to build:** A Research Analyst can work through Insights without the mouse, on both To review and Report detail. `j` or ↓ selects the next Insight, `k` or ↑ the previous; `a` approves the selected Insight; `r` opens the reject dialog; Escape closes the dialog. The shortcuts are shown next to their buttons. They are ignored while focus is in a text input, a textarea or the dialog, and when the selected Insight is not awaiting review. Combined with auto-advance from tickets 04 and 05, an Analyst can review a whole Report with `a`, `r` and the note field alone.

See spec: Keyboard model.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] `j`/↓ and `k`/↑ move the selection on To review and Report detail, keeping the selected row in view and in the URL
- [ ] `a` approves and `r` opens the reject dialog only for an Insight awaiting review and only with the `insight:approve` permission
- [ ] Shortcuts do nothing while typing in a note or title field, while any dialog is open, or for a reviewed Insight
- [ ] Each shortcut is shown as a key hint beside its button, and every shortcut has a visible, labelled button equivalent
- [ ] The selected row is announced to assistive technology (selected state on the list item), and focus is visible
- [ ] The Research Analyst checklist section gains: review the demo house view's Insights with the keyboard only, including one rejection with a note; confirm typing `a` in a note does not approve
- [ ] Typecheck, lint, format check and build pass
