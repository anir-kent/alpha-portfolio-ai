import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.analysis_runs import AnalysisRuns, mark_stranded_runs_interrupted
from app.exchanges import CapturingLlm, endpoint_host
from app.llm import build_llm
from app.db import User, make_session_factory
from app.rbac import ROLES
from app.routers import analysis, approvals, audit, auth, config, governance, grounding, health, llm_exchanges, portfolios, recommendations, reports
from app.security import hash_password
from app.settings import Settings


def seed_users(session_factory, password: str) -> None:
    if not password:
        raise RuntimeError("APP_SEED_USER_PASSWORD must be set (see .env.example)")
    with session_factory() as db:
        existing = set(db.scalars(select(User.username)))
        for role in ROLES:
            if role not in existing:
                db.add(User(username=role, role=role, password_hash=hash_password(password)))
        db.commit()


def create_app(settings: Settings | None = None, *, llm_transport: httpx.BaseTransport | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Alpha Portfolio AI", version="0.1.0")
    app.state.settings = settings
    app.state.session_factory = make_session_factory(settings.database_url)
    app.state.llm = CapturingLlm(
        build_llm(settings, llm_transport), app.state.session_factory, mode=settings.llm_mode, endpoint_host=endpoint_host(settings))
    # Before any run can start, a row with no outcome is from a process that died mid-run. One API process only (ADR-0005)
    mark_stranded_runs_interrupted(app.state.session_factory)
    app.state.analysis_runs = AnalysisRuns(app.state.session_factory)
    seed_users(app.state.session_factory, settings.seed_user_password)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    for r in (auth.router, analysis.router, approvals.router, audit.router, config.router, governance.router, grounding.router, health.router, llm_exchanges.router, portfolios.router, recommendations.router, reports.router):
        app.include_router(r)
    return app
