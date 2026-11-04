from sqlalchemy import DateTime, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    role: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True))


class ConfigRow(Base):
    __tablename__ = "config"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)


class AuditEventRow(Base):
    """Append-only, hash-chained audit event (ADR-0002). Never updated or deleted."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String, index=True)
    actor_kind: Mapped[str] = mapped_column(String)
    actor_name: Mapped[str] = mapped_column(String, index=True)
    actor_role: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[str] = mapped_column(String, index=True)  # fixed-format UTC ISO, hashed as stored
    payload_json: Mapped[str] = mapped_column(Text)
    parent_ids_json: Mapped[str] = mapped_column(Text)
    portfolio_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    client_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    recommendation_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    report_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    previous_hash: Mapped[str] = mapped_column(String, unique=True)  # one successor per link
    hash: Mapped[str] = mapped_column(String)


class ClientRow(Base):
    """Synthetic Client (ADR-0003). name and email are the sensitive fields masked by role."""

    __tablename__ = "clients"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    risk_profile: Mapped[str] = mapped_column(String, index=True)
    objective: Mapped[str] = mapped_column(String)
    horizon_years: Mapped[int] = mapped_column()
    liquidity_needs_pct: Mapped[float] = mapped_column()
    review_due: Mapped[str] = mapped_column(String)  # ISO date


class AccountRow(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    tax_status: Mapped[str] = mapped_column(String)  # taxable | tax_advantaged


class HoldingRow(Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column()
    cost_basis_per_unit: Mapped[float] = mapped_column()


class TargetRow(Base):
    """Target Allocation: intended weight (0-1) of one Asset Class for one Client."""

    __tablename__ = "target_allocations"
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), primary_key=True)
    asset_class: Mapped[str] = mapped_column(String, primary_key=True)
    weight: Mapped[float] = mapped_column()


class RestrictionRow(Base):
    __tablename__ = "restrictions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # instrument | sector
    value: Mapped[str] = mapped_column(String)


class AnalysisRunRow(Base):
    """One on-demand analysis run. The highest id is the current run; earlier runs are superseded."""

    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_at: Mapped[str] = mapped_column(String)
    actor_name: Mapped[str] = mapped_column(String)
    as_of: Mapped[str] = mapped_column(String)  # review-due and urgency are measured at this date
    config_json: Mapped[str] = mapped_column(Text)  # config in force for this run
    completed: Mapped[bool] = mapped_column(default=False)  # only completed runs are current


class PriorityResultRow(Base):
    __tablename__ = "priority_results"
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), primary_key=True)
    score: Mapped[float] = mapped_column(index=True)
    label: Mapped[str] = mapped_column(String, index=True)
    risk_profile: Mapped[str] = mapped_column(String, index=True)
    review_due: Mapped[str] = mapped_column(String, index=True)
    days_past_due: Mapped[int] = mapped_column()
    sla_breached: Mapped[bool] = mapped_column()
    portfolio_drift_pp: Mapped[float] = mapped_column()
    total_value: Mapped[float] = mapped_column()
    components_json: Mapped[str] = mapped_column(Text)
    drift_json: Mapped[str] = mapped_column(Text)


class SuitabilityResultRow(Base):
    """Suitability Rule results for one Portfolio in one analysis run."""

    __tablename__ = "suitability_results"
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String, index=True)  # worst rule status
    results_json: Mapped[str] = mapped_column(Text)


class RecommendationRow(Base):
    """One version of a Recommendation. A modification adds a new row linked by parent_id; versions are never edited
    except for their status."""

    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    root_id: Mapped[int] = mapped_column(index=True)  # id of version 1
    parent_id: Mapped[int | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column()
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"))
    status: Mapped[str] = mapped_column(String, index=True)  # pending_advisor | pending_compliance | pending_committee | approved | rejected | superseded
    created_at: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    total_value: Mapped[float] = mapped_column()
    turnover_pct: Mapped[float] = mapped_column()
    trade_lines_json: Mapped[str] = mapped_column(Text)
    suitability_status: Mapped[str] = mapped_column(String)  # worst post-trade rule status
    suitability_json: Mapped[str] = mapped_column(Text)
    post_trade_drift_json: Mapped[str] = mapped_column(Text)


class DecisionRow(Base):
    """A human's accept, modify or reject of one Recommendation version, with rationale."""

    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    action: Mapped[str] = mapped_column(String)  # accept | reject | modify
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_name: Mapped[str] = mapped_column(String)
    actor_role: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    resulting_status: Mapped[str] = mapped_column(String)
    resulting_recommendation_id: Mapped[int | None] = mapped_column(nullable=True)  # the new version, on modify


