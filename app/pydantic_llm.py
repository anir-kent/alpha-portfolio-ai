"""The LLM layer on pydantic-ai (ADR-0010): the live Model, the transport that sees its wire bytes, and the single-call
Agent behind the step-facing `complete`.

- `build_live_model` speaks the OpenAI chat-completions protocol through pydantic-ai. An OpenRouter base URL gets the
  OpenRouter provider, its attribution title and `provider: {require_parameters: true}`; any other base URL gets the
  generic OpenAI-compatible provider with neither, so a gateway stays a config change. SDK retries are off, so every
  request that reaches the wire is one a capture wrapper sees.
- `RecordingTransport` is the `httpx` transport handed to the provider. Inside `wire_capture()` it keeps the request and
  raw reply bytes of each HTTP exchange, so capture stores what crossed the wire rather than pydantic-ai's parsed
  messages (ADR-0004 as amended).
- `ReplayModel` answers each model request from a recording keyed by `recording_key`: the task, prompt version, reply
  schema, tool definitions and the full message list so far, earlier tool calls and results included. A miss is
  `RecordingMissing`, never a guess. `RecordingModel` wraps a live Model and writes one recording per model request in
  the format `ReplayModel` reads. Both learn the task and prompt version from `tagged`, which capture wraps around
  every request.
- `run_single_call` is the single schema-bound call of ADR-0007's pipeline steps: native structured output over the
  request's JSON schema, no tools, no output retries. The step's own Pydantic model still validates the reply.

Capture itself lives in `app.exchanges`.
"""

import contextlib
import contextvars
import dataclasses
import hashlib
import json
import time
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import httpx
import pydantic_ai
from pydantic_ai import Agent, AgentRetries, NativeOutput, StructuredDict
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings

from app.llm import OPENROUTER_TITLE, LlmRequest, RecordingMissing, wire_schema

pydantic_ai.BANNER_ENABLED = False  # the glass box is the observability record (ADR-0010); no console banner


@dataclasses.dataclass
class WireExchange:
    """One HTTP request as sent, and the reply as received (absent when the transport failed)."""

    request: bytes
    status_code: int | None = None
    reply: bytes | None = None

    def request_messages(self) -> list[dict] | None:
        try:
            messages = json.loads(self.request).get("messages")
        except (ValueError, AttributeError):
            return None
        return messages if isinstance(messages, list) else None

    def reply_text(self) -> str | None:
        return None if self.reply is None else self.reply.decode("utf-8", errors="replace")

    def reply_usage(self) -> dict | None:
        try:
            usage = json.loads(self.reply or b"").get("usage")
        except (ValueError, AttributeError):
            return None
        return usage if isinstance(usage, dict) else None


@dataclasses.dataclass
class WireLog:
    """What a `RecordingTransport` saw inside one `wire_capture()`: every HTTP exchange, and the credentials sent, so
    capture can keep them out of anything it stores."""

    exchanges: list[WireExchange] = dataclasses.field(default_factory=list)
    secrets: set[str] = dataclasses.field(default_factory=set)

    def last(self) -> WireExchange | None:
        """The HTTP exchange of this model request (SDK retries are off, so there is at most one)."""
        return self.exchanges[-1] if self.exchanges else None

    def detail(self, started: float) -> dict:
        """What an Exchange stores from the wire: the request messages, the raw reply (credentials redacted), the
        provider's usage and the latency since `started`. All absent when nothing crossed a wire (a replay or test
        Model)."""
        sent = self.last()
        if sent is None:
            return {"messages": None, "raw_reply": None, "usage": None, "latency_ms": None}
        return {
            "messages": sent.request_messages(),
            "raw_reply": self.redact(sent.reply_text()),
            "usage": sent.reply_usage(),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }

    def redact(self, text: str | None) -> str | None:
        if text is None:
            return None
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        return text


_wire_log: contextvars.ContextVar[WireLog | None] = contextvars.ContextVar("wire_log", default=None)


@contextlib.contextmanager
def wire_capture() -> Iterator[WireLog]:
    """Within the block, HTTP exchanges a `RecordingTransport` makes from this task are appended to the yielded log.
    The log is per task (a context variable), so concurrent model requests never see each other's bytes."""
    log = WireLog()
    token = _wire_log.set(log)
    try:
        yield log
    finally:
        _wire_log.reset(token)


