"""Hand-authored LLM replies for the fixture Reports: what the demo's fake chat model (`tests.fake_chat.DemoPipeline`)
answers each Report's Insight extraction request with."""

from pathlib import Path

from app.reports import extract_pages, extraction_request

HERE = Path(__file__).parent

CASES = {
    "house_view_demo.txt": {
        "insights": [
            {
                "subject_kind": "sector",
                "subject": "Information Technology",
                "direction": "positive",
                "confidence": "high",
                "page": 1,
                "passage": "We are constructive on technology.",
            },
            {
                "subject_kind": "sector",
                "subject": "Utilities",
                "direction": "negative",
                "confidence": "medium",
                "page": 1,
                "passage": "Utilities look expensive after the rally and offer limited upside from here.",
            },
            {
                "subject_kind": "asset_class",
                "subject": "equity",
                "direction": "positive",
                "confidence": "medium",
                "page": 2,
                "passage": "We prefer equities over bonds for the next twelve months as growth stays resilient.",
            },
        ]
    },
    # a fabricated quote, an out-of-taxonomy subject, a page that does not exist, and one genuine claim
    "house_view_adversarial.txt": {
        "insights": [
            {
                "subject_kind": "sector",
                "subject": "Energy",
                "direction": "positive",
                "confidence": "high",
                "page": 1,
                "passage": "Energy will double next year according to our model.",
            },
            {
                "subject_kind": "sector",
                "subject": "Energy",
                "direction": "positive",
                "confidence": "high",
                "page": 1,
                "passage": "Energy stocks are guaranteed to outperform.",
            },
            {
                "subject_kind": "sector",
                "subject": "Crypto",
                "direction": "positive",
                "confidence": "low",
                "page": 1,
                "passage": "Nothing else of note.",
            },
            {
                "subject_kind": "asset_class",
                "subject": "bond",
                "direction": "negative",
                "confidence": "low",
                "page": 9,
                "passage": "Nothing else of note.",
            },
        ]
    },
}


def _extraction_replies() -> dict[str, dict]:
    """Each fixture Report's extraction request text, mapped to its hand-authored reply."""
    replies = {}
    for name, content in CASES.items():
        _, pages = extract_pages(name, (HERE / name).read_bytes())
        replies[extraction_request(pages).user] = content
    return replies


EXTRACTION_REPLIES = _extraction_replies()  # what the demo's fake chat model answers an extraction request with
