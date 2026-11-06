# Portfolio Rebalancing

An advisor-assist platform that detects portfolio drift, turns market research into portfolio-specific insights, and recommends explainable rebalancing actions that a human reviews and approves. It never executes trades.

## Language

### Clients and holdings

**Client**:
A person whose investments an advisor manages; carries a risk profile, objectives, horizon, liquidity needs and restrictions.
_Avoid_: Customer, account holder

**Portfolio**:
The set of holdings belonging to one Client, evaluated against one Target Allocation.
_Avoid_: Account, book

**Holding**:
A quantity of one Instrument held in a Portfolio.
_Avoid_: Position (except in "single-position limit")

**Instrument**:
A tradable item in the asset universe (equity, fund, ETF, bond, cash, structured product) with an asset class, and sector exposure where applicable.
_Avoid_: Security, asset (ambiguous with Asset Class)

**Asset Class**:
A top-level category of Instruments (e.g. equity, bond, cash) used for allocation targets.

**Risk Profile**:
A Client's assessed risk tolerance band; determines default Target Allocation and suitability limits.

**Restriction**:
A Client-specific exclusion of an Instrument or sector.

### Drift

**Target Allocation**:
The intended weight of each Asset Class in a Portfolio, per Client's Risk Profile.
_Avoid_: Model portfolio, benchmark

**Asset-Class Drift**:
The absolute percentage-point deviation of an Asset Class's actual weight from its target weight.

**Tolerance Band**:
The warn and breach thresholds for Asset-Class Drift, configurable per Risk Profile.

**Portfolio Drift**:
Half the sum of absolute Asset-Class Drifts: the share of the Portfolio that would have to move to return to target.

### Analysis

**Analysis Run**:
One on-demand scoring of every Portfolio, ending completed, completed with warnings (an AI step failed after the results were recorded), failed or interrupted. The latest run with recorded results is current; only one can be in flight at a time.
_Avoid_: Job, batch, analysis (on its own)

**Run Step**:
One named stage of an Analysis Run, with an outcome of pending, running, done, failed or skipped.
_Avoid_: Phase, task, stage

### Research

**Report**:
A source document (research, house view, outlook) ingested into the platform.

**Insight**:
A cited, structured claim extracted from a Report (e.g. a sector view), always traceable to a Report passage.
_Avoid_: Signal, finding

**Research Tilt**:
A bounded, configurable adjustment to target weights derived from an Insight and validated by the engine.

### Recommendation and decision

**Recommendation**:
The proposed set of Trade Lines for one Portfolio from one Analysis Run, with rationale and citations. Modifying it creates a new linked version.
_Avoid_: Advice, proposal, suggestion

**Trade Line**:
One proposed buy or sell of an Instrument within a Recommendation.
_Avoid_: Order, trade (nothing is executed)

**Suitability Rule**:
A deterministic check of a Recommendation or Portfolio against a Client's profile, limits and Restrictions; returns pass, warning or breach with the numbers behind it.

**Suitability Exception**:
A Recommendation with a Suitability Rule breach that needs Compliance sign-off to proceed.

**Decision**:
A human's accept, modify or reject of a Recommendation, with captured rationale.
_Avoid_: Approval (only one outcome of a Decision)

**Audit Event**:
An append-only, hash-chained record of an Insight, Recommendation, Suitability result or Decision, linked to its lineage.
_Avoid_: Log entry

### Grounding

**Claim**:
One statement an LLM makes about a Portfolio, Recommendation or asset, with its citations.

**Grounded**:
A Claim whose Report citations quote a real Report page verbatim, whose engine citations name real engine figures, and whose numbers all match those figures. Anything else is flagged ungrounded: kept out of memos but still shown to the Advisor.

### Transparency

**LLM Exchange**:
One request and reply through the single LLM interface: the full prompt, reply schema, raw reply, model, prompt version, timing, token counts and outcome, labelled live or recorded. An Audit Event can point to the Exchange that produced it.
_Avoid_: Log entry, trace, transcript
