"""Seed the research side: sample Reports, the hand-transcribed p3 scorecard and sample Insights.

No LLM is involved. Every seeded item is approved as human-verified, and the audit trail says so (payload
`human_verified: true`, actor `seed`), so an Auditor can tell it from machine-extracted, analyst-approved research.
Idempotent: a Report that already exists is skipped. Usage: uv run python -m app.research_seed
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app import audit, reports
from app.audit import Actor
from app.db import ReportRow

SEED = Actor.system("seed")
_DIRECTION = {"overweight": "positive", "neutral": "neutral", "underweight": "negative"}


def _confidence(row: dict) -> str:
    sign = 1 if row["view"] == "overweight" else -1 if row["view"] == "underweight" else 0
    net = sum(
        sign * (1 if row[k] == "+" else -1) for k in ("fundamentals", "valuations", "relative_strength") if row[k]
    )
    return "high" if net >= 2 else "medium" if net == 1 else "low"


def _scorecard_insights(path: Path) -> list[dict]:
    card = json.loads(path.read_text())
    assert card["human_verified"]
    return [
        {
            "report_id": card["report_id"],
            "subject_kind": "sector",
            "subject": r["sector"],
            "direction": _DIRECTION[r["view"]],
            "confidence": _confidence(r),
            "page": card["page"],
            "passage": r["comment"],
            "source": path.name,
        }
        for r in card["rows"]
    ]


def _seed_insight(db: Session, spec: dict, report_event: int, pages: list[str]) -> None:
    e = reports.ExtractedInsight(**{k: spec[k] for k in reports.ExtractedInsight.model_fields})
    if not reports.valid_subject(e.subject_kind, e.subject) or not reports.passage_on_page(
        e.passage, pages[e.page - 1]
    ):
        raise ValueError(f"Seed Insight does not match its Report: {spec}")
    provenance = {"human_verified": True, "source": spec.get("source", "insights.json")}
    event = audit.record(
        db,
        "insight_extracted",
        SEED,
        {"insight_count": 1, **provenance},
        parents=[report_event],
        report_id=spec["report_id"],
    )
    row = reports.add_insight(db, spec["report_id"], e, extract_event_id=event, human_verified=True)
    reports.decide(db, row, SEED, "approve", "Seed: approved as human-verified")


def seed_research(session_factory: sessionmaker, seed_dir: str = "data/seed") -> int:
    """Returns the number of Reports newly seeded."""
    base = Path(seed_dir)
    insights = json.loads((base / "insights.json").read_text()) + _scorecard_insights(base / "q2_scorecard_p3.json")
    added = 0
    with session_factory() as db:
        for spec in json.loads((base / "reports.json").read_text()):
            if db.get(ReportRow, spec["id"]):
                continue
            path = Path(spec["file"])
            kind, pages = reports.extract_pages(path.name, path.read_bytes())
            reports.store_report(
                db,
                report_id=spec["id"],
                title=spec["title"],
                filename=path.name,
                kind=kind,
                pages=pages,
                uploaded_by=SEED.name,
                human_verified=True,
                extraction_status="seeded",
            )
            event = audit.record(
                db,
                "report_ingested",
                SEED,
                {
                    "title": spec["title"],
                    "filename": path.name,
                    "kind": kind,
                    "page_count": len(pages),
                    "human_verified": True,
                },
                report_id=spec["id"],
            )
            for i in (i for i in insights if i["report_id"] == spec["id"]):
                _seed_insight(db, i, event, pages)
            added += 1
    return added


if __name__ == "__main__":
    from app.db import make_session_factory
    from app.settings import Settings

    s = Settings()
    print(f"seeded {seed_research(make_session_factory(s.database_url), s.seed_dir)} Reports into {s.database_url}")
