"""The Assistant's LLM Graph and its safe, persisted per-turn Trajectory (ADR-0011).

The graph is LangGraph's documented tool-calling agent (Workflows and agents) as an explicit `StateGraph` over
`MessagesState`: an `agent` Graph Node (`model.bind_tools(tools)`), a prebuilt `ToolNode` named `tools`, a conditional
edge `agent -> tools | validate` (the prebuilt `tools_condition`) and an edge `tools -> agent`. `validate` ends the turn;
the grounding and PII checks, the reflection edge and the request budget join it in ticket 04.
"""

import json
import threading
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
from app.llm import LlmError, LlmRequest, parse_json_reply
from app.llm_graph import system_prompt
from app.market_data import MarketData
from app.screen_context import ScreenContext, ScreenIdentity, ScreenKind
from app.settings import Settings

NOT_PERMITTED = "not found or not permitted for your role"

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


def _screen(
    deps: AssistantDeps, kind: ScreenKind, entity_ids: dict[str, str], prefix: str = ""
) -> ScreenContext | None:
    """The Screen Context of `kind` as the asking user would see it, its figures named with `prefix`."""
    screen = ScreenIdentity(kind=kind, entity_ids=entity_ids)
    return screen_context.build(deps.db, deps.market, deps.user, screen, deps.settings, figure_prefix=prefix)


# ToolNode runs the tool calls of one model reply on worker threads. They share the turn's Session and state, so the
# tools take turns, as ADR-0010's sequential tools did.
_TOOLS_TAKE_TURNS = threading.Lock()


@tool
def look_up_portfolio(portfolio_id: str, runtime: ToolRuntime[AssistantContext]) -> str:
    """Look up a Portfolio's permission-checked, PII-free Screen Context and citable engine figures."""
    with _TOOLS_TAKE_TURNS:
        return _look_up_portfolio(runtime.context.deps, portfolio_id)


def _look_up_portfolio(deps: AssistantDeps, portfolio_id: str) -> str:
    arguments = {"portfolio_id": portfolio_id}
    context = _screen(deps, "portfolio", arguments, f"portfolio.{portfolio_id}.")
    if context is None:  # a screen the user may not open and an entity that does not exist give the same result
        deps.add_step(
            TrajectoryStep(
                kind="tool_call", name="look_up_portfolio", arguments=arguments, result_summary=NOT_PERMITTED
            )
        )
        return NOT_PERMITTED
    deps.figures.update(context.figures)
    data, _ = json.JSONDecoder().raw_decode(context.text)  # fenced passages may follow the JSON
    summary = f"Portfolio {portfolio_id}: {len(data['holdings'])} holdings"
    if (drift := data["portfolio_drift_pp"]) is not None:
        summary += f", drift {drift} pp"
    deps.add_step(
        TrajectoryStep(kind="tool_call", name="look_up_portfolio", arguments=arguments, result_summary=summary)
    )
    return context.text


ASSISTANT_TOOLS = (look_up_portfolio,)


def agent(state: MessagesState, runtime: Runtime[AssistantContext]) -> dict:
    """One model request: the model decides to call a tool or to reply."""
    context = runtime.context
    model = context.model.bind_tools(list(ASSISTANT_TOOLS))
    return {"messages": [model.invoke([SystemMessage(system_prompt(context.request)), *state["messages"]])]}


def validate(state: MessagesState) -> dict:
    """The turn's candidate reply is final. Ticket 04 adds the grounding and PII checks here."""
    return {}


def _build_graph():
    # handle_tool_errors=False: a bad tool call fails the turn, as before (no tool retries).
    return (
        StateGraph(MessagesState, context_schema=AssistantContext)
        .add_node(AGENT, agent)
        .add_node(TOOLS, ToolNode(list(ASSISTANT_TOOLS), handle_tool_errors=False))
        .add_node(VALIDATE, validate)
        .add_edge(START, AGENT)
        .add_conditional_edges(AGENT, tools_condition, {"tools": TOOLS, END: VALIDATE})
        .add_edge(TOOLS, AGENT)
        .add_edge(VALIDATE, END)
        .compile(name="assistant")
    )


ASSISTANT = _build_graph()


def run_assistant(
    model: BaseChatModel, request: LlmRequest, deps: AssistantDeps, callbacks: list[BaseCallbackHandler]
) -> dict:
    """The reply object the Assistant graph ends the turn with. `callbacks` see every model call, and each call's
    Graph Node."""
    state = ASSISTANT.invoke(
        {"messages": [HumanMessage(request.user)]},
        {
            "callbacks": callbacks,
            "metadata": {"llm_task": request.task, "llm_prompt_version": request.prompt_version},
            # Interim bound until the request budget is a counter in graph state (ticket 04): agent and tools alternate.
            "recursion_limit": 2 * deps.settings.assistant_request_limit + 1,
        },
        context=AssistantContext(model=model, deps=deps, request=request),
    )
    final = state["messages"][-1]
    if not isinstance(final, AIMessage):
        raise LlmError("the Assistant graph did not end on a model reply")
    return parse_json_reply(str(final.text))
