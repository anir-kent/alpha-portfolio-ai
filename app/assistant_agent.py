"""Read-only Assistant Agent and its safe, persisted per-turn Trajectory (ADR-0010)."""

import json
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
from app.screen_context import ScreenIdentity
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


async def look_up_portfolio(ctx: RunContext[AssistantDeps], portfolio_id: str) -> str:
    """Look up a Portfolio's permission-checked, PII-free Screen Context and citable engine figures."""
    deps = ctx.deps
    context = screen_context.build(
        deps.db,
        deps.market,
        deps.user,
        ScreenIdentity(kind="portfolio", entity_ids={"portfolio_id": portfolio_id}),
        deps.settings,
        figure_prefix=f"portfolio.{portfolio_id}.",
    )
    result = summary = NOT_PERMITTED
    if context is not None:
        deps.figures.update(context.figures)
        result = context.text
        data = json.loads(context.text)
        summary = f"Portfolio {portfolio_id}: {len(data['holdings'])} holdings"
        if (drift := context.figures.get(f"portfolio.{portfolio_id}.portfolio_drift_pp")) is not None:
            summary += f", drift {drift} pp"
    deps.tool_steps.append(
        (
            len(deps.exchanges),
            TrajectoryStep(
                kind="tool_call",
                name="look_up_portfolio",
                arguments={"portfolio_id": portfolio_id},
                result_summary=summary,
            ),
        )
    )
    return result


ASSISTANT_TOOLS = (look_up_portfolio,)


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
