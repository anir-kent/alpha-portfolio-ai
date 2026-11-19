"""The Assistant's LLM Graph and its safe, persisted per-turn Trajectory (ADR-0011).

The graph is LangGraph's documented tool-calling agent (Workflows and agents) as an explicit `StateGraph` over
`MessagesState`: an `agent` Graph Node (`model.bind_tools(tools)`), a prebuilt `ToolNode` named `tools`, a conditional
edge `agent -> tools | validate` (the prebuilt `tools_condition`) and an edge `tools -> agent`. `validate` checks the candidate reply: it
ends the turn, sends the model its ungrounded Claims once (the reflection edge `validate -> agent`), or rejects a PII
reply. The request budget is a model-call counter in the state, checked in the edges into `agent`.
"""

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from langchain.tools import ToolRuntime, tool
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.runtime import Runtime
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import screen_context
from app.db import LlmExchangeRow, User
from app.grounding import ClaimResult
from app.llm import LlmError, LlmRequest, parse_json_reply
from app.llm_graph import system_prompt
from app.market_data import MarketData
from app.routers.analysis import QueueFilters
from app.screen_context import AuditFilters, ScreenContext, ScreenIdentity, ScreenKind
from app.settings import Settings

# Checks one candidate reply against the guardrails: raises PiiExposed, else returns its ungrounded Claims.
Review = Callable[["AssistantDeps", dict], list[ClaimResult]]

NOT_PERMITTED = "not found or not permitted for your role"

BUDGET_EXHAUSTED = "budget_exhausted"
AGENT = "agent"
TOOLS = "tools"
VALIDATE = "validate"


class TrajectoryStep(BaseModel):
    kind: Literal["model_request", "tool_call", "self_correction"]
    name: str | None = None
    arguments: dict[str, str] | None = None
    result_summary: str | None = None
    issue_count: int | None = None  # a self-correction: the grounding issues the rejected draft was told about


class Trajectory(BaseModel):
    steps: list[TrajectoryStep]
    requests_used: int
    request_limit: int
    input_tokens: int
    output_tokens: int

    def made_lookups(self) -> bool:
        """Whether the turn's model called at least one tool."""
        return any(step.kind == "tool_call" for step in self.steps)


