"""The one provider seam (ADR-0011): `get_chat_model(settings)` is the LangChain chat model every LLM Graph runs on, and
the only module that names a provider package.

The provider comes from the base URL. An openrouter.ai URL gets the dedicated OpenRouter integration, with the app's
attribution title and `provider: {require_parameters: true}`, so OpenRouter routes only to an endpoint that honours
every parameter sent (the reply schema included). Any other URL gets the OpenAI-compatible integration with neither, so
a gateway stays a config change. SDK retries are off on both (the default is 2): every request that reaches the wire
is one the capture callback sees. Temperature is sent only when set, because some models accept none, and OpenRouter
then finds no endpoint.
"""

from urllib.parse import urlparse

import httpx
import openrouter
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from openrouter.utils import BackoffStrategy, RetryConfig

from app.llm import OPENROUTER_TITLE
from app.settings import Settings

TIMEOUT_SECONDS = 120
# `max_retries=0` alone does not turn the OpenRouter SDK's retries off: ChatOpenRouter only sets a retry config when
# max_retries > 0, and with none set the SDK's chat call backs off on 5XX and connection errors for up to an hour. So
# the SDK client is built here with retries explicitly off (ADR-0011).
_NO_RETRIES = RetryConfig("none", BackoffStrategy(0, 0, 1.0, 0), retry_connection_errors=False)


def _is_openrouter(base_url: str) -> bool:
    return urlparse(base_url).hostname == "openrouter.ai"


def _openrouter_client(settings: Settings, base_url: str) -> openrouter.OpenRouter:
    """The OpenRouter SDK client ChatOpenRouter would build (attribution header, redirects followed), with retries
    off."""
    headers = {"X-Title": OPENROUTER_TITLE}
    return openrouter.OpenRouter(
        api_key=settings.llm_api_key,
        server_url=base_url,
        client=httpx.Client(headers=headers, follow_redirects=True),
        async_client=httpx.AsyncClient(headers=headers, follow_redirects=True),
        retry_config=_NO_RETRIES,
        timeout_ms=TIMEOUT_SECONDS * 1000,
    )


def get_chat_model(settings: Settings) -> BaseChatModel:
    """The chat model `settings` configure, with SDK retries off. Raises `RuntimeError` when no API key is set."""
    if not settings.llm_api_key:
        raise RuntimeError("APP_LLM_API_KEY must be set to call the model")
    options: dict = {"api_key": settings.llm_api_key, "max_retries": 0}
    if settings.llm_temperature is not None:
        options["temperature"] = settings.llm_temperature
    if _is_openrouter(settings.llm_base_url):
        base_url = settings.llm_base_url.rstrip("/")
        return init_chat_model(
            f"openrouter:{settings.llm_model}",
            base_url=base_url,
            app_title=OPENROUTER_TITLE,
            openrouter_provider={"require_parameters": True},
            client=_openrouter_client(settings, base_url),
            **options,
        )
    return init_chat_model(
        f"openai:{settings.llm_model}", base_url=settings.llm_base_url, timeout=TIMEOUT_SECONDS, **options
    )


def endpoint_host(model: BaseChatModel) -> str | None:
    """The host `model` sends to, or None for a model with no endpoint (a test double)."""
    base_url = getattr(model, "openrouter_api_base", None) or getattr(model, "openai_api_base", None)
    return urlparse(base_url).hostname if base_url else None
