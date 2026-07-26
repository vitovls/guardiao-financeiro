import pytest

from services.llm.bedrock_provider import BedrockProvider
from services.llm.factory import get_llm_provider
from services.llm.gemini_provider import GeminiProvider


def test_gemini_provider_selected_when_llm_provider_is_gemini(monkeypatch):
    monkeypatch.setattr("services.llm.factory.LLM_PROVIDER", "gemini")
    monkeypatch.setattr("services.llm.gemini_provider.GEMINI_API_KEY", "fake-key")

    provider = get_llm_provider()

    assert isinstance(provider, GeminiProvider)


def test_bedrock_provider_selected_when_llm_provider_is_bedrock(monkeypatch):
    monkeypatch.setattr("services.llm.factory.LLM_PROVIDER", "bedrock")

    provider = get_llm_provider()

    assert isinstance(provider, BedrockProvider)


def test_invalid_llm_provider_raises_value_error(monkeypatch):
    monkeypatch.setattr("services.llm.factory.LLM_PROVIDER", "outro")

    with pytest.raises(ValueError):
        get_llm_provider()