@dataclass
class AssistantDeps:
    user: User
    db: Session
    market: MarketData
    settings: Settings
    figures: dict[str, float]
    exchanges: list[LlmExchangeRow]  # the turn's stored Exchanges, appended to by the capture callback
    steps: list[tuple[int, TrajectoryStep]] = field(default_factory=list)  # each after the model request it followed

    def add_step(self, step: TrajectoryStep) -> None:
        """`step` follows the latest model request in the summary."""
        self.steps.append((len(self.exchanges), step))

    def summary(self) -> Trajectory:
        steps = []
        input_tokens = output_tokens = 0
        for n, row in enumerate(self.exchanges, start=1):
            steps.append(TrajectoryStep(kind="model_request"))
            steps.extend(step for after, step in self.steps if after == n)
            usage = json.loads(row.usage_json or "{}")
            input_tokens += usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
            output_tokens += usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        return Trajectory(
            steps=steps,
            requests_used=len(self.exchanges),
            request_limit=self.settings.assistant_request_limit,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


@dataclass(frozen=True)
class AssistantContext:
    """Runtime context of one turn's graph run: the chat model and the turn's state the tools read and extend."""

    model: BaseChatModel
    deps: AssistantDeps
    request: LlmRequest
    review: Review  # the guardrails `validate` applies to a candidate reply


def _screen(
    deps: AssistantDeps, kind: ScreenKind, entity_ids: dict[str, str], prefix: str = ""
) -> ScreenContext | None:
    """The Screen Context of `kind` as the asking user would see it, its figures named with `prefix`."""
    screen = ScreenIdentity(kind=kind, entity_ids=entity_ids)
    return screen_context.build(deps.db, deps.market, deps.user, screen, deps.settings, figure_prefix=prefix)


# ToolNode runs the tool calls of one model reply on worker threads. They share the turn's Session and state, so the
# tools take turns, as ADR-0010's sequential tools did.
_TOOLS_TAKE_TURNS = threading.Lock()


def _record(deps: AssistantDeps, name: str, arguments: dict[str, str], summary: str) -> None:
    """A tool call's step, placed after the model request that made it."""
    deps.add_step(TrajectoryStep(kind="tool_call", name=name, arguments=arguments, result_summary=summary))


def _arguments(filters: BaseModel | dict | None) -> dict[str, str]:
    """The filters the model gave, as the screen's query string would carry them."""
    if isinstance(filters, BaseModel):
        given = filters.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    else:
        given = filters or {}
    return {key: json.dumps(value) if isinstance(value, bool) else str(value) for key, value in given.items()}


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
    return f"lookup.{sum(step.kind == 'tool_call' for _, step in deps.steps) + 1}."


def _counted(screen: str, total: int, shown: int, noun: str) -> str:
    return f"{screen}: {total} {noun}" + (f", showing {shown}" if shown < total else "")


@tool
def look_up_queue(runtime: ToolRuntime[AssistantContext], filters: QueueFilters | None = None) -> str:
    """Look up the prioritised Queue as the Queue screen shows it, optionally filtered and sorted like that screen.
    Figures are named `lookup.<n>.queue...`, where n is this lookup's place in the turn."""

    def summarise(data: dict) -> str:
        if not isinstance(data["rows"], list):
            return "queue: no completed Analysis Run"
        return _counted("queue", data["total_rows"], len(data["rows"]), "rows")

    with _TOOLS_TAKE_TURNS:
        deps, arguments = runtime.context.deps, _arguments(filters)
        context = _screen(deps, "queue", arguments, _next_lookup_prefix(deps))
        return _result(deps, "look_up_queue", arguments, context, summarise)


@tool
def look_up_portfolio(portfolio_id: str, runtime: ToolRuntime[AssistantContext]) -> str:
    """Look up a Portfolio's permission-checked, PII-free Screen Context and citable engine figures."""

    def summarise(data: dict) -> str:
        summary = f"Portfolio {portfolio_id}: {len(data['holdings'])} holdings"
        drift = data["portfolio_drift_pp"]
        return summary + (f", drift {drift} pp" if drift is not None else "")

    with _TOOLS_TAKE_TURNS:
        deps, arguments = runtime.context.deps, {"portfolio_id": portfolio_id}
        context = _screen(deps, "portfolio", arguments, f"portfolio.{portfolio_id}.")
        return _result(deps, "look_up_portfolio", arguments, context, summarise)


@tool
def look_up_recommendation(recommendation_id: str, runtime: ToolRuntime[AssistantContext]) -> str:
    """Look up one Recommendation's rationale as its screen shows it: Trade Lines, post-trade Suitability, the
    Research Tilt with its Report passages (for roles that may read Insights) and grounded Claims. Figures are named
    `portfolio.<Portfolio>.recommendation.<Recommendation>...`."""

    def summarise(data: dict) -> str:
        lines = len(data["trade_lines"])
        breaches = sum(rule["status"] == "breach" for rule in data["post_trade_suitability"]["rules"])
        return (
            f"recommendation {recommendation_id}: {lines} trade lines, {breaches} breach{'' if breaches == 1 else 'es'}"
        )

    with _TOOLS_TAKE_TURNS:
        deps = runtime.context.deps
        prefix = screen_context.recommendation_figure_prefix(deps.db, recommendation_id)
        arguments = {"recommendation_id": recommendation_id}
        context = _screen(deps, "recommendation", arguments, prefix)
        return _result(deps, "look_up_recommendation", arguments, context, summarise)


@tool
def look_up_approvals(runtime: ToolRuntime[AssistantContext]) -> str:
    """Look up the items waiting on the steps the user decides, as the Approvals panel lists them."""

    def summarise(data: dict) -> str:
        return _counted("approvals", data["total_items"], len(data["items"]), "items")

    with _TOOLS_TAKE_TURNS:
        deps = runtime.context.deps
        return _result(deps, "look_up_approvals", {}, _screen(deps, "approvals", {}), summarise)


@tool
def look_up_audit(runtime: ToolRuntime[AssistantContext], filters: AuditFilters | None = None) -> str:
    """Look up Audit Events, newest first, searched like the Audit screen. Figures are named `lookup.<n>.audit...`,
    where n is this lookup's place in the turn."""

    def summarise(data: dict) -> str:
        return _counted("audit", data["total_events"], len(data["events"]), "events")

    with _TOOLS_TAKE_TURNS:
        deps, arguments = runtime.context.deps, _arguments(filters)
        context = _screen(deps, "audit", arguments, _next_lookup_prefix(deps))
        return _result(deps, "look_up_audit", arguments, context, summarise)


@tool
def look_up_governance(runtime: ToolRuntime[AssistantContext]) -> str:
    """Look up the governance model card: models, prompt versions, controls and the Assistant's limits."""
    with _TOOLS_TAKE_TURNS:
        deps = runtime.context.deps
        context = _screen(deps, "governance", {})
        return _result(deps, "look_up_governance", {}, context, lambda data: "governance: model card")


@tool
def list_approved_insights(runtime: ToolRuntime[AssistantContext], sector: str | None = None) -> str:
    """List research Insights whose Insight Review approved them, optionally for one sector (e.g. "Energy"), each
    with its Report id, page and passage. Quote a passage verbatim, with its Report id and page, to cite it."""

    def summarise(data: dict) -> str:
        return f"insights{f' ({sector})' if sector is not None else ''}: {data['total_insights']} approved"

    with _TOOLS_TAKE_TURNS:
        deps = runtime.context.deps
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


class AssistantState(MessagesState):
    """The messages plus what the routing edges read: model calls made, whether the reflection retry was used, and how
    the turn ended (`answer` until a node ends it another way)."""

    model_calls: int
    retried: bool
    ending: Literal["answer", "pii", "budget_exhausted"]


class PiiExposed(Exception):
    """A candidate reply named a Client. The run ends here: the draft is never coached, retried, stored or shown."""


class BudgetExhausted(Exception):
    """The turn used its request budget (`APP_ASSISTANT_REQUEST_LIMIT`) without a final reply."""


def agent(state: AssistantState, runtime: Runtime[AssistantContext]) -> dict:
    """One model request: the model decides to call a tool or to reply."""
    context = runtime.context
    model = context.model.bind_tools(list(ASSISTANT_TOOLS))
    reply = model.invoke([SystemMessage(system_prompt(context.request)), *state["messages"]])
    return {"messages": [reply], "model_calls": state.get("model_calls", 0) + 1}


def retry_message(failing: list[ClaimResult]) -> str:
    """What the model is told about a rejected draft: each failing Claim and its issues."""
    lines = [f'- Claim {r.index} "{r.text}": ' + "; ".join(f"{i.code}: {i.message}" for i in r.issues) for r in failing]
    return (
        "These Claims are not grounded. Fix or remove each one: cite only figures named in the Screen Context or a "
        "lookup, with the number as the figure shows it, and quote Reports verbatim.\n" + "\n".join(lines)
    )


def validate(state: AssistantState, runtime: Runtime[AssistantContext]) -> dict:
    """The evaluator of the evaluator-optimizer loop: checks the candidate reply against the deterministic guardrails.
    A reply naming a Client ends the turn (`pii`). Ungrounded Claims send the model their list once; after that retry
    they are kept (the caller flags them). A reply that is not a JSON object passes, for the caller to fail."""
    context = runtime.context
    final = state["messages"][-1]
    try:
        content = parse_json_reply(str(final.text))
    except LlmError:
        return {}
    try:
        failing = context.review(context.deps, content)
    except PiiExposed:
        return {"ending": "pii"}
    if failing and not state.get("retried"):
        context.deps.add_step(TrajectoryStep(kind="self_correction", issue_count=sum(len(r.issues) for r in failing)))
        return {"messages": [HumanMessage(retry_message(failing))], "retried": True}
    return {}


def route_validate(state: AssistantState, runtime: Runtime[AssistantContext]) -> str:
    """`validate -> END` (accepted, retry already used, or PII rejected), or back to `agent` with the feedback, if the
    request budget allows another run."""
    if state.get("ending") != "pii" and isinstance(state["messages"][-1], HumanMessage):  # the reflection feedback
        return route_to_agent(state, runtime)
    return END


def route_to_agent(state: AssistantState, runtime: Runtime[AssistantContext]) -> str:
    """The request budget: checked in routing before each `agent` run."""
    if state.get("model_calls", 0) >= runtime.context.deps.settings.assistant_request_limit:
        return BUDGET_EXHAUSTED
    return AGENT


def budget_exhausted(state: AssistantState) -> dict:
    return {"ending": "budget_exhausted"}


def _build_graph():
    # handle_tool_errors=False: a bad tool call fails the turn, as before (no tool retries).
    return (
        StateGraph(AssistantState, context_schema=AssistantContext)
        .add_node(AGENT, agent)
        .add_node(TOOLS, ToolNode(list(ASSISTANT_TOOLS), handle_tool_errors=False))
        .add_node(VALIDATE, validate)
        .add_node(BUDGET_EXHAUSTED, budget_exhausted)
        .add_conditional_edges(START, route_to_agent, [AGENT, BUDGET_EXHAUSTED])
        .add_conditional_edges(AGENT, tools_condition, {"tools": TOOLS, END: VALIDATE})
        .add_conditional_edges(TOOLS, route_to_agent, [AGENT, BUDGET_EXHAUSTED])
        .add_conditional_edges(VALIDATE, route_validate, [AGENT, BUDGET_EXHAUSTED, END])
        .add_edge(BUDGET_EXHAUSTED, END)
        .compile(name="assistant")
    )


ASSISTANT = _build_graph()


def run_assistant(
    model: BaseChatModel,
    request: LlmRequest,
    deps: AssistantDeps,
    callbacks: list[BaseCallbackHandler],
    review: Review,
) -> dict:
    """The reply object the Assistant graph ends the turn with, which has passed `review` or is the second draft (its
    ungrounded Claims are for the caller to flag). Raises PiiExposed, or BudgetExhausted when the request budget ran
    out. `callbacks` see every model call, and each call's Graph Node."""
    state = ASSISTANT.invoke(
        {"messages": [HumanMessage(request.user)], "model_calls": 0, "retried": False, "ending": "answer"},
        {
            "callbacks": callbacks,
            "metadata": {"llm_task": request.task, "llm_prompt_version": request.prompt_version},
            # A backstop only: the budget edge ends the turn first (a model call is at most agent + tools + validate).
            "recursion_limit": 3 * deps.settings.assistant_request_limit + 5,
        },
        context=AssistantContext(model=model, deps=deps, request=request, review=review),
    )
    if state["ending"] == "pii":
        raise PiiExposed
    if state["ending"] == "budget_exhausted":
        raise BudgetExhausted
    final = state["messages"][-1]
    if not isinstance(final, AIMessage):
        raise LlmError("the Assistant graph did not end on a model reply")
    return parse_json_reply(str(final.text))
