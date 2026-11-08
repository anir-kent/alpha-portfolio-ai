from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Engine, ForeignKey, String, Text, UniqueConstraint, create_engine, inspect, text
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
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class LlmExchangeRow(Base):
    """One request and reply through the LLM interface (ADR-0004). Append-only: written once, never updated or deleted.
    `hash` is a SHA-256 over the content fields (everything but `id`); the calling step's Audit Event references it.
    `trajectory_id` and `trajectory_position` place the request in its LLM Trajectory (ADR-0010); both are None on rows written
    before Trajectories existed, each of which is a Trajectory of one."""

    __tablename__ = "llm_exchanges"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String, index=True)
    task: Mapped[str] = mapped_column(String, index=True)
    prompt_version: Mapped[str] = mapped_column(String, index=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    mode: Mapped[str] = mapped_column(String, index=True)  # live | recorded
    endpoint_host: Mapped[str | None] = mapped_column(String, nullable=True)
    system_text: Mapped[str] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text)
    reply_schema_json: Mapped[str] = mapped_column(Text)
    messages_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # exactly what was sent (live only)
    raw_reply: Mapped[str | None] = mapped_column(Text, nullable=True)  # before parsing (live only)
    parsed_content_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    outcome: Mapped[str] = mapped_column(String, index=True)  # ok | error (transport only)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trajectory_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    trajectory_position: Mapped[int | None] = mapped_column(nullable=True)  # 0-based within the Trajectory
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
    completed: Mapped[bool] = mapped_column(default=False)  # results recorded: only completed runs can be current
    # completed | completed_with_warnings | failed | interrupted; null while the run is in flight (ADR-0005)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    steps_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # the Run Step results, saved when the run ends


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
    status: Mapped[str] = mapped_column(
        String, index=True
    )  # pending_advisor | pending_compliance | pending_committee | approved | rejected | superseded
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
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_runs.id"), index=True, nullable=True
    )  # a priority narrative's claims
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("clients.id"), index=True, nullable=True
    )  # None when the figure set spans Clients (the Queue)
    subject_kind: Mapped[str | None] = mapped_column(String, nullable=True)  # any other subject, e.g. assistant_turn
    subject_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    claim_index: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    asset: Mapped[str | None] = mapped_column(String, nullable=True)
    citations_json: Mapped[str] = mapped_column(Text)
    grounded: Mapped[bool] = mapped_column(index=True)
    issues_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, index=True)


class FixtureRunRow(Base):
    """One run of the adversarial grounding fixtures: what each fixture was expected to trigger and what the validator did."""

    __tablename__ = "fixture_runs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ran_at: Mapped[str] = mapped_column(String, index=True)
    ran_by: Mapped[str] = mapped_column(String)
    results_json: Mapped[str] = mapped_column(Text)


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
    entries_json: Mapped[str] = mapped_column(
        Text
    )  # [{subject_kind, subject, exposure_pct, proposed_pp, allowed_pp, clipped, reason, insight_ids}]
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


class ConversationRow(Base):
    """One user's Assistant Conversation within one login session (ADR-0006). It ends at logout or session expiry and
    is never resumed; `session_token_hash` names the server-side session row it belongs to."""

    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_token_hash: Mapped[str] = mapped_column(String, index=True)
    started_at: Mapped[str] = mapped_column(String)
    ended_at: Mapped[str | None] = mapped_column(String, nullable=True)


class AssistantTurnRow(Base):
    """One Question and its outcome (ADR-0006). Append-only: written once, never updated or deleted."""

    __tablename__ = "assistant_turns"
    __table_args__ = (UniqueConstraint("conversation_id", "seq"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    seq: Mapped[int] = mapped_column()  # 1-based within the Conversation
    created_at: Mapped[str] = mapped_column(String)
    question: Mapped[str] = mapped_column(Text)
    screen_json: Mapped[str] = mapped_column(Text)  # the screen identity the browser sent
    screen_context_hash: Mapped[str | None] = mapped_column(String, nullable=True)  # None when nothing was readable
    outcome: Mapped[str] = mapped_column(String, index=True)  # answered | refused | failed
    answer_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    grounding_check_id: Mapped[str | None] = mapped_column(String, nullable=True)
    exchange_id: Mapped[int | None] = mapped_column(nullable=True)
    exchange_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)  # a failed turn's reason, else None


def make_session_factory(url: str) -> sessionmaker:
    kwargs: dict[str, Any] = {}
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
    _add_run_outcome_columns(engine)
    _generalise_grounding_results(engine)
    _add_turn_failure_reason(engine)
    _add_exchange_trajectory(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _add_run_outcome_columns(engine) -> None:
    """An existing database predates the Analysis Run outcome columns: add them, and mark its completed runs completed."""
    existing = {c["name"] for c in inspect(engine).get_columns("analysis_runs")}
    if "outcome" in existing:
        return
    with engine.begin() as conn:
        for name, kind in (("outcome", "VARCHAR"), ("finished_at", "VARCHAR"), ("steps_json", "TEXT")):
            if name not in existing:
                conn.execute(text(f"ALTER TABLE analysis_runs ADD COLUMN {name} {kind}"))
        conn.execute(text("UPDATE analysis_runs SET outcome = 'completed' WHERE completed"))


def _add_turn_failure_reason(engine: Engine) -> None:
    """An existing database predates stored failure reasons: afterwards the column exists, empty for older turns (which
    then show the ordinary failure message)."""
    with engine.begin() as conn:
        if "failure_reason" not in {c["name"] for c in inspect(conn).get_columns("assistant_turns")}:
            conn.execute(text("ALTER TABLE assistant_turns ADD COLUMN failure_reason VARCHAR"))


def _add_exchange_trajectory(engine: Engine) -> None:
    """An existing database predates LLM Trajectories: afterwards every Exchange has a `trajectory_id` and `trajectory_position`
    column, empty for older rows, whose stored hashes stay valid because the digest leaves empty ones out."""
    with engine.begin() as conn:
        existing = {c["name"] for c in inspect(conn).get_columns("llm_exchanges")}
        for name, kind in (("trajectory_id", "VARCHAR"), ("trajectory_position", "INTEGER")):
            if name not in existing:
                conn.execute(text(f"ALTER TABLE llm_exchanges ADD COLUMN {name} {kind}"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_llm_exchanges_trajectory_id ON llm_exchanges (trajectory_id)"))


def _generalise_grounding_results(engine: Engine) -> None:
    """An existing database predates checks tied to no Client: afterwards `client_id` is optional and the subject
    columns exist, with every stored grounding result kept."""
    existing = [c["name"] for c in inspect(engine).get_columns("grounding_results")]
    if "subject_kind" in existing:
        return
    table = Base.metadata.tables["grounding_results"]
    with engine.begin() as conn:  # SQLite cannot drop NOT NULL in place: rebuild the table and copy the rows across
        conn.execute(text("ALTER TABLE grounding_results RENAME TO grounding_results_old"))
        for index in inspect(conn).get_indexes("grounding_results_old"):  # names would clash with the new table's
            conn.execute(text(f'DROP INDEX "{index["name"]}"'))
        table.create(conn)
        columns = ", ".join(existing)
        conn.execute(text(f"INSERT INTO grounding_results ({columns}) SELECT {columns} FROM grounding_results_old"))
        conn.execute(text("DROP TABLE grounding_results_old"))
