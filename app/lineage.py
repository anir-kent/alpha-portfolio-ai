"""Lineage of a Recommendation: its audit events plus every ancestor reachable through parent links.

Report passage -> Insight -> Research Tilt -> Recommendation -> Decision, with overrides flagged. Read-only: it
derives the view from the hash-chained audit log and never writes to it.
"""
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import AuditEventRow, InsightRow, ReportRow

STAGE_OF = {
    "report_ingested": "report",
    "insight_extracted": "insight", "insight_approved": "insight", "insight_rejected": "insight",
    "research_tilt_proposed": "research_tilt", "research_tilt_applied": "research_tilt",
    "recommendation_drafted": "recommendation", "recommendation_modified": "recommendation",
    "recommendation_superseded": "recommendation", "suitability_evaluated": "recommendation",
    "memo_generated": "recommendation", "grounding_checked": "recommendation", "claim_ungrounded": "recommendation",
    "decision_recorded": "decision", "exception_approved": "decision", "exception_blocked": "decision",
}
OVERRIDE_TYPES = {"recommendation_modified", "exception_approved"}


@dataclass
class Node:
    event: AuditEventRow
    stage: str
    payload: dict
    override: bool
    human_verified: bool
    source: dict | None = None
    parent_ids: list[int] = field(default_factory=list)


def _is_override(type: str, payload: dict) -> bool:
    return type in OVERRIDE_TYPES or (type == "decision_recorded" and payload.get("action") == "modify")


def lineage(db: Session, recommendation_id: int) -> list[Node]:
    """Oldest-first nodes. Empty when the Recommendation has no audit events."""
    seen: dict[int, AuditEventRow] = {}
    frontier = list(db.scalars(select(AuditEventRow).where(AuditEventRow.recommendation_id == str(recommendation_id))))
    while frontier:
        fresh = [e for e in frontier if e.id not in seen]
        seen.update({e.id: e for e in fresh})
        want = {p for e in fresh for p in json.loads(e.parent_ids_json)} - seen.keys()
        frontier = list(db.scalars(select(AuditEventRow).where(AuditEventRow.id.in_(want)))) if want else []

    insight_ids = {json.loads(e.payload_json).get("insight_id") for e in seen.values() if e.type == "insight_approved"}
    insights = {i.id: i for i in db.scalars(select(InsightRow).where(InsightRow.id.in_(insight_ids - {None})))}
    titles = {r.id: r.title for r in db.scalars(select(ReportRow).where(ReportRow.id.in_({e.report_id for e in seen.values() if e.report_id})))}

    nodes = []
    for e in sorted(seen.values(), key=lambda e: e.id):
        payload = json.loads(e.payload_json)
        ins = insights.get(payload.get("insight_id")) if e.type == "insight_approved" else None
        source = (
            {"report_id": ins.report_id, "report_title": titles.get(ins.report_id), "page": ins.page, "passage": ins.passage}
            if ins else None
        )
        nodes.append(Node(
            e, STAGE_OF.get(e.type, "analysis"), payload, _is_override(e.type, payload),
            payload.get("human_verified") is True, source, json.loads(e.parent_ids_json),
        ))
    return nodes
