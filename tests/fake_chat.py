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
rest to another. `RecordedPipeline` answers every pipeline request from the committed recordings, so the seeded demo
run produces what it always has and the Assistant's recordings, keyed on Screen Context, still replay. It is a bridge
until those recordings are removed (ticket 05).
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
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
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


def _message(step: object, model_name: str) -> AIMessage:
    if isinstance(step, BaseException):
        raise step
    if isinstance(step, AIMessage):
        return step
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

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "FakeChatModel":  # the documented FakeToolCallingModel
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
        request = ChatRequest(list(messages), params, dict(run_manager.metadata) if run_manager else {})
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


class RecordedPipeline(FakeChatModel):
    """Answers each pipeline request with its committed recording, under the model name it was recorded with. A
    request with no recording fails as `RecordingMissing`, as the replay did."""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        from app.pydantic_llm import ReplayModel
        from tests.fixtures.suggested_questions import RECORDED_MODEL, RECORDINGS

        request = self._received(messages, run_manager, kwargs)
        content, model_name = pydantic_single_call(
            ReplayModel(RECORDINGS, model_name=RECORDED_MODEL), request.step_call()
        )
        return ChatResult(generations=[ChatGeneration(message=_message(content, model_name or RECORDED_MODEL))])


def pydantic_single_call(model, call: LlmRequest) -> tuple[dict, str | None]:
    """The reply object and model name of the single pydantic-ai call the pipeline made before ADR-0011 (native
    structured output over the reply schema, no output retries), so the committed recordings' keys still match."""
    from pydantic_ai import Agent, AgentRetries, NativeOutput, StructuredDict

    from app.llm import wire_schema
    from app.llm_graph import system_prompt
    from app.pydantic_llm import tagged

    agent = Agent(
        model,
        instructions=system_prompt(call),
        output_type=NativeOutput(
            StructuredDict(wire_schema(call.schema), name=call.task),  # type: ignore[arg-type]
            template=False,
            strict=False,
        ),
        retries=AgentRetries(output=0),
    )
    with tagged(call):
        result = agent.run_sync(call.user)
    return result.output, result.response.model_name


def serve_chat[M: BaseChatModel](app: FastAPI, model: M) -> M:
    """Makes `model` the chat model the app's pipeline LLM Graph runs on, behind the capture the app serves. Returns
    `model`, so a test can read the requests it received."""
    app.state.llm.chat_model = model
    return model
