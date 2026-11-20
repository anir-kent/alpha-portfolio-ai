"""Seam: Report ingestion, Insight approval and the LLM interface. Insight extraction runs the extraction LLM Graph
(retrieve, then one generate call) over a Report Index on fake embeddings, on a fake chat model that answers from the
hand-authored cases (tests/fixtures/llm_cases.py) unless a test scripts it; a live smoke test runs only with LLM_LIVE=1,
and the PDF test only with DOCLING_MODELS=1 (Docling's PDF pipeline downloads layout models)."""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app import audit
from app.db import AuditEventRow
from app.research_seed import seed_research
from tests.conftest import ROLES
from tests.fake_chat import FakeChatModel, serve_chat

FIXTURES = Path(__file__).parent / "fixtures"


def upload(c, name="house_view_demo.txt", content=None, **params):
    content = (FIXTURES / name).read_bytes() if content is None else content
    return c.post("/api/reports", files={"file": (name, content)}, params=params)


def events(app, **where):
    with app.state.session_factory() as db:
        return [
            r
            for r in db.scalars(select(AuditEventRow).order_by(AuditEventRow.id))
            if all(getattr(r, k) == v for k, v in where.items())
        ]


def minimal_pdf(pages: list[str]) -> bytes:
    """A tiny valid PDF with one line of text per page."""
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(len(pages)))}] /Count {len(pages)} >>",
    ]
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET"
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>"
        )
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


# --- ingestion -------------------------------------------------------------------------------------------------


def test_upload_produces_pending_cited_insights(login):
    r = upload(login("research_analyst"), title="Demo view")
    assert r.status_code == 201, r.text
    report = r.json()
    assert report["title"] == "Demo view" and report["page_count"] == 1 and report["extraction_status"] == "complete"
    by_subject = {i["subject"]: i for i in report["insights"]}
    assert set(by_subject) == {"Information Technology", "Utilities", "equity"}
    tech = by_subject["Information Technology"]
    assert (tech["status"], tech["direction"], tech["confidence"], tech["page"]) == ("pending", "positive", "high", 1)
    assert tech["passage"] == "We are constructive on technology."
    assert by_subject["equity"]["page"] == 1 and by_subject["equity"]["subject_kind"] == "asset_class"
    assert all(i["chunk_id"] for i in report["insights"])
    assert not any(i["human_verified"] for i in report["insights"])


@pytest.mark.skipif(not os.environ.get("DOCLING_MODELS"), reason="downloads Docling's PDF models: set DOCLING_MODELS=1")
def test_pdf_upload_keeps_page_references(login, allow_network):
    pdf = minimal_pdf(
        ["Report cover.", "We prefer equities over bonds for the next twelve months as growth stays resilient."]
    )
    r = upload(login("research_analyst"), "pdf_view.pdf", pdf)
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "pdf" and r.json()["page_count"] == 2
    # a paragraph with no closing punctuation would be joined to the next page's text: Docling's own behaviour
    page = login("advisor").get(f"/api/reports/{r.json()['id']}/pages/2")
    assert "We prefer equities over bonds" in page.json()["text"]
    assert [i["page"] for i in r.json()["insights"]] == [2]


def cite_first_chunk(request):
    """A scripted reply: one Insight quoting the technology passage, cited to the first Chunk sent."""
    chunk_id = request.user_prompt.split("[Chunk ", 1)[1][:36]
    return {
        "insights": [
            {
                "subject_kind": "sector",
                "subject": "Information Technology",
                "direction": "positive",
                "confidence": "high",
                "chunk_id": chunk_id,
                "passage": "We are constructive on technology.",
            }
        ]
    }


@pytest.mark.skipif(not os.environ.get("DOCLING_MODELS"), reason="runs Docling's OCR models: set DOCLING_MODELS=1")
def test_image_upload_is_read_by_ocr(login, allow_network):
    r = upload(login("research_analyst"), "house_view_scan.png")
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "image" and r.json()["page_count"] == 1
    text = login("advisor").get(f"/api/reports/{r.json()['id']}/pages/1").json()["text"]
    assert "constructive on technology" in text


