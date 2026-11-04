# 13: Governance page and AI quality panel

**What to build:** A governance page for the Auditor (and Platform Owner) with a model card and prompt/version log generated from system data, plus an AI quality panel: grounding pass rate, ungrounded-claim counts and adversarial fixture results.

**Blocked by:** 11

**Status:** done

- [x] All figures are computed from stored audit and grounding data, not hand-written
- [x] Prompt/version log lists every prompt version used and when
- [x] Fixture results reflect the latest run of the adversarial fixtures
- [x] Page is restricted to permitted roles

## Implementation notes

- `GET /api/governance` (`governance:read`: Auditor, Platform Owner) returns model card, prompt/version log, AI quality panel and latest fixture run. `app/governance.py` computes everything from stored data: grounding results, audit events (events carrying a prompt version), live settings/config.
- `POST /api/governance/fixtures/run` (`governance:run`) runs nine committed adversarial/valid claims through the real validator against a throwaway in-memory database (quality figures stay untouched), stores the run and audits `adversarial_fixtures_run`. A fixture passes only if the validator raises exactly the expected codes.
- Decision for review: the Auditor holds `governance:run`, which writes a run row and an audit event. Drop it from `auditor` in `app/rbac.py` if the Auditor must stay strictly read-only.
