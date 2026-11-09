"""LLM Exchange capture (ADR-0004 as amended by ADR-0010).

`ModelLlm`, what `build_llm` serves, is the step-facing `complete`, so every call site is captured without change: the
call runs on pydantic-ai over the live or replay Model (or a test's scripted Model), wrapped in `CapturingModel`, which
stores one Exchange per model request. For a live Model those are the bytes its recording transport saw on the wire; a
replay or scripted Model is captured at the model boundary. An immutable Exchange is stored as soon as the reply or
error is in and before the caller writes its Audit Event, and the Exchange id and hash are handed back on the response
or error so the event can reference them. If the Exchange cannot be stored the call fails closed with the existing
`LlmError`: no model output exists without a record.

Every Exchange belongs to an LLM Trajectory and records its position in it. A plain call is a Trajectory of one; calls
made through a `trajectory()` view share one Trajectory and take successive positions.
"""

import copy
import dataclasses
import hashlib
import itertools
import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Self
from urllib.parse import urlparse

import httpx
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from sqlalchemy.orm import Session, sessionmaker

from app.audit import format_ts
from app.db import LlmExchangeRow
from app.llm import LlmError, LlmRequest, LlmResponse, parse_json_reply
from app.pydantic_llm import (
    RecordingModel,
    ReplayModel,
    WireExchange,
    build_live_model,
    run_single_call,
    tagged,
    wire_capture,
)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _loads(text: str | None):
    return None if text is None else json.loads(text)


def exchange_digest(row: LlmExchangeRow) -> str:
    content = [
        row.created_at,
        row.task,
        row.prompt_version,
        row.model,
        row.mode,
        row.endpoint_host,
        row.system_text,
        row.user_prompt,
        json.loads(row.reply_schema_json),
        _loads(row.messages_json),
        row.raw_reply,
        _loads(row.parsed_content_json),
        _loads(row.usage_json),
        row.latency_ms,
        row.outcome,
        row.error,
    ]
    if (
        row.trajectory_id is not None or row.trajectory_position is not None
    ):  # absent on rows written before Trajectories
        content.append([row.trajectory_id, row.trajectory_position])
    return hashlib.sha256(_canonical(content).encode()).hexdigest()


def _dump(value) -> str | None:
    return None if value is None else _canonical(value)


@dataclasses.dataclass
class _Trajectory:
    id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)
    positions: Iterator[int] = dataclasses.field(default_factory=itertools.count)


class _Capture:
    """Where and how Exchanges are stored: the session they go through and the Trajectory they join. `bind` and
    `trajectory` return views; the original is never changed, so one app-wide client serves every request."""

    def __init__(self, session_factory: sessionmaker, *, mode: str, endpoint_host: str | None = None):
        self.session_factory = session_factory
        self.mode = mode
        self.endpoint_host = endpoint_host
        self._db: Session | None = None
        self._trajectory: _Trajectory | None = None

    def bind(self, db: Session) -> Self:
        """A view of this client that stores Exchanges through the caller's own open session. A caller in the middle of
        a write transaction (the analysis run) needs this: a second connection could not write until it committed."""
        view = copy.copy(self)
        view._db = db
        return view

    def trajectory(self) -> Self:
        """A view whose calls form one new LLM Trajectory: they share its id and take positions 0, 1, 2… in call order,
        failed calls included."""
        view = copy.copy(self)
        view._trajectory = _Trajectory()
        return view

    def _persist(
        self,
        request: LlmRequest,
        *,
        model: str | None,
        messages: list[dict] | None,
        raw_reply: str | None,
        content: dict | None,
        usage: dict | None,
        latency_ms: int | None,
        error: str | None,
    ) -> LlmExchangeRow:
        trajectory = self._trajectory or _Trajectory()  # a call outside a Trajectory view is a Trajectory of one
        row = LlmExchangeRow(
            created_at=format_ts(datetime.now(UTC)),
            task=request.task,
            prompt_version=request.prompt_version,
            model=model,
            mode=self.mode,
            endpoint_host=self.endpoint_host,
            system_text=request.system,
            user_prompt=request.user,
            reply_schema_json=_canonical(request.schema),
            messages_json=_dump(messages),
            raw_reply=raw_reply,
            parsed_content_json=_dump(content),
            usage_json=_dump(usage),
            latency_ms=latency_ms,
            outcome="error" if error is not None else "ok",
            error=error,
            trajectory_id=trajectory.id,
            trajectory_position=next(trajectory.positions),
            hash="",
        )
        row.hash = exchange_digest(row)
        if self._db is not None:
            with self._db.begin_nested():  # a failed write rolls back alone, leaving the caller's transaction usable
                self._db.add(row)
                self._db.flush()
            return row
        with self.session_factory() as db:
            db.add(row)
            db.commit()
        return row


