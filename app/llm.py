"""The single LLM interface (spec: OpenAI-compatible, gateway-ready; OpenRouter in front of an Anthropic model).

Callers only ever see `LlmClient.complete`, its request and response, and its errors. What the app serves behind it is
`app.exchanges.build_llm`: pydantic-ai over the live or replay Model, wrapped in capture (ADR-0010). Every response
carries the model and prompt version so the caller can log both to the audit chain.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

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
