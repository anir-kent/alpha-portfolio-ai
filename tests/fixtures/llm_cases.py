"""Hand-authored LLM replies for the fixture Reports. Regenerate the committed recordings with
`uv run python -m tests.fixtures.llm_cases` (needed only if a fixture Report or the prompt version changes)."""
from pathlib import Path

from app.llm import LlmResponse, write_recording
from app.reports import extract_pages, extraction_request

HERE = Path(__file__).parent
MODEL = "claude-sonnet-5-5"

CASES = {
    "house_view_demo.txt": {"insights": [
        {"subject_kind": "sector", "subject": "Information Technology", "direction": "positive", "confidence": "high",
         "page": 1, "passage": "We are constructive on technology."},
        {"subject_kind": "sector", "subject": "Utilities", "direction": "negative", "confidence": "medium",
         "page": 1, "passage": "Utilities look expensive after the rally and offer limited upside from here."},
        {"subject_kind": "asset_class", "subject": "equity", "direction": "positive", "confidence": "medium",
         "page": 2, "passage": "We prefer equities over bonds for the next twelve months as growth stays resilient."},
    ]},
    # a fabricated quote, an out-of-taxonomy subject, a page that does not exist, and one genuine claim
    "house_view_adversarial.txt": {"insights": [
        {"subject_kind": "sector", "subject": "Energy", "direction": "positive", "confidence": "high",
         "page": 1, "passage": "Energy will double next year according to our model."},
        {"subject_kind": "sector", "subject": "Energy", "direction": "positive", "confidence": "high",
         "page": 1, "passage": "Energy stocks are guaranteed to outperform."},
        {"subject_kind": "sector", "subject": "Crypto", "direction": "positive", "confidence": "low",
         "page": 1, "passage": "Nothing else of note."},
        {"subject_kind": "asset_class", "subject": "bond", "direction": "negative", "confidence": "low",
         "page": 9, "passage": "Nothing else of note."},
    ]},
}


def regenerate() -> None:
    for name, content in CASES.items():
        _, pages = extract_pages(name, (HERE / name).read_bytes())
        req = extraction_request(pages)
        write_recording(HERE / "llm", req, LlmResponse(content, MODEL, req.prompt_version))


if __name__ == "__main__":
    regenerate()
