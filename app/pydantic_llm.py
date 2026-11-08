"""The LLM layer on pydantic-ai (ADR-0010): the live Model, the transport that sees its wire bytes, and the single-call
Agent behind the step-facing `complete`.

- `build_live_model` speaks the OpenAI chat-completions protocol through pydantic-ai. An OpenRouter base URL gets the
  OpenRouter provider, its attribution title and `provider: {require_parameters: true}`; any other base URL gets the
  generic OpenAI-compatible provider with neither, so a gateway stays a config change. SDK retries are off, so every
  request that reaches the wire is one a capture wrapper sees.
- `RecordingTransport` is the `httpx` transport handed to the provider. Inside `wire_capture()` it keeps the request and
  raw reply bytes of each HTTP exchange, so capture stores what crossed the wire rather than pydantic-ai's parsed
  messages (ADR-0004 as amended).
- `run_single_call` is the single schema-bound call of ADR-0007's pipeline steps: native structured output over the
  request's JSON schema, no tools, no output retries. The step's own Pydantic model still validates the reply.

Capture itself lives in `app.exchanges`.
"""

import contextlib
import contextvars
import dataclasses
import json
import time
import warnings
from collections.abc import Iterator
from typing import cast

import httpx
import pydantic_ai
from pydantic_ai import Agent, AgentRetries, NativeOutput, StructuredDict
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.llm import OPENROUTER_TITLE, LlmRequest, wire_schema

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
