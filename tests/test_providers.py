"""Unit tests for LLM provider abstraction and ModelFactory."""

import pytest
from app.core.exceptions import ProviderUnavailableError
from app.providers.anthropic import AnthropicChatProvider
from app.providers.gemini import GeminiChatProvider, GeminiEmbeddingProvider
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


def test_gemini_missing_key():
    """Verify Gemini provider raises error when API key is missing."""
    provider = GeminiChatProvider(api_key="")
    with pytest.raises(ProviderUnavailableError):
        provider.get_chat_model()


def test_gemini_default_model_is_gemini_2_5_flash():
    """Verify Gemini provider defaults to gemini-2.5-flash."""
    provider = GeminiChatProvider(api_key="fake-gemini-key")
    model = provider.get_chat_model()
    assert model.model == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_gemini_health_and_models():
    """Verify Gemini provider health check and available models list."""
    unconfigured = GeminiChatProvider(api_key="")
    health_unconf = await unconfigured.check_health()
    assert health_unconf["available"] is False
    assert health_unconf["status"] == "unconfigured"

    configured = GeminiChatProvider(api_key="fake-key")
    health_conf = await configured.check_health()
    assert health_conf["available"] is True
    assert health_conf["status"] == "configured"

    models = await configured.list_available_models()
    assert "gemini-2.5-flash" in models


def test_gemini_embedding_provider():
    """Verify Gemini embedding provider initialization and error handling."""
    unconfigured = GeminiEmbeddingProvider(api_key="")
    with pytest.raises(ProviderUnavailableError):
        unconfigured.get_embeddings()

    configured = GeminiEmbeddingProvider(api_key="fake-key")
    emb = configured.get_embeddings()
    assert emb.model == "models/text-embedding-004"


@pytest.mark.asyncio
async def test_providers_info():
    """Verify ModelFactory collects providers info including gemini."""
    info = await ModelFactory.get_providers_info()
    assert "chat" in info
    assert "embedding" in info
    assert len(info["chat"]) >= 4

    # Verify gemini is present with default model gemini-2.5-flash
    gemini_chat = next((p for p in info["chat"] if p.name == "gemini"), None)
    assert gemini_chat is not None
    assert gemini_chat.default_model == "gemini-2.5-flash"
    assert "gemini-2.5-flash" in gemini_chat.models
