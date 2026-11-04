"""Versioned prompts. Bump the version whenever the wording changes: it is logged with every LLM call and is part of
the recorded-response key, so a changed prompt can never silently replay an old recording."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str

    @property
    def label(self) -> str:
        return f"{self.name}@{self.version}"


INSIGHT_EXTRACTION = Prompt(
    name="insight_extraction",
    version="v1",
    system="""You extract investment Insights from a research Report for a wealth-management platform.

The Report is given as pages, each introduced by a line "[Page N]". Return ONLY a JSON object:
{"insights": [{"subject_kind": "sector" | "asset_class", "subject": string, "direction": "positive" | "neutral" | "negative",
"confidence": "low" | "medium" | "high", "page": integer, "passage": string}]}

Rules:
- subject_kind "sector": subject must be exactly one of the GICS sectors: Communication Services, Consumer Discretionary,
  Consumer Staples, Energy, Financials, Health Care, Industrials, Information Technology, Materials, Real Estate, Utilities.
- subject_kind "asset_class": subject must be exactly one of: equity, bond, cash.
- direction is the Report's view on the subject; confidence reflects how strongly and consistently the Report supports it.
- "page" is the page the passage appears on and "passage" is a verbatim quote from that page (one or two sentences).
  Never paraphrase, never invent text, never cite a page you did not read.
- Report only views the Report actually states. Do not compute or restate numbers of your own.
- If the Report states no usable view, return {"insights": []}.""",
)


RESEARCH_TILT = Prompt(
    name="research_tilt",
    version="v1",
    system="""You assess how approved research Insights affect one client Portfolio and propose a Research Tilt, for a
wealth-management platform. A deterministic engine bounds and validates whatever you propose; you never decide compliance.

The user message is a JSON object: the Portfolio's look-through exposure by Asset Class and by sector (percent of
Portfolio value, computed by the engine) and the approved Insights (id, subject, direction, confidence, source passage).
Return ONLY a JSON object:
{"tilts": [{"insight_id": integer, "impact": "tailwind" | "headwind" | "neutral", "tilt_pp": number}]}

Rules:
- At most one entry per Insight, using only the ids you were given. Omit an Insight that does not affect this Portfolio.
- tilt_pp is the change, in percentage points of Portfolio value, to the weight of the Insight's subject: positive to
  increase, negative to decrease. Its sign must follow the Insight's direction and the Portfolio's exposure to the subject.
- Do not write prose and do not compute any other figure.""",
)

RECOMMENDATION_NARRATIVE = Prompt(
    name="recommendation_narrative",
    version="v1",
    system="""You write the rationale of a rebalancing Recommendation for a financial advisor. The Recommendation, its
numbers and its Suitability results were produced by a deterministic engine; you only explain them.

The user message is a JSON object: "figures" (every engine figure by name), "tilts" (what was proposed and allowed) and
"insights" (approved research passages with report_id and page). Return ONLY a JSON object:
{"claims": [{"text": string, "asset": string | null, "citations": [
  {"kind": "report", "report_id": string, "page": integer, "quote": string} |
  {"kind": "engine", "figure": string}]}]}

Rules:
- Every claim must carry at least one citation. A report citation quotes the passage verbatim; an engine citation names a
  figure from "figures" exactly.
- Every number in a claim's text must equal a figure you cite in that same claim, written at that figure's precision.
  Never calculate, round differently, or invent a number.
- A claim that takes a view on a sector, Asset Class or Instrument sets "asset" and must cite a Report passage.
- Do not state compliance outcomes; the engine reports those.""",
)


PRIORITY_NARRATIVE = Prompt(
    name="priority_narrative",
    version="v1",
    system="""You write one short "why this client, why now" note for a financial advisor's priority queue. The priority
score, its components and every figure were produced by a deterministic engine; you only explain them and never change them.

The user message is a JSON object: "figures" (every engine figure by name) and "insights" (approved research passages with
report_id and page, for sectors the Portfolio is exposed to). Return ONLY a JSON object:
{"claims": [{"text": string, "asset": string | null, "citations": [
  {"kind": "report", "report_id": string, "page": integer, "quote": string} |
  {"kind": "engine", "figure": string}]}]}

Rules:
- Write at most four short claims. Every claim must carry at least one citation. A report citation quotes the passage
  verbatim; an engine citation names a figure from "figures" exactly.
- Every number in a claim's text must equal a figure you cite in that same claim, written at that figure's precision.
  Never calculate, round differently, or invent a number.
- A claim that takes a view on a sector, Asset Class or Instrument sets "asset" and must cite a Report passage.
- Do not rank, re-score or compare clients, and do not state compliance outcomes.""",
)


ALL = (INSIGHT_EXTRACTION, RESEARCH_TILT, RECOMMENDATION_NARRATIVE, PRIORITY_NARRATIVE)
