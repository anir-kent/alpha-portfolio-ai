"""The fake chat model the pipeline's LLM Graph runs on in tests (ADR-0011; LangChain docs: test/unit-testing).

`FakeChatModel` is LangChain's documented `FakeToolCallingModel`: a `GenericFakeChatModel` whose `bind_tools` returns
itself. Its replies are a script, and it keeps every request it received:

    model = FakeChatModel({"insights": []}, then=lambda request: {"echo": request.user_prompt})

Each step answers one model request, in order:
- a `dict` is a reply object, sent as its JSON text (the reply content structured output parses)
- a `str` is reply text, sent as is
- an `AIMessage` is sent as is
- an exception is raised by the request, as a failing provider's would be
- a callable takes the `ChatRequest` and returns any of the above
A request beyond the script fails the test, unless a `then` step answers every request after it.

Test seam for structured output: a fake's base `with_structured_output` would use function calling (a tool call of the
schema), but the pipeline asks for `method="json_schema"`. So `with_structured_output` here is the provider
integration's own `json_schema` path: it binds the same `response_format` and parses the reply content with the same
parser, and the script just returns JSON content.

`ByTask(fallback, research_tilt=FakeChatModel(...))` answers some pipeline tasks from their own fake and leaves the
rest to another. `DemoPipeline` answers every pipeline task with a deterministic reply built from the request, so the
seeded demo run completes offline.
"""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_openrouter import ChatOpenRouter
from pydantic import Field

from app.llm import LlmRequest
from app.llm_graph import REPLY_SCHEMA_HEADING


@dataclass(frozen=True)
class ChatRequest:
    """One model request as the fake received it: the messages, the call parameters (`response_format`…) and the run
    metadata the LLM Graph tagged it with (`llm_task`, `llm_prompt_version`, `langgraph_node`)."""

    messages: list[BaseMessage]
    params: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    tools: list = field(default_factory=list)  # the tools bound to the model for this request

    @property
    def instructions(self) -> str:
        """The system text without its reply schema: what the Assistant's agent was instructed with."""
        return self.system.partition(REPLY_SCHEMA_HEADING)[0]

    @property
    def schema(self) -> dict:
        """The reply schema the system text carries."""
        return json.loads(self.system.partition(REPLY_SCHEMA_HEADING)[2])

    @property
    def prompts(self) -> list[str]:
        """The text of every user message sent, oldest first."""
        return [str(m.content) for m in self.messages if isinstance(m, HumanMessage)]

    @property
    def tool_returns(self) -> dict[str, object]:
        """Each tool's latest result in the messages sent, by tool name."""
        return {m.name: m.content for m in self.messages if isinstance(m, ToolMessage) and m.name}

    @property
    def task(self) -> str | None:
        return self.metadata.get("llm_task")

    @property
    def prompt_version(self) -> str | None:
        return self.metadata.get("llm_prompt_version")

    @property
    def system(self) -> str:
        return next(str(m.content) for m in self.messages if isinstance(m, SystemMessage))

    @property
    def user_prompt(self) -> str:
        return [str(m.content) for m in self.messages if isinstance(m, HumanMessage)][-1]

    @property
    def payload(self) -> dict:
        """The user prompt as the JSON object a pipeline step sends."""
        return json.loads(self.user_prompt)

    @property
    def response_format(self) -> dict:
        return self.params.get("response_format") or {}

    def step_call(self) -> LlmRequest:
        """The step call this request was made for, as the pipeline sent it."""
        system, _, schema = self.system.partition(REPLY_SCHEMA_HEADING)
        assert self.task and self.prompt_version, "a request outside the pipeline graph"
        return LlmRequest(self.task, self.prompt_version, system, self.user_prompt, json.loads(schema))


Step = Any  # dict | str | AIMessage | BaseException | Callable[[ChatRequest], ...]


def call(tool_name: str, **args: object) -> AIMessage:
    """A scripted reply that calls one tool."""
    return calls({"name": tool_name, "args": args, "id": f"call-{tool_name}", "type": "tool_call"})


def calls(*tool_calls: dict) -> AIMessage:
    """A scripted reply that calls one or several tools at once."""
    return AIMessage(
        content="",
        tool_calls=list(tool_calls),
        response_metadata={"model_name": "scripted"},
        usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    )


def _message(step: object, model_name: str) -> AIMessage:
    if isinstance(step, BaseException):
        raise step
    if isinstance(step, AIMessage):
        return step.model_copy(update={"id": None})  # a repeated step is a new message, not an update of the old one
    if isinstance(step, list):  # several tool calls in one reply
        return calls(*(m.tool_calls[0] for m in step))
    if isinstance(step, dict):
        content = json.dumps(step)
    elif isinstance(step, str):
        content = step
    else:
        pytest.fail(f"not a script step: {step!r}")
    return AIMessage(
        content=content,
        response_metadata={"model_name": model_name},
        usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    )


