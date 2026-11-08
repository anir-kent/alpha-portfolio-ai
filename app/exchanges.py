"""LLM Exchange capture (ADR-0004 as amended by ADR-0010).

`CapturingLlm` wraps the LLM interface, so every call site is captured without change. It stores one immutable Exchange
per call, as soon as the reply or error is in and before the caller writes its Audit Event, and hands the Exchange id and
hash back on the response or error so the event can reference them. If the Exchange cannot be stored the call fails
closed with the existing `LlmError`: no model output exists without a record.

Every Exchange belongs to an LLM Trajectory and records its position in it. A plain call is a Trajectory of one; calls
made through a `trajectory()` view share one Trajectory and take successive positions.
"""

import dataclasses
import hashlib
import itertools
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session, sessionmaker

from app.audit import format_ts
from app.db import LlmExchangeRow
from app.llm import LlmClient, LlmError, LlmRequest, LlmResponse


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


class CapturingLlm:
    def __init__(self, inner: LlmClient, session_factory: sessionmaker, *, mode: str, endpoint_host: str | None = None):
        self.inner = inner
        self.session_factory = session_factory
        self.mode = mode
        self.endpoint_host = endpoint_host
        self._db: Session | None = None
        self._trajectory: _Trajectory | None = None

    def _view(self, *, db: Session | None, trajectory: _Trajectory | None) -> "CapturingLlm":
        view = CapturingLlm(self.inner, self.session_factory, mode=self.mode, endpoint_host=self.endpoint_host)
        view._db, view._trajectory = db, trajectory
        return view

    def bind(self, db: Session) -> "CapturingLlm":
        """A view of this client that stores Exchanges through the caller's own open session. A caller in the middle of
        a write transaction (the analysis run) needs this: a second connection could not write until it committed."""
        return self._view(db=db, trajectory=self._trajectory)

    def trajectory(self) -> "CapturingLlm":
        """A view whose calls form one new LLM Trajectory: they share its id and take positions 0, 1, 2… in call order,
        failed calls included."""
        return self._view(db=self._db, trajectory=_Trajectory())

    def _store(
        self,
        request: LlmRequest,
        *,
        response: LlmResponse | None,
        error: LlmError | None = None,
    ) -> LlmExchangeRow:
        detail = response or error  # both carry whatever transport detail the adapter knew
        assert detail is not None, "an Exchange is stored for a response or an error"
        trajectory = self._trajectory or _Trajectory()  # a call outside a Trajectory view is a Trajectory of one
        row = LlmExchangeRow(
            created_at=format_ts(datetime.now(UTC)),
            task=request.task,
            prompt_version=request.prompt_version,
            model=response.model if response else getattr(self.inner, "model", None),
            mode=self.mode,
            endpoint_host=self.endpoint_host,
            system_text=request.system,
            user_prompt=request.user,
            reply_schema_json=_canonical(request.schema),
            messages_json=_dump(detail.messages),
            raw_reply=detail.raw_reply,
            parsed_content_json=_dump(response.content if response else None),
            usage_json=_dump(detail.usage),
            latency_ms=detail.latency_ms,
            outcome="ok" if response else "error",
            error=str(error) if error else None,
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

    def complete(self, request: LlmRequest) -> LlmResponse:
        try:
            response = self.inner.complete(request)
        except LlmError as e:
            try:
                row = self._store(request, response=None, error=e)
            except Exception:
                raise LlmError(f"{e} (the failed call could not be recorded)") from e
            raise LlmError(str(e), exchange_id=row.id, exchange_hash=row.hash) from e
        try:
            row = self._store(request, response=response)
        except Exception as e:
            raise LlmError(f"LLM exchange could not be recorded: {e}") from e
        return dataclasses.replace(response, exchange_id=row.id, exchange_hash=row.hash)


def endpoint_host(settings) -> str | None:
    return urlparse(settings.llm_base_url).hostname if settings.llm_mode == "live" else None
