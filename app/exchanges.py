"""LLM Exchange capture (ADR-0004 as amended by ADR-0010 and ADR-0011).

`ModelLlm`, what `build_llm` serves, is the step-facing `complete`, so every call site is captured without change. The
call runs the pipeline's LLM Graph (`app.llm_graph`) on the chat model from `get_chat_model`, with an `ExchangeCapture`
callback that stores one Exchange per model call: the messages and reply as LangChain sent and received them, usage,
latency and the Graph Node that made the call. The Assistant's agent graph (`app.assistant_agent`) runs on the same chat
model and is captured the same way, through `ModelLlm.exchange_capture` (ADR-0011).

An immutable Exchange is stored as soon as the reply or error is in and before the caller writes its Audit Event, and
the Exchange id and hash are handed back on the response or error so the event can reference them. If the Exchange
cannot be stored the call fails closed with the existing `LlmError`: no model output exists without a record.

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
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, convert_to_openai_messages
from langchain_core.outputs import LLMResult
from sqlalchemy.orm import Session, sessionmaker

from app.audit import format_ts
from app.chat_model import endpoint_host as chat_endpoint_host
from app.chat_model import get_chat_model
from app.db import LlmExchangeRow
from app.llm import LlmError, LlmRequest, LlmResponse, parse_json_reply
from app.llm_graph import run_pipeline


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
    if row.graph_node is not None:  # absent on rows written before LLM Graphs (ADR-0011)
        content.append(["graph_node", row.graph_node])
    return hashlib.sha256(_canonical(content).encode()).hexdigest()


def _dump(value) -> str | None:
    return None if value is None else _canonical(value)


STORED_MODE = "live"  # every Exchange is a live call; rows from before recorded mode was removed keep "recorded"


@dataclasses.dataclass
class _Trajectory:
    id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)
    positions: Iterator[int] = dataclasses.field(default_factory=itertools.count)


class _Capture:
    """Where and how Exchanges are stored: the session they go through and the Trajectory they join. `bind` and
    `trajectory` return views; the original is never changed, so one app-wide client serves every request."""

    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory
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

    def persist(
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
        endpoint_host: str | None = None,
        graph_node: str | None = None,
    ) -> LlmExchangeRow:
        """Stores one Exchange, the host it was sent to included (None when the chat model has no endpoint)."""
        trajectory = self._trajectory or _Trajectory()  # a call outside a Trajectory view is a Trajectory of one
        row = LlmExchangeRow(
            created_at=format_ts(datetime.now(UTC)),
            task=request.task,
            prompt_version=request.prompt_version,
            model=model,
            mode=STORED_MODE,
            endpoint_host=endpoint_host,
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
            graph_node=graph_node,
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


def _text(content: object) -> str:
    return content if isinstance(content, str) else _canonical(content)


def _json_object(text: str) -> dict | None:
    """The reply as the JSON object it holds, or None: what an Exchange keeps as parsed content."""
    try:
        return parse_json_reply(text)
    except LlmError:
        return None


class ExchangeCapture(BaseCallbackHandler):
    """A LangChain callback that stores one LLM Exchange for every chat-model call of one LLM Graph run (ADR-0011).

    `on_chat_model_start` notes the messages sent, the Graph Node (`langgraph_node` from the run metadata) and the
    start time. `on_llm_end` stores an `ok` Exchange with the reply content, its JSON object when it holds one, usage
    and latency; `on_llm_error` stores an `error` Exchange with what failed. Outcome is transport-level: a reply that
    is not JSON is still `ok`, and the step fails on it. `raise_error` makes a failed save fail the call (fail closed).
    Credentials are not in anything the callback sees; `secret` is redacted from error text all the same, since a
    provider may echo it."""

    raise_error = True

    def __init__(self, capture: "_Capture", request: LlmRequest, *, endpoint_host: str | None, secret: str = ""):
        self._capture = capture
        self._request = request
        self._endpoint_host = endpoint_host
        self._secret = secret
        self._calls: dict[UUID, dict] = {}
        self.stored: list[LlmExchangeRow] = []
        self.error: str | None = None  # what the last failed call reported, as its Exchange stores it

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        invocation = kwargs.get("invocation_params") or {}
        self._calls[run_id] = {
            "messages": convert_to_openai_messages(messages[0]),
            "graph_node": (metadata or {}).get("langgraph_node"),
            "started": time.perf_counter(),
            "model": invocation.get("model") or invocation.get("model_name"),
        }

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        call = self._calls.pop(run_id)
        message = getattr(response.generations[0][0], "message", None)
        raw_reply = _text(message.content if message is not None else response.generations[0][0].text)
        metadata = getattr(message, "response_metadata", None) or {}
        try:
            self._store(
                call,
                model=metadata.get("model_name") or metadata.get("model") or call["model"],
                raw_reply=raw_reply,
                content=_json_object(raw_reply),
                usage=getattr(message, "usage_metadata", None),
            )
        except Exception as e:
            self.error = f"LLM exchange could not be recorded: {e}"
            raise LlmError(self.error) from e

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        call = self._calls.pop(run_id, None)
        if call is None:  # the reply arrived and its save failed: `on_llm_end` already failed the call
            return
        self.error = self.redact(f"LLM call failed: {type(error).__name__}: {error}")
        try:
            self._store(call, model=call["model"], raw_reply=None, content=None, usage=None, error=self.error)
        except Exception as e:
            self.error = f"{self.error} (the failed call could not be recorded)"
            raise LlmError(self.error) from e

    def redact(self, text: str) -> str:
        return text.replace(self._secret, "[redacted]") if self._secret else text

    def _store(
        self,
        call: dict,
        *,
        model: str | None,
        raw_reply: str | None,
        content: dict | None,
        usage: Mapping[str, Any] | None,
        error: str | None = None,
    ) -> None:
        row = self._capture.persist(
            self._request,
            model=model,
            messages=call["messages"],
            raw_reply=raw_reply,
            content=content,
            usage=dict(usage) if usage else None,
            latency_ms=round((time.perf_counter() - call["started"]) * 1000),
            error=error,
            endpoint_host=self._endpoint_host,
            graph_node=call["graph_node"],
        )
        self.stored.append(row)


class ModelLlm(_Capture):
    """The step-facing `complete`: one run of the pipeline's LLM Graph on `chat_model`, captured by an `ExchangeCapture`
    callback (ADR-0011). The response and any error carry the stored Exchange's id and hash for the Audit Event.

    The chat model is built on first use from `chat_model_factory`, so the app starts without an API key; a test sets
    `chat_model` to a fake."""

    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        chat_model: BaseChatModel | None = None,
        chat_model_factory: Callable[[], BaseChatModel] | None = None,
        secret: str = "",
    ):
        super().__init__(session_factory)
        self._chat_model = chat_model
        self._chat_model_factory = chat_model_factory
        self._secret = secret

    @property
    def chat_model(self) -> BaseChatModel:
        if self._chat_model is None:
            if self._chat_model_factory is None:
                raise RuntimeError("no chat model is configured")
            self._chat_model = self._chat_model_factory()
        return self._chat_model

    @chat_model.setter
    def chat_model(self, model: BaseChatModel) -> None:
        self._chat_model = model

    def exchange_capture(self, request: LlmRequest) -> ExchangeCapture:
        """The callback that stores one Exchange per model call of an LLM Graph run, in this view's Trajectory."""
        chat_model = self.chat_model
        return ExchangeCapture(self, request, endpoint_host=chat_endpoint_host(chat_model), secret=self._secret)

    def complete(self, request: LlmRequest) -> LlmResponse:
        try:
            chat_model = self.chat_model
        except Exception as e:  # not configured (no API key): no call was made, so there is nothing to record
            raise LlmError(f"LLM call failed: {e}") from e
        capture = ExchangeCapture(self, request, endpoint_host=chat_endpoint_host(chat_model), secret=self._secret)
        try:
            content = run_pipeline(chat_model, request, [capture])
        except Exception as e:  # anchor whatever was stored: the error Exchange, or the ok one a step cannot use
            last = capture.stored[-1] if capture.stored else None
            if isinstance(e, LlmError) and e.exchange_id is None and str(e):
                message = str(e)
            else:
                message = capture.error or capture.redact(f"LLM call failed: {type(e).__name__}: {e}")
            raise LlmError(
                message,
                exchange_id=last.id if last else None,
                exchange_hash=last.hash if last else None,
                raw_reply=last.raw_reply if last else None,
            ) from e
        row = capture.stored[-1]
        return LlmResponse(
            content=content,
            model=row.model or getattr(chat_model, "model_name", None) or type(chat_model).__name__,
            prompt_version=request.prompt_version,
            exchange_id=row.id,
            exchange_hash=row.hash,
            raw_reply=row.raw_reply,
            latency_ms=row.latency_ms,
        )


def build_llm(settings, session_factory: sessionmaker, *, chat_model: BaseChatModel | None = None) -> ModelLlm:
    """The LLM the app serves, for the pipeline graph and the Assistant graph alike: `chat_model`, by default
    `get_chat_model(settings)` built on first use, with every model call captured (ADR-0004, ADR-0011)."""
    return ModelLlm(
        session_factory,
        chat_model=chat_model,
        chat_model_factory=lambda: get_chat_model(settings),
        secret=settings.llm_api_key,
    )
