"""The scripted-model test helper: a pydantic-ai Model whose replies and tool calls are a script, and which keeps every
request it received (ADR-0010; spec: Testing Decisions).

    model = ScriptedModel(call("look_up_portfolio", portfolio_id=12), {"answer": ...})

Each step answers one model request, in order:
- a `dict` is a reply object, sent as its JSON text
- a `str` is reply text, sent as is
- `call(name, **args)`, or a list of calls and text, is a response with those tool calls
- an exception is raised by the request
- a callable takes the `ScriptedRequest` and returns any of the above
A request beyond the script fails the test. Being a Model, it goes behind capture like any other, so a test that
scripts it exercises the same capture path as a live or replayed call.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass

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
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition


@dataclass(frozen=True)
class ScriptedRequest:
    """One model request as the scripted Model received it."""

    messages: list[ModelMessage]
    info: AgentInfo

    @property
    def instructions(self) -> str | None:
        return self.info.instructions

    @property
    def tools(self) -> list[ToolDefinition]:
        """The function tools offered to the model with this request."""
        return self.info.function_tools

    @property
    def user_prompt(self) -> str:
        """The text of the latest user prompt sent."""
        prompts = [
            part.content
            for message in self.messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        ]
        assert prompts, "the request carries no text user prompt"
        return prompts[-1]

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
    raise TypeError(f"not a script step: {step!r}")


class ScriptedModel(FunctionModel):
    """A Model that answers its n-th request with the n-th step of its script. `requests` holds every request
    received, in order."""

    def __init__(self, *steps: Step, model_name: str = "scripted"):
        self.steps = list(steps)
        self.requests: list[ScriptedRequest] = []
        super().__init__(self._answer, model_name=model_name)

    def _answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        request = ScriptedRequest(list(messages), info)
        self.requests.append(request)
        n = len(self.requests)
        assert n <= len(self.steps), f"model request {n}, but the script has {len(self.steps)} step(s)"
        step = self.steps[n - 1]
        return _response(step(request) if callable(step) and not isinstance(step, BaseException) else step)