class RecordingTransport(httpx.AsyncBaseTransport):
    """Hands each request to `inner` and keeps its bytes and the raw reply bytes in the active `wire_capture()` log.

    Without an `inner`, each request goes through a fresh `httpx.AsyncHTTPTransport` that is closed afterwards: every
    `run_sync` runs its own event loop, and a pooled connection must not outlive the loop that opened it.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None, *, secret: str = ""):
        self._inner = inner
        self._secret = secret

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        log = _wire_log.get()
        body = await request.aread()
        exchange = WireExchange(request=body)
        if log is not None:
            log.exchanges.append(exchange)
            if self._secret:
                log.secrets.add(self._secret)
        response = await self._send(request)
        exchange.status_code, exchange.reply = response.status_code, response.content
        return response

    async def _send(self, request: httpx.Request) -> httpx.Response:
        if self._inner is None:
            async with httpx.AsyncHTTPTransport() as transport:
                return await _read(await transport.handle_async_request(request))
        if isinstance(self._inner, httpx.AsyncBaseTransport):
            return await _read(await self._inner.handle_async_request(request))
        return await _read(self._inner.handle_request(request))  # a sync-only test transport


async def _read(response: httpx.Response) -> httpx.Response:
    """The response with its body read in full (httpx keeps it), so the bytes are known before pydantic-ai parses
    them and the connection can close."""
    if isinstance(response.stream, httpx.AsyncByteStream):
        await response.aread()
    else:
        response.read()
    return response


def _is_openrouter(base_url: str) -> bool:
    return httpx.URL(base_url).host == "openrouter.ai"


def _profile(base: ModelProfile) -> ModelProfile:
    """The routed model's profile, told it takes native JSON-schema output and an ordinary system prompt. Gateway model
    names are not in pydantic-ai's catalogue; without this it refuses native output and prepends its own preamble."""
    return merge_profile(base, {"supports_json_schema_output": True, "supports_inline_system_prompts": True})


def build_live_model(settings, transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None) -> Model:
    """The live pydantic-ai Model for `settings`, sending through a `RecordingTransport` over `transport` (the real
    network when omitted)."""
    http_client = httpx.AsyncClient(transport=RecordingTransport(transport, secret=settings.llm_api_key), timeout=120.0)
    with warnings.catch_warnings():
        # ADR-0010 keeps legacy `httpx`, which pydantic-ai still accepts; the app and its capture are built on it.
        warnings.filterwarnings("ignore", message=r".*httpx2\.AsyncClient.*")
        # Temperature is sent only when set: some models accept none, and OpenRouter then finds no endpoint.
        common = {"max_retries": 0} | (
            {} if settings.llm_temperature is None else {"temperature": settings.llm_temperature}
        )
        if _is_openrouter(settings.llm_base_url):
            return OpenRouterModel(
                settings.llm_model,
                provider=OpenRouterProvider(
                    api_key=settings.llm_api_key, app_title=OPENROUTER_TITLE, http_client=http_client
                ),
                profile=_profile,
                settings=OpenRouterModelSettings(**common, openrouter_provider={"require_parameters": True}),
            )
        return OpenAIChatModel(
            settings.llm_model,
            provider=OpenAIProvider(
                base_url=settings.llm_base_url, api_key=settings.llm_api_key, http_client=http_client
            ),
            profile=_profile,
            settings=OpenAIChatModelSettings(**common),
        )


_tag: contextvars.ContextVar[LlmRequest | None] = contextvars.ContextVar("llm_request", default=None)


@contextlib.contextmanager
def tagged(request: LlmRequest) -> Iterator[None]:
    """Within the block, model requests from this task belong to the step call `request`: its task and prompt version
    key their recordings (ADR-0010: the task and prompt version are tagged, not read from pydantic-ai's messages)."""
    token = _tag.set(request)
    try:
        yield
    finally:
        _tag.reset(token)


def current_request() -> LlmRequest:
    """The step call the model request in progress belongs to (see `tagged`)."""
    request = _tag.get()
    if request is None:
        raise RuntimeError("a model request outside `tagged()`: its task and prompt version are unknown")
    return request


# Fields of a message or part that say when, where or under which run it happened, not what was said. They differ
# between a live run and its replay, so they are not part of a request's identity, nor kept in a recording.
_CIRCUMSTANCE = frozenset(
    {
        "timestamp",
        "run_id",
        "conversation_id",
        "provider_response_id",
        "provider_details",
        "provider_name",
        "provider_url",
        "canonical_system",
        "metadata",
        "state",
        "id",
        "usage",
        "model_name",
        "model_id",
        "finish_reason",
    }
)


def _what_was_said(messages: list[ModelMessage]) -> list[dict]:
    """The message list as content only: each message and part without its circumstances, and tool-call arguments as
    an object whether the provider sent them as text or not."""
    said = []
    for message in ModelMessagesTypeAdapter.dump_python(messages, mode="json", exclude_none=True):
        parts = []
        for part in message.get("parts", []):
            part = {k: v for k, v in part.items() if k not in _CIRCUMSTANCE}
            if part.get("part_kind") == "tool-call" and isinstance(part.get("args"), str):
                with contextlib.suppress(ValueError):  # unparseable arguments are kept as sent
                    part["args"] = json.loads(part["args"])
            parts.append(part)
        said.append({k: v for k, v in message.items() if k not in _CIRCUMSTANCE} | {"parts": parts})
    return said


