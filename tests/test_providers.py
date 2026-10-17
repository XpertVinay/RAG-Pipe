"""Unit tests for LLM provider abstraction and ModelFactory."""

import pytest
from app.core.exceptions import ProviderUnavailableError
from app.providers.anthropic import AnthropicChatProvider
from app.providers.factory import ModelFactory
from app.providers.ollama import OllamaChatProvider
from app.providers.openai import OpenAIChatProvider


def test_unsupported_provider(monkeypatch):
    """Verify requesting an unknown provider raises ProviderUnavailableError."""
    # Reset monkeypatch for this specific test
    monkeypatch.undo()
    with pytest.raises(ProviderUnavailableError):
        ModelFactory.get_chat_model(provider_name="nonexistent_llm")


def test_openai_missing_key():
    """Verify OpenAI provider raises error when API key is missing."""
    provider = OpenAIChatProvider(api_key=None, base_url="https://api.openai.com/v1")
    with pytest.raises(ProviderUnavailableError):
        provider.get_chat_model()


def test_anthropic_missing_key():
    """Verify Anthropic provider raises error when API key is missing."""
    provider = AnthropicChatProvider(api_key=None)
    with pytest.raises(ProviderUnavailableError):
        provider.get_chat_model()


@pytest.mark.asyncio
async def test_providers_info():
    """Verify ModelFactory collects providers info."""
    info = await ModelFactory.get_providers_info()
    assert "chat" in info
    assert "embedding" in info
    assert len(info["chat"]) >= 3