def _failure_message(error: Exception, sent: WireExchange | None) -> str:
    """What failed, in the provider's terms where the wire shows them: the HTTP status and reply text for any non-2xx
    reply (a redirect included), or the transport error behind pydantic-ai's own (a timeout, a reset connection)."""
    if isinstance(error, LlmError):  # already says what failed (a replay miss)
        return str(error)
    if sent is not None and sent.status_code is not None and not 200 <= sent.status_code < 300:
        return f"LLM call failed: HTTP {sent.status_code}: {(sent.reply_text() or '')[:500]}"
    if isinstance(error, ModelHTTPError):
        return f"LLM call failed: HTTP {error.status_code}: {str(error.body or '')[:500]}"
    cause: BaseException | None = error
    while cause is not None and not isinstance(cause, httpx.HTTPError):
        cause = cause.__cause__ or cause.__context__
    error = cause if isinstance(cause, httpx.HTTPError) else error
    return f"LLM call failed: {type(error).__name__}: {error}"


class CapturingModel(WrapperModel):
    """A pydantic-ai Model that stores one LLM Exchange for every model request it passes on, as soon as the reply or
    error is known (ADR-0004 as amended by ADR-0010).

    When the request crossed a `RecordingTransport`, the Exchange's messages and raw reply are that HTTP exchange's
    bytes, with any credential the transport sent redacted. Otherwise (a replay or test Model) they come from the model
    boundary. A reply that is not a JSON object is an error Exchange that keeps the raw reply; a reply a step later
    rejects is still `ok`, since the outcome is transport-level. A failed save fails the request (fail closed)."""

    def __init__(
        self,
        wrapped: Model,
        capture: _Capture,
        request: LlmRequest,
        stored: list[LlmExchangeRow],
        *,
        capture_model_boundary: bool = False,
    ):
        super().__init__(wrapped)
        self._capture = capture
        self._llm_request = request
        self._stored = stored
        self._capture_model_boundary = capture_model_boundary

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        started = time.perf_counter()
        with tagged(self._llm_request), wire_capture() as wire:
            try:
                response = await super().request(messages, model_settings, model_request_parameters)
            except Exception as e:
                message = wire.redact(_failure_message(e, wire.last())) or ""
                detail = wire.detail(started)
                if self._capture_model_boundary and wire.last() is None:
                    detail["messages"] = ModelMessagesTypeAdapter.dump_python(messages, mode="json", exclude_none=True)
                raise self._failed(detail, message) from e
        detail = wire.detail(started)
        if self._capture_model_boundary and wire.last() is None:
            detail = {
                "messages": ModelMessagesTypeAdapter.dump_python(messages, mode="json", exclude_none=True),
                "raw_reply": response.text or ModelMessagesTypeAdapter.dump_json([response]).decode(),
                "usage": dataclasses.asdict(response.usage),
                "latency_ms": None,  # replay/scripted requests have no provider latency
            }
        if response.tool_calls:
            try:
                self._store(detail, model=response.model_name or self.wrapped.model_name)
            except Exception as e:
                raise LlmError(f"LLM exchange could not be recorded: {e}") from e
            return response
        if response.text is None:
            raise self._failed(detail, "LLM call failed: the reply's message content was not text")
        try:
            content = parse_json_reply(response.text)
        except LlmError as e:
            raise self._failed({**detail, "raw_reply": detail["raw_reply"] or response.text}, str(e)) from e
        try:
            self._store(detail, model=response.model_name or self.wrapped.model_name, content=content)
        except Exception as e:
            raise LlmError(f"LLM exchange could not be recorded: {e}") from e
        return response

    def _store(
        self, detail: dict, *, model: str | None, content: dict | None = None, error: str | None = None
    ) -> LlmExchangeRow:
        row = self._capture._persist(self._llm_request, model=model, content=content, error=error, **detail)
        self._stored.append(row)
        return row

    def _failed(self, detail: dict, message: str) -> LlmError:
        """The error to raise for a failed model request, pointing at the error Exchange now stored for it."""
        try:
            row = self._store(detail, model=self.wrapped.model_name, error=message)
        except Exception:
            return LlmError(f"{message} (the failed call could not be recorded)")
        return LlmError(message, exchange_id=row.id, exchange_hash=row.hash)


