"""Unit and integration tests for LLM Request and Response Logging library."""

import asyncio
import logging
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from langchain_community.chat_models.fake import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.config import Settings
from app.core.llm_logging import (
    LLMLogContext,
    LLMLogger,
    LLMLoggingCallbackHandler,
    format_messages_to_str,
    is_llm_logging_enabled,
    log_llm_call,
    log_llm_error,
    log_llm_request,
    log_llm_response,
    redact_sensitive_text,
    truncate_text,
)
from app.providers.factory import ModelFactory


class TestLLMLoggingEnvironmentPolicy:
    """Verify strict environment enforcement: non-prod/preprod only."""

    @pytest.mark.parametrize("env", ["development", "dev", "local", "stage", "staging", "test"])
    def test_logging_allowed_in_non_prod_environments(self, env: str):
        with patch("app.core.llm_logging.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                APP_ENV=env,
                ENABLE_LLM_LOGGING=True,
                LLM_LOG_ENVIRONMENTS="local,development,dev,stage,staging,test",
            )
            assert is_llm_logging_enabled(env) is True
            assert is_llm_logging_enabled() is True

    @pytest.mark.parametrize("env", ["production", "prod", "preprod", "pre-production", "pre_prod"])
    def test_logging_strictly_forbidden_in_prod_and_preprod(self, env: str):
        with patch("app.core.llm_logging.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                APP_ENV=env,
                ENABLE_LLM_LOGGING=True,  # Even if mistakenly set to True
                LLM_LOG_ENVIRONMENTS="production,prod,preprod,local,development",
            )
            assert is_llm_logging_enabled(env) is False
            assert is_llm_logging_enabled() is False

    def test_logging_disabled_when_flag_false(self):
        with patch("app.core.llm_logging.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                APP_ENV="development",
                ENABLE_LLM_LOGGING=False,
            )
            assert is_llm_logging_enabled("development") is False


class TestRedactionAndFormatting:
    """Verify data sanitization and message formatting."""

    def test_redact_sensitive_keys_and_tokens(self):
        raw = (
            "Connecting with api_key='sk-abcdef1234567890abcdef12' and "
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 and "
            "Google key AIzaSyDt8CW-mVcswvzqpKzYP9HFw2uqtOtN2FY and "
            "password: 'superSecretPassword123'"
        )
        redacted = redact_sensitive_text(raw)
        assert "sk-abcdef" not in redacted
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
        assert "AIzaSyDt8CW" not in redacted
        assert "superSecretPassword123" not in redacted
        assert "***REDACTED***" in redacted

    def test_truncate_text(self):
        text = "a" * 150
        truncated = truncate_text(text, max_chars=50)
        assert len(truncated.split("\n")[0]) == 50
        assert "truncated 100 characters" in truncated

    def test_format_messages_list(self):
        messages = [
            SystemMessage(content="You are an expert AI orchestrator."),
            HumanMessage(content="Explain quantum computing in one sentence."),
        ]
        formatted = format_messages_to_str(messages)
        assert "[SYSTEM]:" in formatted
        assert "You are an expert AI orchestrator." in formatted
        assert "[HUMAN]:" in formatted
        assert "Explain quantum computing" in formatted


class TestLLMLoggerDirectEmission:
    """Verify LLMLogger request, response, and error emissions."""

    def test_log_request_and_response_text_format(self, caplog):
        caplog.set_level(logging.INFO, logger="rag_agent.llm")

        with patch("app.core.llm_logging.is_llm_logging_enabled", return_value=True):
            run_id = log_llm_request(
                provider="ollama",
                model="llama3.2",
                prompt_or_messages="What is RAG architecture?",
                run_id="run-test-01",
                environment="development",
            )
            assert run_id == "run-test-01"

            log_llm_response(
                run_id="run-test-01",
                output="Retrieval Augmented Generation combines search with generation.",
                provider="ollama",
                model="llama3.2",
                latency_ms=1250.0,
                usage={"prompt_tokens": 12, "completion_tokens": 10, "total_tokens": 22},
                environment="development",
            )

        assert "LLM REQUEST" in caplog.text
        assert "LLM RESPONSE" in caplog.text
        assert "run-test-01" in caplog.text
        assert "1.25s (1250ms)" in caplog.text
        assert "Total=22" in caplog.text

    def test_log_error_emission(self, caplog):
        caplog.set_level(logging.ERROR, logger="rag_agent.llm")

        with patch("app.core.llm_logging.is_llm_logging_enabled", return_value=True):
            log_llm_error(
                run_id="err-run-99",
                error=TimeoutError("Ollama endpoint connection timed out"),
                provider="ollama",
                model="qwen2.5:3b",
                latency_ms=30000.0,
                environment="development",
            )

        assert "LLM ERROR" in caplog.text
        assert "err-run-99" in caplog.text
        assert "TimeoutError" in caplog.text
        assert "Ollama endpoint connection timed out" in caplog.text

    def test_no_emission_when_disabled(self, caplog):
        caplog.set_level(logging.INFO, logger="rag_agent.llm")

        with patch("app.core.llm_logging.is_llm_logging_enabled", return_value=False):
            log_llm_request(
                provider="openai",
                model="gpt-4o",
                prompt_or_messages="Secret confidential prompt",
                environment="production",
            )
            log_llm_response(
                run_id="prod-run",
                output="Confidential output",
                environment="production",
            )

        assert "Secret confidential prompt" not in caplog.text
        assert "Confidential output" not in caplog.text


