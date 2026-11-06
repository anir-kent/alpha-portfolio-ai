from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import grounding
from app.db import RecommendationRow, User
from app.deps import get_db, require

router = APIRouter(prefix="/api", tags=["grounding"])


class GroundingIn(BaseModel):
    claims: list[grounding.Claim]


class ClaimResultOut(grounding.ClaimResult):
    memo_eligible: bool  # only grounded claims may appear in a memo


class SummaryOut(BaseModel):
    total: int
    grounded: int
    ungrounded: int


class GroundingOut(BaseModel):
    recommendation_id: int
    check_id: str | None
    results: list[ClaimResultOut]  # every claim, flagged ones included: the Advisor sees them
    summary: SummaryOut


def _out(rec_id: int, check_id: str | None, results: list[grounding.ClaimResult]) -> GroundingOut:
    return GroundingOut(
        recommendation_id=rec_id,
        check_id=check_id,
        summary=SummaryOut(**grounding.summarise(results)),
        results=[ClaimResultOut(**r.model_dump(), memo_eligible=r.grounded) for r in results],
    )


def _rec(db: Session, recommendation_id: int) -> RecommendationRow:
    rec = db.get(RecommendationRow, recommendation_id)
    if rec is None:
        raise HTTPException(404, "Recommendation not found")
    return rec


@router.post(
    "/recommendations/{recommendation_id}/grounding", response_model=GroundingOut, operation_id="validateClaims"
)
def validate_claims(
    recommendation_id: int,
    body: GroundingIn,
    user: User = Depends(require("grounding:validate")),
    db: Session = Depends(get_db),
):
    rec = _rec(db, recommendation_id)
    check_id, results = grounding.validate(db, rec, body.claims)
    return _out(rec.id, check_id, results)


@router.get("/recommendations/{recommendation_id}/grounding", response_model=GroundingOut, operation_id="getGrounding")
def get_grounding(
    recommendation_id: int, user: User = Depends(require("grounding:read")), db: Session = Depends(get_db)
):
    rec = _rec(db, recommendation_id)
    return _out(rec.id, None, grounding.latest_results(db, rec.id))
