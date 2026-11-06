"""What the server-sent event streams (LLM Exchanges, Analysis Runs) share: the keepalive interval, how a `Last-Event-ID`
is read, and the response that carries the events."""

from collections.abc import Iterator

from fastapi.responses import StreamingResponse

KEEPALIVE_SECONDS = 15.0


def last_event_number(header: str | None) -> int | None:
    """The `Last-Event-ID` a reconnecting browser sends, as a number; None when absent or not a number."""
    raw = (header or "").strip()
    return int(raw) if raw.isascii() and raw.isdigit() else None


def event_stream(events: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
