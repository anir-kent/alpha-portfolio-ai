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
