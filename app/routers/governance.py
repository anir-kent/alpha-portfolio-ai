from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit, governance
from app.db import User
from app.deps import get_db, require

router = APIRouter(prefix="/api/governance", tags=["governance"])


class GovernanceOut(BaseModel):
    model_card: governance.ModelCard
    prompt_log: list[governance.PromptUse]
    quality: governance.Quality
    capture_health: governance.CaptureHealth
    fixtures: governance.FixtureRun | None  # latest run of the adversarial fixtures; None until one has been run


@router.get("", response_model=GovernanceOut, operation_id="getGovernance")
def get_governance(request: Request, user: User = Depends(require("governance:read")), db: Session = Depends(get_db)):
    return GovernanceOut(
        model_card=governance.model_card(db, request.app.state.settings), prompt_log=governance.prompt_log(db),
        quality=governance.quality(db), capture_health=governance.capture_health(db), fixtures=governance.latest_run(db),
    )


@router.post("/fixtures/run", response_model=governance.FixtureRun, operation_id="runAdversarialFixtures")
def run_fixtures(user: User = Depends(require("governance:run")), db: Session = Depends(get_db)):
    return governance.record_run(db, audit.Actor.user(user.username, user.role))
