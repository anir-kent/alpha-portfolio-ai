"""Read-only Assistant Agent and its safe, persisted per-turn Trajectory (ADR-0010)."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast

from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput, RunContext, StructuredDict, UsageLimits
from pydantic_ai.models import Model
from sqlalchemy.orm import Session

from app import screen_context
from app.db import LlmExchangeRow, User
from app.llm import LlmRequest, wire_schema
from app.market_data import MarketData
from app.routers.analysis import QueueFilters
from app.screen_context import AuditFilters, ScreenContext, ScreenIdentity, ScreenKind
from app.settings import Settings

REQUEST_LIMIT = 6
NOT_PERMITTED = "not found or not permitted for your role"


class TrajectoryStep(BaseModel):
    kind: Literal["model_request", "tool_call"]
    name: str | None = None
    arguments: dict[str, str] | None = None
    result_summary: str | None = None


class Trajectory(BaseModel):
    steps: list[TrajectoryStep]
    requests_used: int
    request_limit: int
    input_tokens: int
    output_tokens: int


@dataclass
class AssistantDeps:
    user: User
    db: Session
    market: MarketData
    settings: Settings
    figures: dict[str, float]
    exchanges: list[LlmExchangeRow]
    tool_steps: list[tuple[int, TrajectoryStep]] = field(default_factory=list)

    def summary(self) -> Trajectory:
        steps = []
        input_tokens = output_tokens = 0
        for n, row in enumerate(self.exchanges, start=1):
            steps.append(TrajectoryStep(kind="model_request"))
            steps.extend(step for after, step in self.tool_steps if after == n)
            usage = json.loads(row.usage_json or "{}")
            input_tokens += usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
            output_tokens += usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        return Trajectory(
            steps=steps,
            requests_used=len(self.exchanges),
            request_limit=REQUEST_LIMIT,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _record(deps: AssistantDeps, name: str, arguments: dict[str, str], summary: str) -> None:
    """A tool call's step, placed after the model request that made it."""
    step = TrajectoryStep(kind="tool_call", name=name, arguments=arguments, result_summary=summary)
    deps.tool_steps.append((len(deps.exchanges), step))


def _arguments(filters: BaseModel | None) -> dict[str, str]:
    """The filters the model gave, as the screen's query string would carry them."""
    given = filters.model_dump(mode="json", exclude_unset=True, exclude_none=True) if filters else {}
    return {key: json.dumps(value) if isinstance(value, bool) else str(value) for key, value in given.items()}


def _screen(
    deps: AssistantDeps, kind: ScreenKind, entity_ids: dict[str, str], prefix: str = ""
) -> ScreenContext | None:
    """The Screen Context of `kind` as the asking user would see it, its figures named with `prefix`."""
    screen = ScreenIdentity(kind=kind, entity_ids=entity_ids)
    return screen_context.build(deps.db, deps.market, deps.user, screen, deps.settings, figure_prefix=prefix)


def _result(
    deps: AssistantDeps,
    name: str,
    arguments: dict[str, str],
    context: ScreenContext | None,
    summarise: Callable[[dict], str],
) -> str:
    """What the tool returns: the serialised, fenced context, whose figures join the turn's citable set. A screen the
    user may not open and an entity that does not exist give the same result."""
    if context is None:
        _record(deps, name, arguments, NOT_PERMITTED)
        return NOT_PERMITTED
    deps.figures.update(context.figures)
    data, _ = json.JSONDecoder().raw_decode(context.text)  # fenced passages may follow the JSON
    _record(deps, name, arguments, summarise(data))
    return context.text


def _next_lookup_prefix(deps: AssistantDeps) -> str:
    """Filtered views differ in their totals, so each such lookup names its figures by its place in the turn."""
    return f"lookup.{len(deps.tool_steps) + 1}."


def _counted(screen: str, total: int, shown: int, noun: str) -> str:
    return f"{screen}: {total} {noun}" + (f", showing {shown}" if shown < total else "")


async def look_up_queue(ctx: RunContext[AssistantDeps], filters: QueueFilters | None = None) -> str:
    """Look up the prioritised Queue as the Queue screen shows it, optionally filtered and sorted like that screen.
    Figures are named `lookup.<n>.queue...`, where n is this lookup's place in the turn."""

    def summarise(data: dict) -> str:
        if not isinstance(data["rows"], list):
            return "queue: no completed Analysis Run"
        return _counted("queue", data["total_rows"], len(data["rows"]), "rows")

    deps, arguments = ctx.deps, _arguments(filters)
    context = _screen(deps, "queue", arguments, _next_lookup_prefix(deps))
    return _result(deps, "look_up_queue", arguments, context, summarise)