class ReportRow(Base):
    """A source document. Pages are stored so Insight citations can be checked and shown."""

    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # pdf | text
    uploaded_by: Mapped[str] = mapped_column(String)
    uploaded_at: Mapped[str] = mapped_column(String)
    page_count: Mapped[int] = mapped_column()
    human_verified: Mapped[bool] = mapped_column(default=False)  # seeded, not machine-extracted
    extraction_status: Mapped[str] = mapped_column(String)  # complete | failed | seeded
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReportPageRow(Base):
    __tablename__ = "report_pages"
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), primary_key=True)
    page: Mapped[int] = mapped_column(primary_key=True)  # 1-based
    text: Mapped[str] = mapped_column(Text)


class InsightRow(Base):
    """A cited claim from a Report. Pending until a Research Analyst approves; only approved ones are usable."""

    __tablename__ = "insights"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    subject_kind: Mapped[str] = mapped_column(String)  # sector | asset_class
    subject: Mapped[str] = mapped_column(String, index=True)
    direction: Mapped[str] = mapped_column(String)  # positive | neutral | negative
    confidence: Mapped[str] = mapped_column(String)  # low | medium | high
    page: Mapped[int] = mapped_column()
    passage: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, index=True)  # pending | approved | rejected
    human_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(String)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    extract_event_id: Mapped[int] = mapped_column()  # the audit event that produced it


class GroundingResultRow(Base):
    """One claim's grounding verdict. Kept per claim so the AI quality panel can aggregate pass rates and flag reasons."""

    __tablename__ = "grounding_results"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    check_id: Mapped[str] = mapped_column(String, index=True)  # one validation call
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendations.id"), index=True, nullable=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id"), index=True, nullable=True)  # a priority narrative's claims
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    claim_index: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    asset: Mapped[str | None] = mapped_column(String, nullable=True)
    citations_json: Mapped[str] = mapped_column(Text)
    grounded: Mapped[bool] = mapped_column(index=True)
    issues_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, index=True)


class RecommendationTiltRow(Base):
    """The Research Tilt attempt for one Recommendation: what the LLM proposed and what the engine allowed, per subject
    (sector or Asset Class), or that the attempt failed and the plain rule-based Recommendation stands."""

    __tablename__ = "recommendation_tilts"
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String)  # ok | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    bound_pp: Mapped[float] = mapped_column()  # the bound in force when clipped
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str] = mapped_column(String)
    entries_json: Mapped[str] = mapped_column(Text)  # [{subject_kind, subject, exposure_pct, proposed_pp, allowed_pp, clipped, reason, insight_ids}]
    dropped_json: Mapped[str] = mapped_column(Text)


class RecommendationNarrativeRow(Base):
    """The generated advisor memo for one Recommendation; its claims and flags are GroundingResultRows of `check_id`."""

    __tablename__ = "recommendation_narratives"
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String)  # complete | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_id: Mapped[str | None] = mapped_column(String, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)


class PriorityNarrativeRow(Base):
    """The "why this client, why now" narrative for one queue row; its claims and flags are GroundingResultRows of `check_id`."""

    __tablename__ = "priority_narratives"
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String)  # complete | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_id: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # built by the engine from grounded claims only
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)


def make_session_factory(url: str) -> sessionmaker:
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        else:
            path = url.removeprefix("sqlite:///")
            import os

            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
