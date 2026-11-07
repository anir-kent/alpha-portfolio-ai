"""Seam: the HTTP API, end to end. The scripted demo walkthrough (`scripts/walkthrough.py`) plays every planted
scenario from a fresh seed on the committed recordings, from the Queue to the Auditor's evidence; every claim it
makes must hold, AI steps included, so the demo can never silently degrade to failed AI steps."""

from scripts.walkthrough import walk


def test_the_demo_walkthrough_holds_end_to_end_from_a_fresh_seed_on_recorded_responses():
    checks = walk()
    failed = [f"{c.act}: {c.claim} [{c.evidence}]" for c in checks if not c.ok]
    assert not failed, "\n".join(failed)
    assert {c.act for c in checks} >= {"1 Queue", "7 Auditor evidence", "8 Supersession and the clean Portfolio"}