class ModelLlm(_Capture):
    """The step-facing `complete` over an injected pydantic-ai Model, wrapped in capture: one single-call Agent run per
    request (ADR-0010). The response and any error carry the stored Exchange's id and hash for the Audit Event."""

    def __init__(self, model: Model, session_factory: sessionmaker, *, mode: str, endpoint_host: str | None = None):
        super().__init__(session_factory, mode=mode, endpoint_host=endpoint_host)
        self.model = model

    def capturing_model(self, request: LlmRequest, stored: list[LlmExchangeRow]) -> CapturingModel:
        """Capture every model request of an Agent run in this view's Trajectory."""
        return CapturingModel(self.model, self, request, stored, capture_model_boundary=True)

    def complete(self, request: LlmRequest) -> LlmResponse:
        stored: list[LlmExchangeRow] = []
        try:
            content = run_single_call(CapturingModel(self.model, self, request, stored), request)
        except LlmError:
            raise
        except Exception as e:  # the framework failed after (or before) the request: anchor what was stored
            last = stored[-1] if stored else None
            raise LlmError(
                f"LLM call failed: {type(e).__name__}: {e}",
                exchange_id=last.id if last else None,
                exchange_hash=last.hash if last else None,
            ) from e
        row = stored[-1]
        return LlmResponse(
            content=content,
            model=row.model or self.model.model_name,
            prompt_version=request.prompt_version,
            exchange_id=row.id,
            exchange_hash=row.hash,
            raw_reply=row.raw_reply,
            latency_ms=row.latency_ms,
        )


def endpoint_host(settings) -> str | None:
    return urlparse(settings.llm_base_url).hostname if settings.llm_mode == "live" else None


def build_model(settings, transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None) -> Model:
    """The pydantic-ai Model `settings` select: the replay Model over the recordings directory in recorded mode, or the
    live Model (over `transport`, the network when omitted), recording each request when `llm_record` is set."""
    if settings.llm_mode == "recorded":
        return ReplayModel(settings.llm_recordings_dir, model_name=settings.llm_model)
    if settings.llm_mode == "live":
        if not settings.llm_api_key:
            raise RuntimeError("APP_LLM_API_KEY must be set when APP_LLM_MODE=live")
        live = build_live_model(settings, transport)
        return RecordingModel(live, settings.llm_recordings_dir) if settings.llm_record else live
    raise RuntimeError(f"Unknown APP_LLM_MODE: {settings.llm_mode}")


def build_llm(
    settings, session_factory: sessionmaker, transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None
) -> ModelLlm:
    """The step-facing LLM the app serves: the Model `settings` select, wrapped in capture (ADR-0004, ADR-0010)."""
    return ModelLlm(
        build_model(settings, transport), session_factory, mode=settings.llm_mode, endpoint_host=endpoint_host(settings)
    )
