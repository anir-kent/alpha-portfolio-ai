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

**Insight Review**:
A Research Analyst's final approval or rejection of an Insight; an Insight not yet reviewed is awaiting review, and only approved Insights can inform a Research Tilt.
_Avoid_: Insight Decision, validation

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

**LLM Trajectory**:
The ordered LLM Exchanges, with the lookups the model asked for between them, that together produce one outcome such as one Answer; a single-call step is a Trajectory of one Exchange.
_Avoid_: Trace, run, session, chain

**Request budget**:
The most model requests one Answer's LLM Trajectory may make, lookups and Self-correction included (a setting, default 6). A Trajectory that would go over it fails the turn with reason `budget_exhausted`; every Exchange it made stays anchored.
_Avoid_: Step limit, max iterations, quota

**Self-correction**:
The one retry an Answer's first draft gets when grounding rejects some of its Claims: the model is told each failing Claim and its issues, and Claims still ungrounded in the second draft are kept, flagged. A draft exposing PII is never self-corrected.
_Avoid_: Reflection, repair, regeneration

### Assistant

**Assistant**:
The read-only conversational helper available on every screen that answers Questions about the platform's own data and workings, using only what the asking user is permitted to see. It never acts and never produces figures the engine did not compute.
_Avoid_: Chatbot, copilot, agent

**Conversation**:
The sequence of Questions and Answers one user has with the Assistant during one login session; it ends at logout or session expiry and cannot be resumed.
_Avoid_: Chat, thread, session

**Question**:
One message a user sends to the Assistant, together with the Screen Context current when it was asked.
_Avoid_: Prompt, query

**Answer**:
The Assistant's reply to one Question, made of Claims that are grounding-checked like any other LLM output.
_Avoid_: Response, completion

**Screen Context**:
The data and metadata behind the screen the user is on, rebuilt by the server from the screen's identity and the user's permissions, never taken from what the browser displays.
_Avoid_: Page data, context window

**Suggested Question**:
A predefined Question offered on a screen, whose Answer is recorded so it also works when the platform replays recordings.
_Avoid_: Canned question, FAQ

**Out-of-Scope Refusal**:
The fixed Answer given to a Question outside the platform's domain, such as general investment advice, market predictions or Clients the user cannot see.
_Avoid_: Rejection, block