def test_upload_runs_insight_extraction_off_the_event_loop(app, login):
    model = serve_chat(app, FakeChatModel(cite_first_chunk))
    r = upload(login("research_analyst"))
    assert r.status_code == 201, r.text
    assert len(model.requests) == 1 and r.json()["extraction_status"] == "complete" and len(r.json()["insights"]) == 1
    assert r.json()["insights"][0]["passage"] == "We are constructive on technology."


def test_every_llm_call_logs_model_and_prompt_version_to_the_audit_chain(app, login):
    report = upload(login("research_analyst")).json()
    ingested, extracted = events(app, report_id=report["id"])
    assert (ingested.type, ingested.actor_role) == ("report_ingested", "research_analyst")
    assert extracted.type == "insight_extracted" and extracted.actor_kind == "system"
    assert (extracted.model, extracted.prompt_version) == ("demo-model", "insight_extraction@v2")
    assert json.loads(extracted.parent_ids_json) == [ingested.id]
    with app.state.session_factory() as db:
        assert audit.verify(db).valid


def test_insights_failing_citation_or_taxonomy_checks_are_dropped_and_recorded(app, login):
    report = upload(login("research_analyst"), "house_view_adversarial.txt").json()
    assert [i["passage"] for i in report["insights"]] == ["Energy will double next year according to our model."]
    payload = json.loads(events(app, report_id=report["id"], type="insight_extracted")[0].payload_json)
    assert {d["reason"] for d in payload["dropped"]} == {
        "passage not found in cited chunk",
        "subject not in taxonomy",
        "cited chunk was not among the chunks sent",
    }


def test_report_whose_extraction_fails_is_stored_with_failed_extraction(login):
    r = upload(login("research_analyst"), content=b"A report the demo model has no reply for.\n")
    assert r.status_code == 201
    assert r.json()["extraction_status"] == "failed" and r.json()["insights"] == []
    assert "no reply for this Report" in r.json()["extraction_error"]


@pytest.mark.parametrize(
    "name,content",
    [
        ("notes.docx", b"hello"),
        ("empty.txt", b"  \n"),
        ("broken.pdf", b"not a pdf"),
        ("bin.txt", b"\xff\xfe\x00"),
    ],
)
def test_unusable_uploads_are_rejected(login, name, content):
    assert upload(login("research_analyst"), name, content).status_code == 422


# --- approval gate ---------------------------------------------------------------------------------------------


