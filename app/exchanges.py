"""LLM Exchange capture (ADR-0004).

`CapturingLlm` wraps the LLM interface, so every call site is captured without change. It stores one immutable Exchange
per call, as soon as the reply or error is in and before the caller writes its Audit Event, and hands the Exchange id and
hash back on the response or error so the event can reference them. If the Exchange cannot be stored the call fails
closed with the existing `LlmError`: no model output exists without a record.
"""
import dataclasses
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import sessionmaker

from app.audit import format_ts
from app.db import LlmExchangeRow
from app.llm import LlmClient, LlmError, LlmRequest, LlmResponse


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _loads(text: str | None):
    return None if text is None else json.loads(text)


def exchange_digest(row: LlmExchangeRow) -> str:
    content = [
        row.created_at, row.task, row.prompt_version, row.model, row.mode, row.endpoint_host, row.system_text,
        row.user_prompt, json.loads(row.reply_schema_json), _loads(row.messages_json), row.raw_reply,
        _loads(row.parsed_content_json), _loads(row.usage_json), row.latency_ms, row.outcome, row.error,
    ]
    return hashlib.sha256(_canonical(content).encode()).hexdigest()


def _dump(value) -> str | None:
    return None if value is None else _canonical(value)


class CapturingLlm:
    def __init__(self, inner: LlmClient, session_factory: sessionmaker, *, mode: str, endpoint_host: str | None = None):
        self.inner = inner
        self.session_factory = session_factory
        self.mode = mode
        self.endpoint_host = endpoint_host

    def _store(
        self, request: LlmRequest, *, response: LlmResponse | None, error: LlmError | None = None,
    ) -> LlmExchangeRow:
        detail = response or error  # both carry whatever transport detail the adapter knew
        row = LlmExchangeRow(
            created_at=format_ts(datetime.now(timezone.utc)), task=request.task, prompt_version=request.prompt_version,
            model=response.model if response else getattr(self.inner, "model", None), mode=self.mode,
            endpoint_host=self.endpoint_host, system_text=request.system, user_prompt=request.user,
            reply_schema_json=_canonical(request.schema),
            messages_json=_dump(detail.messages), raw_reply=detail.raw_reply,
            parsed_content_json=_dump(response.content if response else None),
            usage_json=_dump(detail.usage), latency_ms=detail.latency_ms,
            outcome="ok" if response else "error", error=str(error) if error else None, hash="",
        )
        row.hash = exchange_digest(row)
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
