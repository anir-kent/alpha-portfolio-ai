"""The scripted-model test helper: a pydantic-ai Model whose replies and tool calls are a script, and which keeps every
request it received (ADR-0010; spec: Testing Decisions).

    model = ScriptedModel(call("look_up_portfolio", portfolio_id=12), {"answer": ...})

Each step answers one model request, in order:
- a `dict` is a reply object, sent as its JSON text
- a `str` is reply text, sent as is
- `call(name, **args)`, or a list of calls and text, is a response with those tool calls
- an exception is raised by the request
- a callable takes the `ScriptedRequest` and returns any of the above
A request beyond the script fails the test, unless a `then` step answers every request after it. Being a Model, it goes
behind capture like any other, so a test that scripts it exercises the same capture path as a live or replayed call.
Behind capture each request also knows the step call it belongs to: its task, prompt version and reply schema.

`ByTask(fallback, research_tilt=ScriptedModel(...))` scripts some pipeline steps and leaves the rest to another Model,
typically the app's replay Model, so a test scripts only the step it is about.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponsePart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition

from app.exchanges import ModelLlm
from app.llm import LlmRequest
from app.pydantic_llm import current_request


def _step_call() -> LlmRequest | None:
    try:
        return current_request()
    except RuntimeError:  # an Agent run outside capture: no step call is tagged
        return None


@dataclass(frozen=True)
class ScriptedRequest:
    """One model request as the scripted Model received it."""

    messages: list[ModelMessage]
    info: AgentInfo
    step_call: LlmRequest | None = None  # the step call this request belongs to, when it came through capture

    @property
    def task(self) -> str | None:
        return None if self.step_call is None else self.step_call.task

    @property
    def prompt_version(self) -> str | None:
        return None if self.step_call is None else self.step_call.prompt_version

    @property
    def instructions(self) -> str | None:
        return self.info.instructions

    @property
    def schema(self) -> dict | None:
        """The JSON schema the reply is held to (native structured output), if any."""
        output = self.info.model_request_parameters.output_object
        return None if output is None else output.json_schema

    @property
    def tools(self) -> list[ToolDefinition]:
        """The function tools offered to the model with this request."""
        return self.info.function_tools

    @property
    def prompts(self) -> list[str]:
        """The text of every user prompt sent, oldest first: the first is the step's own, and any after it is retry
        feedback on a rejected reply."""
        prompts = [
            part.content
            for message in self.messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        ]
        assert prompts, "the request carries no text user prompt"
        return prompts

    @property
    def user_prompt(self) -> str:
        """The text of the latest user prompt sent."""
        return self.prompts[-1]

    @property
    def tool_returns(self) -> dict[str, object]:
        """Each tool's latest result in the messages sent, by tool name."""
        return {
            part.tool_name: part.content
            for message in self.messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        }


def call(tool_name: str, **args: object) -> ToolCallPart:
    """A scripted tool call."""
    return ToolCallPart(tool_name, args)


Step = dict | str | ToolCallPart | list[ModelResponsePart | str] | BaseException | Callable[[ScriptedRequest], object]


def _response(step: object) -> ModelResponse:
    if isinstance(step, BaseException):
        raise step
    if isinstance(step, dict):
        return ModelResponse(parts=[TextPart(json.dumps(step))])
    if isinstance(step, str):
        return ModelResponse(parts=[TextPart(step)])
    if isinstance(step, ToolCallPart):
        return ModelResponse(parts=[step])
    if isinstance(step, list):
        return ModelResponse(parts=[TextPart(p) if isinstance(p, str) else p for p in step])
    pytest.fail(f"not a script step: {step!r}")


class ScriptedModel(FunctionModel):
    """A Model that answers its n-th request with the n-th step of its script, and any request after the script with
    `then` when given. `requests` holds every request received, in order."""

    def __init__(self, *steps: Step, then: Step | None = None, model_name: str = "scripted") -> None:
        self.steps = list(steps)
        self.then = then
        self.requests: list[ScriptedRequest] = []
        super().__init__(self._answer, model_name=model_name)

    async def _answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        # A coroutine, so it runs in the request's own context and sees the step call capture tagged.
        request = ScriptedRequest(list(messages), info, _step_call())
        self.requests.append(request)
        n = len(self.requests)
        if n <= len(self.steps):
            step = self.steps[n - 1]
        else:
            if self.then is None:
                pytest.fail(f"model request {n}, but the script has {len(self.steps)} step(s)")
            step = self.then
        response_step: object = step
        if callable(step) and not isinstance(step, BaseException):
            try:
                response_step = step(request)
            except Exception as error:
                pytest.fail(f"script callback failed: {type(error).__name__}: {error}")
        return _response(response_step)


class ByTask(WrapperModel):
    """A Model that answers each request of a scripted task with that task's Model, and passes any other on to
    `fallback`. The task is the one capture tagged the request with. `tasks` lists the task of every request received,
    in order. Override `script_for` to choose the script some other way."""

    def __init__(self, fallback: Model, **scripts: Model) -> None:
        super().__init__(fallback)
        self.scripts = scripts
        self.tasks: list[str] = []

    def script_for(self, task: str) -> Model | None:
        return self.scripts.get(task)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        task = current_request().task
        self.tasks.append(task)
        script = self.script_for(task)
        if script is None:
            return await super().request(messages, model_settings, model_request_parameters)
        return await script.request(messages, model_settings, model_request_parameters)


def serve[M: Model](app: FastAPI, model: M) -> M:
    """Makes `model` the one the app's LLM calls go to, behind the same capture the app serves (Exchanges labelled
    `recorded`, as a replay's are). Returns `model`, so a test can read the requests it received."""
    app.state.llm = ModelLlm(model, app.state.session_factory, mode="recorded")
    return model
