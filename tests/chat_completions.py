"""Chat-completions replies as a provider sends them, for tests of the live chat model against a stand-in provider
(ADR-0011)."""

import httpx

REPLY_TEXT = '{"insights": []}'


def completion(content=REPLY_TEXT, **extra) -> httpx.Response:
    """A chat-completions reply as OpenRouter sends it (its SDK requires `provider` and `system_fingerprint`)."""
    return httpx.Response(
        200,
        json={
            "id": "gen-1",
            "object": "chat.completion",
            "created": 1,
            "model": "anthropic/claude-sonnet-5.5",
            "provider": "Anthropic",
            "system_fingerprint": None,
            "usage": {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366},
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            **extra,
        },
    )