class FakeChatModel(GenericFakeChatModel):
    """Answers its n-th request with the n-th step of its script, and any request after it with `then` when given.
    `requests` holds every request received, in order."""

    messages: Iterator[AIMessage] = Field(default_factory=lambda: iter(()))
    script: list = Field(default_factory=list)
    then: Any = None
    model_name: str = "scripted"
    requests: list[ChatRequest] = Field(default_factory=list)

    def __init__(self, *steps: Step, **values: Any) -> None:
        super().__init__(script=list(steps), **values)

    tools: list = Field(default_factory=list)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "FakeChatModel":  # the documented FakeToolCallingModel
        self.tools = list(tools)
        return self

    def with_structured_output(self, schema: dict | type, *, include_raw: bool = False, **kwargs: Any) -> Runnable:
        kwargs.pop("method", None)
        # Only `bind` is used on `self`: the provider's json_schema binding and output parser.
        return ChatOpenRouter.with_structured_output(
            self,  # type: ignore[arg-type]
            schema,
            method="json_schema",
            include_raw=include_raw,
            **kwargs,
        )

    def _received(
        self, messages: list[BaseMessage], run_manager: CallbackManagerForLLMRun | None, params: dict
    ) -> ChatRequest:
        """The request as received, kept in `requests`."""
        request = ChatRequest(
            list(messages), params, dict(run_manager.metadata) if run_manager else {}, list(self.tools)
        )
        self.requests.append(request)
        return request

    def answer(self, request: ChatRequest) -> Step:
        """The step that answers `request`."""
        n = len(self.requests)
        if n <= len(self.script):
            return self.script[n - 1]
        if self.then is None:
            pytest.fail(f"model request {n}, but the script has {len(self.script)} step(s)")
        return self.then

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        request = self._received(messages, run_manager, kwargs)
        step = self.answer(request)
        if callable(step) and not isinstance(step, BaseException):
            try:
                step = step(request)
            except Exception as error:
                pytest.fail(f"script callback failed: {type(error).__name__}: {error}")
        return ChatResult(generations=[ChatGeneration(message=_message(step, self.model_name))])


class ByTask(FakeChatModel):
    """Answers each request of a scripted task with that task's fake and passes any other on to `fallback`. `tasks`
    lists the task of every request received, in order. Override `script_for` to choose another way."""

    fallback: Any = None
    scripts: dict = Field(default_factory=dict)
    tasks: list[str] = Field(default_factory=list)

    def __init__(self, fallback: FakeChatModel, **scripts: FakeChatModel) -> None:
        super().__init__(fallback=fallback, scripts=scripts)

    def script_for(self, task: str) -> FakeChatModel | None:
        return self.scripts.get(task)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        task = (run_manager.metadata if run_manager else {}).get("llm_task", "")
        self.tasks.append(task)
        model = self.script_for(task) or self.fallback
        return model._generate(messages, stop, run_manager, **kwargs)


class DemoPipeline(FakeChatModel):
    """Answers every pipeline task with a plausible, deterministic reply built from the request, so the seeded demo run
    completes offline: the fixture Reports' hand-authored Insights, a small tilt per Insight by its direction, and
    narratives of claims that cite the engine figures (and, where an Insight bears on a figure, its Report passage).
    A task it cannot answer fails as an unreachable provider does."""

    model_name: str = "demo-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        request = self._received(messages, run_manager, kwargs)
        reply = demo_reply(request)
        return ChatResult(generations=[ChatGeneration(message=_message(reply, self.model_name))])


_TILT_PP = {"positive": 0.3, "negative": -0.3}


def demo_reply(request: ChatRequest) -> dict:
    """The demo's reply object for one pipeline request."""
    from tests.fixtures.llm_cases import EXTRACTION_REPLIES

    task = request.task
    if task == "insight_extraction":
        if request.user_prompt not in EXTRACTION_REPLIES:
            raise ConnectionError("the demo has no reply for this Report")
        return EXTRACTION_REPLIES[request.user_prompt]
    if task == "research_tilt":
        tilts = []
        for insight in request.payload["insights"]:
            pp = _TILT_PP.get(insight["direction"], 0.0)
            impact = "tailwind" if pp > 0 else "headwind" if pp < 0 else "neutral"
            tilts.append({"insight_id": insight["id"], "impact": impact, "tilt_pp": pp})
        return {"tilts": tilts}
    if task in ("recommendation_narrative", "priority_narrative"):
        return {"claims": _demo_claims(request.payload)}
    raise ConnectionError(f"the demo has no reply for {task}")


def _demo_claims(payload: dict) -> list[dict]:
    """Up to two engine-figure claims, and one view on an Insight's subject that cites both its figure and passage."""
    figures: dict[str, float] = payload["figures"]
    plain = [name for name in figures if not any(c.isdigit() for c in name)]  # a figure name is no number in a claim
    claims = [
        {
            "text": f"The {name.replace('_', ' ').replace('.', ' ')} is {figures[name]}.",
            "asset": None,
            "citations": [{"kind": "engine", "figure": name}],
        }
        for name in plain[:2]
    ]
    for insight in payload["insights"]:
        figure = next((n for n in plain if n.endswith(f".{insight['subject']}")), None)
        if figure:
            claims.append(
                {
                    "text": f"Research is {insight['direction']} on {insight['subject']}.",
                    "asset": insight["subject"],
                    "citations": [
                        {"kind": "engine", "figure": figure},
                        {
                            "kind": "report",
                            "report_id": insight["report_id"],
                            "page": insight["page"],
                            "quote": insight["passage"],
                        },
                    ],
                }
            )
            break
    return claims


def serve_chat[M: BaseChatModel](app: FastAPI, model: M) -> M:
    """Makes `model` the chat model the app's pipeline LLM Graph runs on, behind the capture the app serves. Returns
    `model`, so a test can read the requests it received."""
    app.state.llm.chat_model = model
    return model
