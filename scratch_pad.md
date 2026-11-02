Q1 - Yes, Build a local end-to-end demonstrator, and treat the "contract-first" principle as real by defining the API contracts. The real integrations stay as stubs behind those contracts.

Q2 - Yes. Use FastAPI, Pydantic v2 and SQLite through SQLAlchemy, and manage the project with uv. This is easy to demo, and the contracts come out as OpenAPI for free.

Q3 - I would prefer separate React front end however I agree to your point the primary value is in workflow and the audit trail but since this demo is a part of second round interview selection so I am putting some weight on UI as well

Q4 - I agree with you all suggestions also I am planning to use AI Gateway like `https://www.litellm.ai/` eventually if not in the first wave

Q5 - Yes. The deterministic engine owns the numbers and the suitability pass/fail. The LLM interprets and explains. It can propose a "research tilt", but only within bounds the engine checks.

Q6 - I want working views only for advisor/RM (queue, drill down, decision), Compliance Officer (suitability flags, exception approval) and auditor(audit, search). Other five would be role label in RBAC with dashboard or upload page added only if time allows. Those three personas carry the Human-In-the-loop (HITL) and auditability story, the rest are lightweight.

Q7 - Yes. Use a tiered workflow with configurable thresholds, and make "no approval without a human" a hard invariant that tests enforce.

Q8 - Yes. Use a simple append-only, hash-chained audit table with lineage links. It's cheap to build and it's what the Auditor persona needs.