def test_only_approved_insights_are_retrievable_for_use(app, login):
    analyst, advisor = login("research_analyst"), login("advisor")
    insights = upload(analyst).json()["insights"]
    assert advisor.get("/api/insights").json()["items"] == []
    tech, utilities = (next(i for i in insights if i["subject"] == s) for s in ("Information Technology", "Utilities"))

    approved = analyst.post(f"/api/insights/{tech['id']}/decision", json={"action": "approve", "note": "checked p1"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert approved.json()["decided_by"] == "research_analyst"
    assert (
        analyst.post(f"/api/insights/{utilities['id']}/decision", json={"action": "reject"}).json()["status"]
        == "rejected"
    )

    visible = advisor.get("/api/insights").json()["items"]
    assert [i["subject"] for i in visible] == ["Information Technology"]
    assert visible[0]["page"] == 1 and visible[0]["passage"] and visible[0]["chunk_id"]
    assert advisor.get("/api/insights", params={"subject": "Utilities"}).json()["items"] == []

    types = [e.type for e in events(app, report_id=tech["report_id"])]
    assert types == ["report_ingested", "insight_extracted", "insight_approved", "insight_rejected"]
    approval = events(app, type="insight_approved")[0]
    assert approval.actor_role == "research_analyst" and json.loads(approval.payload_json)["human_verified"] is False


def test_a_decided_insight_cannot_be_decided_again(login):
    analyst = login("research_analyst")
    i = upload(analyst).json()["insights"][0]["id"]
    assert analyst.post(f"/api/insights/{i}/decision", json={"action": "reject"}).status_code == 200
    assert analyst.post(f"/api/insights/{i}/decision", json={"action": "approve"}).status_code == 409
    assert analyst.post("/api/insights/9999/decision", json={"action": "approve"}).status_code == 404


# --- roles -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [r for r in ROLES if r != "research_analyst"])
def test_other_roles_cannot_upload_or_approve_and_are_audited(app, login, role):
    analyst = login("research_analyst")
    i = upload(analyst).json()["insights"][0]["id"]
    c = login(role)
    assert upload(c).status_code == 403
    assert c.post(f"/api/insights/{i}/decision", json={"action": "approve"}).status_code == 403
    denied = events(app, type="access_denied", actor_name=role)
    assert {json.loads(e.payload_json)["permission"] for e in denied} == {"report:upload", "insight:approve"}
    assert analyst.get(f"/api/reports/{upload(analyst).json()['id']}").json()["insights"][0]["status"] == "pending"


@pytest.mark.parametrize(
    "role,allowed",
    [
        ("advisor", True),
        ("relationship_manager", True),
        ("auditor", True),
        ("research_analyst", True),
        ("platform_owner", False),
        ("investment_committee", False),
    ],
)
def test_reading_approved_insights_by_role(login, role, allowed):
    assert (login(role).get("/api/insights").status_code == 200) is allowed


# --- seeds -----------------------------------------------------------------------------------------------------


@pytest.fixture
def seeded_research(app):
    assert seed_research(app.state.session_factory) == 5
    return app


def test_seeded_insights_are_approved_cited_and_marked_human_verified(seeded_research, login):
    advisor = login("advisor")
    items = advisor.get("/api/insights").json()["items"]
    assert len(items) >= 15 and all(i["status"] == "approved" and i["human_verified"] for i in items)
    sectors = {i["subject"]: i["direction"] for i in items if i["report_id"] == "RPT-FID-Q2-2026"}
    assert len(sectors) == 11
    assert sectors["Information Technology"] == "positive" and sectors["Utilities"] == "negative"
    assert sectors["Health Care"] == "neutral"
    for i in items:  # every citation resolves to a real quote on the cited page
        page = advisor.get(f"/api/reports/{i['report_id']}/pages/{i['page']}").json()["text"]
        assert " ".join(i["passage"].split()) in " ".join(page.split()).replace("- ", "-")


def test_seeded_items_are_human_verified_in_the_audit_trail(seeded_research):
    with seeded_research.state.session_factory() as db:
        assert audit.verify(db).valid
    seeded = events(seeded_research, type="insight_approved")
    assert seeded and all(e.actor_name == "seed" and json.loads(e.payload_json)["human_verified"] for e in seeded)
    assert all(json.loads(e.payload_json)["human_verified"] for e in events(seeded_research, type="report_ingested"))


def test_seeding_twice_adds_nothing(seeded_research):
    before = len(events(seeded_research))
    assert seed_research(seeded_research.state.session_factory) == 0
    assert len(events(seeded_research)) == before


@pytest.mark.skipif(not os.environ.get("LLM_LIVE"), reason="live smoke test: set LLM_LIVE=1 and APP_LLM_API_KEY")
def test_live_smoke_extraction(tmp_path, allow_network, monkeypatch):
    from app import extraction
    from app.audit import Actor
    from app.chat_model import get_chat_model
    from app.db import make_session_factory
    from app.exchanges import build_llm
    from app.report_index import ReportIndex
    from app.settings import Settings

    monkeypatch.undo()  # the offline doubles: this test calls the real embedding endpoint and tokenizer
    s = Settings(vector_store="memory")
    store = make_session_factory(f"sqlite:///{tmp_path / 'smoke.db'}")
    llm = build_llm(s, store, chat_model=get_chat_model(s))
    with store() as db:
        _, insights = extraction.ingest(
            db,
            llm,
            ReportIndex(s),
            title="v",
            filename="v.md",
            content=(FIXTURES / "house_view_demo.md").read_bytes(),
            uploader=Actor.system("smoke"),
        )
    assert insights