class TestLangChainCallbackHandler:
    """Verify LLMLoggingCallbackHandler integration with LangChain models."""

    def test_callback_sync_invocation(self, caplog):
        caplog.set_level(logging.INFO, logger="rag_agent.llm")
        handler = LLMLoggingCallbackHandler(provider="fake_provider", model="fake_model")
        model = FakeListChatModel(responses=["Hello from Fake LLM"])
        model.callbacks = [handler]

        with patch("app.core.llm_logging.is_llm_logging_enabled", return_value=True):
            response = model.invoke([HumanMessage(content="Say hello")])

        assert response.content == "Hello from Fake LLM"
        assert "LLM REQUEST" in caplog.text
        assert "Say hello" in caplog.text
        assert "LLM RESPONSE" in caplog.text
        assert "Hello from Fake LLM" in caplog.text

    @pytest.mark.asyncio
    async def test_callback_async_invocation(self, caplog):
        caplog.set_level(logging.INFO, logger="rag_agent.llm")
        handler = LLMLoggingCallbackHandler(provider="fake_provider", model="fake_model")
        model = FakeListChatModel(responses=["Async result ready"])
        model.callbacks = [handler]

        with patch("app.core.llm_logging.is_llm_logging_enabled", return_value=True):
            response = await model.ainvoke([HumanMessage(content="Execute async task")])

        assert response.content == "Async result ready"
        assert "LLM REQUEST" in caplog.text
        assert "Execute async task" in caplog.text
        assert "LLM RESPONSE" in caplog.text
        assert "Async result ready" in caplog.text

    def test_callback_streaming(self, caplog):
        caplog.set_level(logging.INFO, logger="rag_agent.llm")
        handler = LLMLoggingCallbackHandler(provider="fake_provider", model="fake_model")
        model = FakeListChatModel(responses=["Streamed token stream"])
        model.callbacks = [handler]

        with patch("app.core.llm_logging.is_llm_logging_enabled", return_value=True):
            tokens = []
            for chunk in model.stream([HumanMessage(content="Stream this reply")]):
                tokens.append(chunk.content)

        assert "".join(tokens) == "Streamed token stream"
        assert "LLM REQUEST" in caplog.text
        assert "Stream this reply" in caplog.text
        assert "LLM RESPONSE" in caplog.text
        assert "Streamed token stream" in caplog.text


class TestContextManagerAndDecorator:
    """Verify LLMLogContext and @log_llm_call decorator."""

    def test_context_manager_success(self, caplog):
        caplog.set_level(logging.INFO, logger="rag_agent.llm")

        with patch("app.core.llm_logging.is_llm_logging_enabled", return_value=True):
            with LLMLogContext(
                provider="gemini",
                model="gemini-2.5-flash",
                input_data={"prompt": "Custom client query"},
                environment="stage",
            ) as ctx:
                ctx.set_response({"answer": "Context manager output"}, usage={"total_tokens": 42})

        assert "LLM REQUEST" in caplog.text
        assert "Custom client query" in caplog.text
        assert "LLM RESPONSE" in caplog.text
        assert "Context manager output" in caplog.text
        assert "Total=42" in caplog.text

    def test_context_manager_error_handling(self, caplog):
        caplog.set_level(logging.ERROR, logger="rag_agent.llm")

        with patch("app.core.llm_logging.is_llm_logging_enabled", return_value=True):
            with pytest.raises(ValueError):
                with LLMLogContext(
                    provider="openai",
                    model="gpt-4o",
                    input_data="Trigger failure",
                    environment="development",
                ):
                    raise ValueError("Simulated model rate limit error")

        assert "LLM ERROR" in caplog.text
        assert "ValueError" in caplog.text
        assert "Simulated model rate limit error" in caplog.text

    @pytest.mark.asyncio
    async def test_decorator_async_function(self, caplog):
        caplog.set_level(logging.INFO, logger="rag_agent.llm")

        @log_llm_call(provider="anthropic", model="claude-3-5-sonnet", environment="development")
        async def call_claude(prompt: str) -> str:
            await asyncio.sleep(0.01)
            return f"Claude response to: {prompt}"

        with patch("app.core.llm_logging.is_llm_logging_enabled", return_value=True):
            res = await call_claude("Hello Claude")

        assert res == "Claude response to: Hello Claude"
        assert "LLM REQUEST" in caplog.text
        assert "Hello Claude" in caplog.text
        assert "LLM RESPONSE" in caplog.text
        assert "Claude response to: Hello Claude" in caplog.text


class TestModelFactoryIntegration:
    """Verify ModelFactory automatically attaches LLMLoggingCallbackHandler on non-prod."""

    def test_factory_attaches_callback_when_enabled(self):
        with patch("app.config.Settings.is_llm_logging_enabled", new_callable=PropertyMock, return_value=True):
            chat_model = getattr(ModelFactory, "_orig_get_chat_model", ModelFactory.get_chat_model)(
                provider_name="ollama",
                model_name="qwen2.5:3b",
                streaming=False,
            )
            assert chat_model.callbacks is not None
            has_logger = any(isinstance(cb, LLMLoggingCallbackHandler) for cb in chat_model.callbacks)
            assert has_logger is True

    def test_factory_does_not_attach_callback_when_disabled(self):
        with patch("app.config.Settings.is_llm_logging_enabled", new_callable=PropertyMock, return_value=False):
            chat_model = getattr(ModelFactory, "_orig_get_chat_model", ModelFactory.get_chat_model)(
                provider_name="ollama",
                model_name="qwen2.5:3b",
                streaming=False,
            )
            callbacks = getattr(chat_model, "callbacks", None)
            if callbacks:
                has_logger = any(isinstance(cb, LLMLoggingCallbackHandler) for cb in callbacks)
                assert has_logger is False
