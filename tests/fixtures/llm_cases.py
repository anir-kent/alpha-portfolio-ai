"""Hand-authored LLM replies for the fixture Reports: what the demo's fake chat model (`tests.fake_chat.DemoPipeline`)
answers an Insight extraction request with. The model cites a Chunk, so `demo_reply` fills each Insight's `chunk_id` from
the Chunks the request carries: the one whose text holds the passage, else the first (so a fabricated passage is cited
to a real Chunk that does not contain it). An entry with `"chunk_id": FABRICATED` cites a Chunk that was never sent.
The case a request belongs to is the one with most passages found in its Chunks."""

FABRICATED = "00000000-0000-0000-0000-000000000000"

CASES = {
    "house_view_demo.txt": {
        "insights": [
            {
                "subject_kind": "sector",
                "subject": "Information Technology",
                "direction": "positive",
                "confidence": "high",
                "passage": "We are constructive on technology.",
            },
            {
                "subject_kind": "sector",
                "subject": "Utilities",
                "direction": "negative",
                "confidence": "medium",
                "passage": "Utilities look expensive after the rally and offer limited upside from here.",
            },
            {
                "subject_kind": "asset_class",
                "subject": "equity",
                "direction": "positive",
                "confidence": "medium",
                "passage": "We prefer equities over bonds for the next twelve months as growth stays resilient.",
            },
        ]
    },
    # a fabricated quote, an out-of-taxonomy subject, a Chunk that was never sent, and one genuine claim
    "house_view_adversarial.txt": {
        "insights": [
            {
                "subject_kind": "sector",
                "subject": "Energy",
                "direction": "positive",
                "confidence": "high",
                "passage": "Energy will double next year according to our model.",
            },
            {
                "subject_kind": "sector",
                "subject": "Energy",
                "direction": "positive",
                "confidence": "high",
                "passage": "Energy stocks are guaranteed to outperform.",
            },
            {
                "subject_kind": "sector",
                "subject": "Crypto",
                "direction": "positive",
                "confidence": "low",
                "passage": "Nothing else of note.",
            },
            {
                "subject_kind": "asset_class",
                "subject": "bond",
                "direction": "negative",
                "confidence": "low",
                "chunk_id": FABRICATED,
                "passage": "Nothing else of note.",
            },
        ]
    },
}
