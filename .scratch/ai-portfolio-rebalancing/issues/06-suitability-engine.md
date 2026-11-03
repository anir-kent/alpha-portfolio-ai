# 06: Suitability engine

**What to build:** The seven deterministic Suitability Rules: max equity share by Risk Profile, single-position limit, sector concentration with look-through, minimum cash reserve, Client Restrictions, horizon check, and a taxable-gain warning. Each returns pass, warning or breach with rule ID and the numbers behind it. Results are shown on the drill-down and feed the priority risk component.

**Blocked by:** 05

**Status:** ready-for-agent

**Carry-forward from 04:** planted scenarios C001 (heavy tech) and C004 (restricted instrument) have no Asset-Class Drift and rank low in the queue; once suitability feeds the risk component, add ranking assertions for them. The risk component is currently worst Asset-Class Drift / breach threshold (`app/priority.py`).

- [ ] Each rule has tests with exact numbers on the planted scenarios
- [ ] Restricted-instrument scenario returns a breach naming the rule and Instrument
- [ ] Clean Portfolio passes all rules
- [ ] Suitability evaluation is audited with its results
- [ ] Priority risk component uses these results
- [ ] Full tax-lot optimisation is not implemented
