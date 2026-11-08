"""The single LLM interface (spec: OpenAI-compatible, gateway-ready; OpenRouter in front of an Anthropic model).

Callers only ever see `LlmClient.complete`. Two implementations sit behind it:
- `RecordedLlm` replays committed responses (tests, demos; no network). A miss is an error, never a guess.
- `OpenAICompatibleLlm` speaks the OpenAI chat-completions protocol, so pointing `llm_base_url` at OpenRouter (the
  default), Anthropic's compatibility endpoint or a LiteLLM/AI gateway is a config change. With `record_dir` set, live responses are saved
  in the format `RecordedLlm` replays.
Every response carries the model and prompt version so the caller can log both to the audit chain.
"""

import hashlib
import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

OPENROUTER_TITLE = "Portfolio Rebalancing"  # how OpenRouter attributes the calls


class LlmError(Exception):
    """A failed LLM call. When capture recorded the failure, `exchange_id`/`exchange_hash` point at the error Exchange."""

    def __init__(
        self,
        message: str = "",
        *,
        exchange_id: int | None = None,
        exchange_hash: str | None = None,
        messages: list[dict] | None = None,
        raw_reply: str | None = None,
        usage: dict | None = None,
        latency_ms: int | None = None,
    ):
        super().__init__(message)
        self.exchange_id = exchange_id
        self.exchange_hash = exchange_hash
        # Whatever transport detail was known when the call failed (the request sent, any reply text received).
        self.messages = messages
        self.raw_reply = raw_reply
        self.usage = usage
        self.latency_ms = latency_ms


class RecordingMissing(LlmError):
    """Replay found no recording for the request: in recorded mode only recorded calls can be answered."""


@dataclass(frozen=True)
class LlmRequest:
    task: str
    prompt_version: str  # e.g. "insight_extraction@v1"
    system: str
    user: str
    schema: dict  # JSON schema of the expected reply


@dataclass(frozen=True)
class LlmResponse:
    content: dict
    model: str
    prompt_version: str
    # Set by the capture wrapper once the Exchange is stored (ADR-0004).
    exchange_id: int | None = None
    exchange_hash: str | None = None
    # Transport detail an adapter may know; absent for a replay.
    messages: list[dict] | None = None
    raw_reply: str | None = None
    usage: dict | None = None
    latency_ms: int | None = None


def exchange_ref(outcomes: "LlmResponse | LlmError | Sequence[LlmResponse | LlmError] | None") -> dict:
    """What an Audit Event carries to anchor its LLM Trajectory in the chain: an ordered `exchanges` list of
    `{exchange_id, exchange_hash}`. Pass the response or error of a single call (a list of one), or every outcome of a
    Trajectory in call order. Outcomes capture did not store are left out, and with none stored the result is empty, so
    a step needs no other change to inherit capture (ADR-0004 as amended by ADR-0010)."""
    if outcomes is None:
        outcomes = []
    elif isinstance(outcomes, LlmResponse | LlmError):
        outcomes = [outcomes]
    anchored = [
        {"exchange_id": o.exchange_id, "exchange_hash": o.exchange_hash} for o in outcomes if o.exchange_id is not None
    ]
    return {"exchanges": anchored} if anchored else {}