async def look_up_portfolio(ctx: RunContext[AssistantDeps], portfolio_id: str) -> str:
    """Look up a Portfolio's permission-checked, PII-free Screen Context and citable engine figures."""

    def summarise(data: dict) -> str:
        summary = f"Portfolio {portfolio_id}: {len(data['holdings'])} holdings"
        drift = data["portfolio_drift_pp"]
        return summary + (f", drift {drift} pp" if drift is not None else "")

    deps, arguments = ctx.deps, {"portfolio_id": portfolio_id}
    context = _screen(deps, "portfolio", arguments, f"portfolio.{portfolio_id}.")
    return _result(deps, "look_up_portfolio", arguments, context, summarise)


async def look_up_recommendation(ctx: RunContext[AssistantDeps], recommendation_id: str) -> str:
    """Look up one Recommendation's rationale as its screen shows it: Trade Lines, post-trade Suitability, the
    Research Tilt with its Report passages (for roles that may read Insights) and grounded Claims. Figures are named
    `portfolio.<Portfolio>.recommendation.<Recommendation>...`."""

    def summarise(data: dict) -> str:
        lines = len(data["trade_lines"])
        breaches = sum(rule["status"] == "breach" for rule in data["post_trade_suitability"]["rules"])
        return (
            f"recommendation {recommendation_id}: {lines} trade lines, {breaches} breach{'' if breaches == 1 else 'es'}"
        )

    deps = ctx.deps
    prefix = screen_context.recommendation_figure_prefix(deps.db, recommendation_id)
    arguments = {"recommendation_id": recommendation_id}
    return _result(
        deps, "look_up_recommendation", arguments, _screen(deps, "recommendation", arguments, prefix), summarise
    )


async def look_up_approvals(ctx: RunContext[AssistantDeps]) -> str:
    """Look up the items waiting on the steps the user decides, as the Approvals panel lists them."""

    def summarise(data: dict) -> str:
        return _counted("approvals", data["total_items"], len(data["items"]), "items")

    return _result(ctx.deps, "look_up_approvals", {}, _screen(ctx.deps, "approvals", {}), summarise)


async def look_up_audit(ctx: RunContext[AssistantDeps], filters: AuditFilters | None = None) -> str:
    """Look up Audit Events, newest first, searched like the Audit screen. Figures are named `lookup.<n>.audit...`,
    where n is this lookup's place in the turn."""

    def summarise(data: dict) -> str:
        return _counted("audit", data["total_events"], len(data["events"]), "events")

    deps, arguments = ctx.deps, _arguments(filters)
    context = _screen(deps, "audit", arguments, _next_lookup_prefix(deps))
    return _result(deps, "look_up_audit", arguments, context, summarise)


async def look_up_governance(ctx: RunContext[AssistantDeps]) -> str:
    """Look up the governance model card: models, prompt versions, controls and the Assistant's limits."""
    context = _screen(ctx.deps, "governance", {})
    return _result(ctx.deps, "look_up_governance", {}, context, lambda data: "governance: model card")


async def list_approved_insights(ctx: RunContext[AssistantDeps], sector: str | None = None) -> str:
    """List research Insights whose Insight Review approved them, optionally for one sector (e.g. "Energy"), each
    with its Report id, page and passage. Quote a passage verbatim, with its Report id and page, to cite it."""

    def summarise(data: dict) -> str:
        return f"insights{f' ({sector})' if sector is not None else ''}: {data['total_insights']} approved"

    deps = ctx.deps
    arguments = {"sector": sector} if sector is not None else {}
    context = screen_context.approved_insights(deps.db, deps.user, sector)
    return _result(deps, "list_approved_insights", arguments, context, summarise)


ASSISTANT_TOOLS = (
    look_up_queue,
    look_up_portfolio,
    look_up_recommendation,
    look_up_approvals,
    look_up_audit,
    look_up_governance,
    list_approved_insights,
)


def build_agent(model: Model, request: LlmRequest) -> Agent[AssistantDeps, dict]:
    """All registered tools run on the caller's event loop, retaining its database session and capture binding."""
    agent = Agent(
        model,
        deps_type=AssistantDeps,
        instructions=request.system + "\n\nJSON schema of the reply:\n" + json.dumps(request.schema),
        output_type=NativeOutput(
            StructuredDict(cast(dict, wire_schema(request.schema)), name=request.task),
            template=False,
            strict=False,
        ),
        retries=0,
    )
    for tool in ASSISTANT_TOOLS:
        agent.tool(retries=0, sequential=True)(tool)
    return agent


def run_agent(model: Model, request: LlmRequest, deps: AssistantDeps) -> dict:
    return (
        build_agent(model, request)
        .run_sync(
            request.user,
            deps=deps,
            usage_limits=UsageLimits(request_limit=REQUEST_LIMIT),
        )
        .output
    )