def _tool(tool) -> dict:
    return {"name": tool.name, "description": tool.description, "parameters": tool.parameters_json_schema}


def recording_key(request: LlmRequest, messages: list[ModelMessage], parameters: ModelRequestParameters) -> str:
    """Identity of one model request: the step's task and prompt version, the reply schema the model is held to, the
    tool definitions (names, descriptions, parameter schemas) and every message sent so far. Any change, an earlier
    tool result included, is a different request, so it misses rather than replaying a stale continuation."""
    output = parameters.output_object
    identity = {
        "task": request.task,
        "prompt_version": request.prompt_version,
        "output_mode": parameters.output_mode,
        "reply_schema": None if output is None else {"name": output.name, "schema": output.json_schema},
        "output_tools": [_tool(t) for t in parameters.output_tools],
        "tools": [_tool(t) for t in parameters.function_tools],
        "messages": _what_was_said(messages),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def recording_path(directory: str | Path, request: LlmRequest, key: str) -> Path:
    return Path(directory) / f"{request.task}-{key}.request.json"


def write_recording(directory: str | Path, request: LlmRequest, key: str, response: ModelResponse) -> Path:
    """Saves `response` as the reply to the model request `key`: its parts, model name and usage, without the
    circumstances of the call, so re-recording an unchanged reply leaves the file unchanged."""
    path = recording_path(directory, request, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    (reply,) = ModelMessagesTypeAdapter.dump_python([response], mode="json", exclude_none=True)
    usage = {k: v for k, v in reply.get("usage", {}).items() if v}
    recording = {
        "task": request.task,
        "prompt_version": request.prompt_version,
        "model": response.model_name,
        "usage": usage,
        "parts": [{k: v for k, v in part.items() if k not in _CIRCUMSTANCE} for part in reply["parts"]],
    }
    path.write_text(json.dumps(recording, indent=2, sort_keys=True) + "\n")
    return path


def read_recording(path: Path) -> ModelResponse:
    recording = json.loads(path.read_text())
    reply = {"kind": "response", "parts": recording["parts"], "model_name": recording["model"]}
    if recording.get("usage"):
        reply["usage"] = recording["usage"]
    (response,) = ModelMessagesTypeAdapter.validate_python([reply])
    assert isinstance(response, ModelResponse)
    return response


# What the live model is told it supports (`_profile`), so an Agent over a replay prepares the same messages and asks
# for the same output mode it did live; otherwise pydantic-ai would add its own system-voice preamble and miss.
_REPLAY_PROFILE = _profile(ModelProfile(supports_json_object_output=True, supports_tools=True))


class ReplayModel(Model):
    """A Model that answers each request from its recording in `directory`, or raises `RecordingMissing` (ADR-0010).
    It makes no network call. `answered` counts the requests it replayed."""

    def __init__(self, directory: str | Path, *, model_name: str):
        super().__init__(profile=_REPLAY_PROFILE)
        self.directory = Path(directory)
        self._model_name = model_name
        self.answered = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def system(self) -> str:
        return "replay"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        request = current_request()
        path = recording_path(self.directory, request, recording_key(request, messages, model_request_parameters))
        if not path.exists():
            raise RecordingMissing(f"No recorded response for {request.task} ({request.prompt_version}): {path.name}")
        self.answered += 1
        return read_recording(path)


class RecordingModel(WrapperModel):
    """A Model that passes each request on and saves the reply as the recording `ReplayModel` answers it with."""

    def __init__(self, wrapped: Model, directory: str | Path):
        super().__init__(wrapped)
        self.directory = Path(directory)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        request = current_request()
        key = recording_key(request, messages, model_request_parameters)
        response = await super().request(messages, model_settings, model_request_parameters)
        write_recording(self.directory, request, key, response)
        return response


def run_single_call(model: Model, request: LlmRequest) -> dict:
    """The reply object of one model request for `request`: its system text (with the reply schema, as the step's
    prompt has always carried it) and user prompt, held to the schema by native structured output."""
    agent = Agent(
        model,
        instructions=request.system + "\n\nJSON schema of the reply:\n" + json.dumps(request.schema),
        output_type=NativeOutput(
            StructuredDict(cast(dict, wire_schema(request.schema)), name=request.task),
            template=False,
            strict=False,
        ),
        retries=AgentRetries(output=0),
    )
    return agent.run_sync(request.user).output