class LlmClient(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse: ...


def recording_key(request: LlmRequest) -> str:
    """Identity of a call: task, prompt version, exact input, system text and schema. Editing a prompt without a
    version bump therefore misses the recording instead of silently replaying a stale one."""
    parts = [
        request.task,
        request.prompt_version,
        request.system,
        json.dumps(request.schema, sort_keys=True),
        request.user,
    ]
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()
    return digest[:20]


def _recording_path(directory: Path, request: LlmRequest) -> Path:
    return directory / f"{request.task}-{recording_key(request)}.json"


def write_recording(directory: str | Path, request: LlmRequest, response: LlmResponse) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = _recording_path(directory, request)
    path.write_text(
        json.dumps(
            {
                "task": request.task,
                "prompt_version": request.prompt_version,
                "model": response.model,
                "content": response.content,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return path


class RecordedLlm:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def complete(self, request: LlmRequest) -> LlmResponse:
        path = _recording_path(self.directory, request)
        if not path.exists():
            raise RecordingMissing(f"No recorded response for {request.task} ({request.prompt_version}): {path.name}")
        data = json.loads(path.read_text())
        return LlmResponse(content=data["content"], model=data["model"], prompt_version=request.prompt_version)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_json_reply(text: str) -> dict:
    try:
        value = json.loads(_FENCE.sub("", text.strip()))
    except ValueError as e:
        raise LlmError(f"LLM reply was not valid JSON: {e}") from e
    if not isinstance(value, dict):
        raise LlmError("LLM reply was not a JSON object")
    return value


def wire_schema(schema: object) -> object:
    """The reply schema as sent to the provider: `oneOf` becomes `anyOf` and `discriminator` is dropped, because
    Anthropic's structured outputs reject both. Equivalent for this codebase's unions, whose members are told apart by
    a literal `kind`, and every reply is still validated against its Pydantic model on return."""
    if isinstance(schema, dict):
        return {("anyOf" if k == "oneOf" else k): wire_schema(v) for k, v in schema.items() if k != "discriminator"}
    if isinstance(schema, list):
        return [wire_schema(v) for v in schema]
    return schema


class OpenAICompatibleLlm:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        record_dir: str | Path | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 120.0,
        temperature: float | None = None,
    ):
        self.model = model
        self.temperature = temperature  # None: omitted, the provider's default (some models accept none)
        self.record_dir = record_dir
        self._api_key = api_key
        # OpenRouter routes a model to any of several providers, and one may ignore `response_format`; asking it to
        # require every parameter keeps the reply schema enforced. Other gateways get the plain protocol.
        self._openrouter = httpx.URL(base_url).host == "openrouter.ai"
        headers = {"Authorization": f"Bearer {api_key}"}
        if self._openrouter:
            headers["X-OpenRouter-Title"] = OPENROUTER_TITLE
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/", timeout=timeout, transport=transport, headers=headers
        )

    def complete(self, request: LlmRequest) -> LlmResponse:
        messages = [
            {
                "role": "system",
                "content": request.system + "\n\nJSON schema of the reply:\n" + json.dumps(request.schema),
            },
            {"role": "user", "content": request.user},
        ]
        body: dict = {
            "model": self.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": request.task, "schema": wire_schema(request.schema)},
            },
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self._openrouter:
            body["provider"] = {"require_parameters": True}
        started = time.perf_counter()

        def elapsed_ms() -> int:
            return round((time.perf_counter() - started) * 1000)

        def failure(message: str, *, raw_reply: str | None = None, usage: dict | None = None) -> LlmError:
            # The key travels only in the request header, but a provider can echo anything back: never keep it.
            if self._api_key:
                message = message.replace(self._api_key, "[redacted]")
                raw_reply = raw_reply.replace(self._api_key, "[redacted]") if raw_reply else raw_reply
            return LlmError(message, messages=messages, raw_reply=raw_reply, usage=usage, latency_ms=elapsed_ms())

        try:
            r = self._http.post("chat/completions", json=body)
        except httpx.HTTPError as e:
            raise failure(f"LLM call failed: {type(e).__name__}: {e}") from e
        if not r.is_success:
            raise failure(f"LLM call failed: HTTP {r.status_code}: {r.text[:500]}", raw_reply=r.text or None)
        latency_ms = elapsed_ms()
        try:
            payload = r.json()
            reply = payload["choices"][0]["message"]["content"]
            if not isinstance(reply, str):
                raise TypeError(f"message content was {type(reply).__name__}, not text")
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise failure(f"LLM call failed: unexpected reply shape ({type(e).__name__}: {e})", raw_reply=r.text) from e
        if self._api_key:
            reply = reply.replace(self._api_key, "[redacted]")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        try:
            content = parse_json_reply(reply)
        except LlmError as e:
            raise failure(str(e), raw_reply=reply, usage=usage) from e
        response = LlmResponse(
            content=content,
            model=payload.get("model") or self.model,
            prompt_version=request.prompt_version,
            messages=messages,
            raw_reply=reply,
            usage=usage,
            latency_ms=latency_ms,
        )
        if self.record_dir:
            write_recording(self.record_dir, request, response)
        return response


def build_llm(settings, transport: httpx.BaseTransport | None = None) -> LlmClient:
    if settings.llm_mode == "recorded":
        return RecordedLlm(settings.llm_recordings_dir)
    if settings.llm_mode == "live":
        if not settings.llm_api_key:
            raise RuntimeError("APP_LLM_API_KEY must be set when APP_LLM_MODE=live")
        return OpenAICompatibleLlm(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            record_dir=settings.llm_recordings_dir if settings.llm_record else None,
            transport=transport,
            temperature=settings.llm_temperature,
        )
    raise RuntimeError(f"Unknown APP_LLM_MODE: {settings.llm_mode}")
