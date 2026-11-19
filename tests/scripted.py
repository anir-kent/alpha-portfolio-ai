"""The Assistant's scripted test double: LangChain's fake chat model (`tests.fake_chat.FakeChatModel`) under the name the
Assistant tests use (ADR-0011; spec: Testing Decisions).

    model = ScriptedModel(call("look_up_portfolio", portfolio_id="C001"), {"in_scope": True, ...})

Each step answers one model request, in order: a `dict` is a reply object, a `str` is reply text, `call(name, **args)` is
a reply that calls a tool, an exception is raised by the request, and a callable takes the request and returns any of
these. The model keeps every request it received in `requests`.
"""

from fastapi import FastAPI

from tests.fake_chat import ByTask, ChatRequest, FakeChatModel, call, serve_chat

__all__ = ["ByTask", "ScriptedModel", "ScriptedRequest", "call", "serve"]

ScriptedRequest = ChatRequest


class ScriptedModel(FakeChatModel):
    """A fake chat model with the script and `then` of `FakeChatModel`."""

    def __init__(self, *steps, then=None, model_name: str = "scripted", **values) -> None:
        super().__init__(*steps, then=then, model_name=model_name, **values)


def serve[M: FakeChatModel](app: FastAPI, model: M) -> M:
    """Makes `model` the chat model the app's LLM Graphs run on, behind the capture the app serves. Returns `model`, so a
    test can read the requests it received."""
    return serve_chat(app, model)
