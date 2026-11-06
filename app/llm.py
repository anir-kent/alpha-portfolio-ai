"""The single LLM interface (spec: OpenAI-compatible, gateway-ready, Anthropic first).

Callers only ever see `LlmClient.complete`. Two implementations sit behind it:
- `RecordedLlm` replays committed responses (tests, demos; no network). A miss is an error, never a guess.
- `OpenAICompatibleLlm` speaks the OpenAI chat-completions protocol, so pointing `llm_base_url` at Anthropic's
  compatibility endpoint or at a LiteLLM/AI gateway is a config change. With `record_dir` set, live responses are saved
  in the format `RecordedLlm` replays.
Every response carries the model and prompt version so the caller can log both to the audit chain.
"""
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

TEMPERATURE = 0.0  # reported on the governance model card


class LlmError(Exception):
    """A failed LLM call. When capture recorded the failure, `exchange_id`/`exchange_hash` point at the error Exchange."""

    def __init__(
        self, message: str = "", *, exchange_id: int | None = None, exchange_hash: str | None = None,
        messages: list[dict] | None = None, raw_reply: str | None = None, usage: dict | None = None,
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


def exchange_ref(outcome: "LlmResponse | LlmError | None") -> dict:
    """What an Audit Event carries to anchor an LLM Exchange in the chain: pass the response or the error the call
    produced. Empty if capture did not store one, so a step needs no other change to inherit capture (ADR-0004)."""
    if outcome is None or outcome.exchange_id is None:
        return {}
    return {"exchange_id": outcome.exchange_id, "exchange_hash": outcome.exchange_hash}


class LlmClient(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse: ...


def recording_key(request: LlmRequest) -> str:
    """Identity of a call: task, prompt version, exact input, system text and schema. Editing a prompt without a
    version bump therefore misses the recording instead of silently replaying a stale one."""
    parts = [request.task, request.prompt_version, request.system, json.dumps(request.schema, sort_keys=True), request.user]
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()
    return digest[:20]


def _recording_path(directory: Path, request: LlmRequest) -> Path:
    return directory / f"{request.task}-{recording_key(request)}.json"


def write_recording(directory: str | Path, request: LlmRequest, response: LlmResponse) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = _recording_path(directory, request)
    path.write_text(json.dumps(
        {"task": request.task, "prompt_version": request.prompt_version, "model": response.model,
         "content": response.content}, indent=2, sort_keys=True) + "\n")
    return path


class RecordedLlm:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def complete(self, request: LlmRequest) -> LlmResponse:
        path = _recording_path(self.directory, request)
        if not path.exists():
            raise LlmError(f"No recorded response for {request.task} ({request.prompt_version}): {path.name}")
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


class OpenAICompatibleLlm:
    def __init__(
        self, *, base_url: str, api_key: str, model: str, record_dir: str | Path | None = None,
        transport: httpx.BaseTransport | None = None, timeout: float = 120.0,
    ):
        self.model = model
        self.record_dir = record_dir
        self._api_key = api_key
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/", timeout=timeout, transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def complete(self, request: LlmRequest) -> LlmResponse:
        messages = [
            {"role": "system", "content": request.system + "\n\nJSON schema of the reply:\n" + json.dumps(request.schema)},
            {"role": "user", "content": request.user},
        ]
        body = {
            "model": self.model,
            "temperature": TEMPERATURE,
            "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": {"name": request.task, "schema": request.schema}},
        }
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
            content=content, model=payload.get("model") or self.model, prompt_version=request.prompt_version,
            messages=messages, raw_reply=reply, usage=usage, latency_ms=latency_ms)
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
            base_url=settings.llm_base_url, api_key=settings.llm_api_key, model=settings.llm_model,
            record_dir=settings.llm_recordings_dir if settings.llm_record else None, transport=transport,
        )
    raise RuntimeError(f"Unknown APP_LLM_MODE: {settings.llm_mode}")
