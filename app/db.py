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
