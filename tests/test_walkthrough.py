"""Seam: the HTTP API, end to end. The scripted demo walkthrough (`scripts/walkthrough.py`) plays every planted
scenario from a fresh seed on a fake chat model, from the Queue to the Auditor's evidence; every claim it makes must
hold, AI steps included, so the demo can never silently degrade to failed AI steps."""

from scripts.walkthrough import walk
from tests.fake_chat import DemoPipeline


def test_the_demo_walkthrough_holds_end_to_end_from_a_fresh_seed_on_a_fake_chat_model():
    checks = walk(DemoPipeline())
    failed = [f"{c.act}: {c.claim} [{c.evidence}]" for c in checks if not c.ok]
    assert not failed, "\n".join(failed)
    assert {c.act for c in checks} >= {"1 Queue", "7 Auditor evidence", "8 Supersession and the clean Portfolio"}
