"""Seam: `get_chat_model(settings)`, the one provider seam (ADR-0011). Provider and model come from config: an
openrouter.ai base URL gets LangChain's OpenRouter integration with the app's attribution title and
`provider: {require_parameters: true}`; any other base URL gets the OpenAI-compatible integration with neither. SDK
retries are off on both, so every request that reaches the wire is one capture sees. No network."""

import ast
from pathlib import Path
from typing import Any

import pytest

from app.chat_model import endpoint_host, get_chat_model
from app.settings import Settings

APP = Path(__file__).resolve().parents[1] / "app"


def settings(**values) -> Settings:
    return Settings(_env_file=None, llm_api_key="sk-test", llm_model="anthropic/claude-sonnet-5.5", **values)


def test_an_openrouter_base_url_selects_the_openrouter_integration_with_title_and_required_parameters():
    model: Any = get_chat_model(settings(llm_base_url="https://openrouter.ai/api/v1/"))
    assert type(model).__name__ == "ChatOpenRouter"
    assert model.model_name == "anthropic/claude-sonnet-5.5"
    assert model.max_retries == 0
    assert model.app_title == "Portfolio Rebalancing"
    assert model.openrouter_provider == {"require_parameters": True}
    assert model.temperature is None
    assert endpoint_host(model) == "openrouter.ai"


def test_any_other_base_url_selects_the_openai_compatible_integration_with_no_openrouter_extras():
    model: Any = get_chat_model(settings(llm_base_url="https://gw.example/v1"))
    assert type(model).__name__ == "ChatOpenAI"
    assert model.model_name == "anthropic/claude-sonnet-5.5"
    assert model.max_retries == 0
    assert model.temperature is None
    assert "provider" not in model.model_kwargs and "extra_body" not in model.model_kwargs
    assert endpoint_host(model) == "gw.example"


@pytest.mark.parametrize("base_url", ["https://openrouter.ai/api/v1/", "https://gw.example/v1"])
def test_temperature_is_set_only_when_configured(base_url):
    model: Any = get_chat_model(settings(llm_base_url=base_url, llm_temperature=0.0))
    assert model.temperature == 0.0


def test_no_api_key_is_a_configuration_error_naming_the_setting():
    with pytest.raises(RuntimeError, match="APP_LLM_API_KEY"):
        get_chat_model(settings().model_copy(update={"llm_api_key": ""}))


def test_only_the_provider_seams_import_a_langchain_provider_package():
    importers = set()
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(
                n.split(".")[0] in {"langchain_openrouter", "langchain_openai", "openrouter", "openai"} for n in names
            ):
                importers.add(path.name)
    # `get_chat_model` for the chat model, `report_index.py` for the embeddings the Report Index uses (ADR-0012)
    assert importers <= {"chat_model.py", "report_index.py"}
