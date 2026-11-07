"""LLM Request and Response Logging Library for Non-Production Environments.

This module provides comprehensive logging of LLM inputs (prompts, messages, parameters)
and outputs (responses, tokens, latency, tool calls) specifically designed for Docker
container inspection (docker logs) in local, development, and stage environments.

CRITICAL SAFETY POLICY:
LLM Request/Response logging is strictly DISABLED on preprod and production environments
to prevent compliance violations, sensitive data exposure, and secret leakage.
"""

import functools
import inspect
import json
import logging
import os
import re
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Union

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from app.config import get_settings
from app.core.logging import logger as app_logger

# Logger instance tied to the application logger hierarchy
logger = logging.getLogger("rag_agent.llm")
logger.setLevel(logging.INFO)

# Redaction patterns for sensitive information
THREE_GROUP_PATTERNS = [
    re.compile(r"(api[-_]?key\s*[:=]\s*['\"]?)([\w\-]+)(['\"]?)", re.IGNORECASE),
    re.compile(r"(bearer\s+)([\w\-]+)()", re.IGNORECASE),
    re.compile(r"(password\s*[:=]\s*['\"]?)([^'\"\s]+)(['\"]?)", re.IGNORECASE),
    re.compile(r"(secret\s*[:=]\s*['\"]?)([^'\"\s]+)(['\"]?)", re.IGNORECASE),
]

STANDALONE_PATTERNS = [
    re.compile(r"(AIza[0-9A-Za-z-_]{35})", re.IGNORECASE),  # Google API key pattern
    re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE),   # OpenAI API key pattern
]

DISALLOWED_ENVIRONMENTS = {
    "production",
    "prod",
    "preprod",
    "pre-production",
    "pre_prod",
}


def is_llm_logging_enabled(environment: Optional[str] = None) -> bool:
    """Check if LLM logging is permitted in the current environment.

    Returns False for any production or pre-production environment.
    """
    settings = get_settings()
    if getattr(settings, "FORCE_LLM_LOGGING", False) or os.environ.get("FORCE_LLM_LOGGING", "").lower() in ("true", "1"):
        return bool(getattr(settings, "ENABLE_LLM_LOGGING", True))

    env = (environment or getattr(settings, "APP_ENV", "") or os.environ.get("APP_ENV", "development")).strip().lower()

    # Absolute blocker: Preprod and Production are NEVER allowed to log LLM payloads unless FORCE_LLM_LOGGING is set
    if env in DISALLOWED_ENVIRONMENTS:
        return False

    if not getattr(settings, "ENABLE_LLM_LOGGING", True):
        return False

    allowed_raw = getattr(settings, "LLM_LOG_ENVIRONMENTS", "local,development,dev,stage,staging,test")
    allowed = {e.strip().lower() for e in allowed_raw.split(",") if e.strip()}
    return env in allowed


def redact_sensitive_text(text: str) -> str:
    """Mask any credential patterns, tokens, or API keys from log strings."""
    if not isinstance(text, str):
        text = str(text)
    for pattern in THREE_GROUP_PATTERNS:
        text = pattern.sub(r"\1***REDACTED***\3", text)
    for pattern in STANDALONE_PATTERNS:
        text = pattern.sub(r"***REDACTED***", text)
    return text


def truncate_text(text: str, max_chars: Optional[int] = None) -> str:
    """Truncate excessively long strings while appending a clean truncation marker."""
    if not text:
        return ""
    if max_chars is None:
        settings = get_settings()
        max_chars = getattr(settings, "LLM_LOG_MAX_CHARS", 10000)

    if max_chars and max_chars > 0 and len(text) > max_chars:
        remaining = len(text) - max_chars
        return f"{text[:max_chars]}\n... [truncated {remaining} characters for log visibility]"
    return text


def format_message_content(content: Any) -> str:
    """Format message content whether it is a string, dictionary, or list."""
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        try:
            return json.dumps(content, indent=2, default=str)
        except Exception:
            return str(content)
    return str(content)


def format_messages_to_str(messages: Any, max_chars: Optional[int] = None) -> str:
    """Convert a message list, prompt string, or nested sequence into formatted text."""
    if isinstance(messages, str):
        return truncate_text(redact_sensitive_text(messages), max_chars)

    formatted_lines = []
    
    # Handle single message or flat list
    item_list = messages if isinstance(messages, (list, tuple)) else [messages]

    for item in item_list:
        if isinstance(item, (list, tuple)):
            # Nested list of messages (LangChain batching)
            for sub_item in item:
                formatted_lines.append(_format_single_item(sub_item))
        else:
            formatted_lines.append(_format_single_item(item))

    raw_text = "\n\n".join(filter(None, formatted_lines))
    return truncate_text(redact_sensitive_text(raw_text), max_chars)


def _format_single_item(item: Any) -> str:
    """Format an individual message item."""
    if isinstance(item, BaseMessage):
        role = item.__class__.__name__.replace("Message", "").upper()
        content = format_message_content(item.content)
        extra = ""
        if hasattr(item, "additional_kwargs") and item.additional_kwargs:
            extra_tools = item.additional_kwargs.get("tool_calls")
            if extra_tools:
                extra = f"\n[Tool Calls]: {json.dumps(extra_tools, indent=2, default=str)}"
        return f"[{role}]:\n{content}{extra}"
    elif isinstance(item, dict):
        role = item.get("role", "MESSAGE").upper()
        content = format_message_content(item.get("content", item))
        return f"[{role}]:\n{content}"
    elif isinstance(item, str):
        return item
    return str(item)


class LLMLogger:
    """Central logging controller for LLM requests and responses."""

    @classmethod
    def emit_log(cls, message: str, level: int = logging.INFO) -> None:
        """Log message and immediately flush stdout for realtime Docker container viewing."""
        logger.log(level, message)
        try:
            sys.stdout.flush()
        except Exception:
            pass

    @classmethod
    def log_request(
        cls,
        provider: str,
        model: str,
        prompt_or_messages: Any,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        environment: Optional[str] = None,
    ) -> str:
        """Log the outgoing request / prompt to the LLM."""
        if not is_llm_logging_enabled(environment):
            return run_id or str(uuid.uuid4())[:8]

        run_id = run_id or str(uuid.uuid4())[:8]
        settings = get_settings()
        env = environment or getattr(settings, "APP_ENV", "development")
        log_format = getattr(settings, "LLM_LOG_FORMAT", "text").lower()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        formatted_input = format_messages_to_str(prompt_or_messages)

        if log_format == "json":
            entry = {
                "event": "llm_request",
                "run_id": run_id,
                "timestamp": timestamp,
                "environment": env,
                "provider": provider,
                "model": model,
                "metadata": metadata or {},
                "input": formatted_input,
            }
            cls.emit_log(json.dumps(entry, default=str))
        else:
            meta_str = f" | Extra: {json.dumps(metadata)}" if metadata else ""
            header = f"======================== [LLM REQUEST] [Run: {run_id}] ========================"
            divider = "---------------------------------- INPUT ----------------------------------"
            footer = "=" * len(header)
            
            body = (
                f"\n{header}\n"
                f"Provider:    {provider}\n"
                f"Model:       {model}\n"
                f"Environment: {env}\n"
                f"Timestamp:   {timestamp}{meta_str}\n"
                f"{divider}\n"
                f"{formatted_input}\n"
                f"{footer}"
            )
            cls.emit_log(body)

        return run_id

    @classmethod
    def log_response(
        cls,
        run_id: str,
        output: Any,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        latency_ms: Optional[float] = None,
        usage: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        environment: Optional[str] = None,
    ) -> None:
        """Log the incoming response / generation from the LLM."""
        if not is_llm_logging_enabled(environment):
            return

        settings = get_settings()
        env = environment or getattr(settings, "APP_ENV", "development")
        log_format = getattr(settings, "LLM_LOG_FORMAT", "text").lower()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        # Extract textual output and details
        output_text = cls._extract_output_text(output)
        formatted_output = truncate_text(redact_sensitive_text(output_text))

        latency_str = ""
        if latency_ms is not None:
            latency_s = latency_ms / 1000.0
            latency_str = f"{latency_s:.2f}s ({latency_ms:.0f}ms)"
        else:
            latency_str = "N/A"

        # Token usage summary
        usage_str = cls._format_usage(usage)

        if log_format == "json":
            entry = {
                "event": "llm_response",
                "run_id": run_id,
                "timestamp": timestamp,
                "environment": env,
                "provider": provider or "unknown",
                "model": model or "unknown",
                "latency_ms": latency_ms,
                "usage": usage or {},
                "metadata": metadata or {},
                "output": formatted_output,
            }
            cls.emit_log(json.dumps(entry, default=str))
        else:
            header = f"======================== [LLM RESPONSE] [Run: {run_id}] ======================="
            divider = "--------------------------------- OUTPUT ----------------------------------"
            footer = "=" * len(header)

            body = (
                f"\n{header}\n"
                f"Provider:    {provider or 'unknown'}\n"
                f"Model:       {model or 'unknown'}\n"
                f"Environment: {env}\n"
                f"Timestamp:   {timestamp}\n"
                f"Latency:     {latency_str}\n"
                f"Token Usage: {usage_str}\n"
                f"{divider}\n"
                f"{formatted_output}\n"
                f"{footer}"
            )
            cls.emit_log(body)

    @classmethod
    def log_error(
        cls,
        run_id: str,
        error: Union[Exception, str],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        latency_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        environment: Optional[str] = None,
    ) -> None:
        """Log an LLM error or failure."""
        if not is_llm_logging_enabled(environment):
            return

        settings = get_settings()
        env = environment or getattr(settings, "APP_ENV", "development")
        log_format = getattr(settings, "LLM_LOG_FORMAT", "text").lower()
        err_type = error.__class__.__name__ if isinstance(error, Exception) else "LLMError"
        err_msg = redact_sensitive_text(str(error))
        latency_str = f"{(latency_ms / 1000.0):.2f}s ({(latency_ms):.0f}ms)" if latency_ms is not None else "N/A"

        if log_format == "json":
            entry = {
                "event": "llm_error",
                "run_id": run_id,
                "environment": env,
                "provider": provider or "unknown",
                "model": model or "unknown",
                "latency_ms": latency_ms,
                "error_type": err_type,
                "error_message": err_msg,
                "metadata": metadata or {},
            }
            cls.emit_log(json.dumps(entry, default=str), level=logging.ERROR)
        else:
            header = f"========================= [LLM ERROR] [Run: {run_id}] ========================="
            divider = "---------------------------------- ERROR ----------------------------------"
            footer = "=" * len(header)

            body = (
                f"\n{header}\n"
                f"Provider:    {provider or 'unknown'}\n"
                f"Model:       {model or 'unknown'}\n"
                f"Environment: {env}\n"
                f"Latency:     {latency_str}\n"
                f"Error Type:  {err_type}\n"
                f"{divider}\n"
                f"{err_msg}\n"
                f"{footer}"
            )
            cls.emit_log(body, level=logging.ERROR)

    @classmethod
    def _extract_output_text(cls, output: Any) -> str:
        """Extract output text from various LangChain or primitive responses."""
        if isinstance(output, str):
            return output
        if isinstance(output, BaseMessage):
            content = format_message_content(output.content)
            if hasattr(output, "additional_kwargs") and output.additional_kwargs:
                tool_calls = output.additional_kwargs.get("tool_calls")
                if tool_calls:
                    content += f"\n[Tool Calls]: {json.dumps(tool_calls, indent=2, default=str)}"
            return content
        if isinstance(output, LLMResult):
            chunks = []
            for gen_list in output.generations:
                for gen in gen_list:
                    text = gen.text
                    if not text and hasattr(gen, "message"):
                        text = format_message_content(gen.message.content)
                    chunks.append(text)
            return "\n".join(chunks)
        if isinstance(output, dict):
            return json.dumps(output, indent=2, default=str)
        return str(output)

    @classmethod
    def _format_usage(cls, usage: Optional[Dict[str, Any]]) -> str:
        """Format token usage numbers into a concise string."""
        if not usage:
            return "Not reported by provider"
        parts = []
        if "prompt_tokens" in usage:
            parts.append(f"Prompt={usage['prompt_tokens']}")
        elif "input_tokens" in usage:
            parts.append(f"Prompt={usage['input_tokens']}")

        if "completion_tokens" in usage:
            parts.append(f"Completion={usage['completion_tokens']}")
        elif "output_tokens" in usage:
            parts.append(f"Completion={usage['output_tokens']}")

        if "total_tokens" in usage:
            parts.append(f"Total={usage['total_tokens']}")

        return ", ".join(parts) if parts else str(usage)


class LLMLoggingCallbackHandler(BaseCallbackHandler):
    """LangChain CallbackHandler to log prompts, completions, streaming, and latency.

    Automatically attaches to ChatModel instances created via ModelFactory on non-prod environments.
    """

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        super().__init__()
        self.provider = provider or "unknown"
        self.model = model or "unknown"
        self._runs: Dict[str, Dict[str, Any]] = {}

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Log chat model invocation start."""
        if not is_llm_logging_enabled():
            return

        rid = str(run_id)[:8]
        provider = self.provider
        model = self.model

        # Extract model or provider from serialized dict if available
        if serialized:
            if "name" in serialized:
                provider = provider or serialized.get("name")
            kwargs_dict = serialized.get("kwargs", {})
            model = kwargs_dict.get("model_name") or kwargs_dict.get("model") or model

        self._runs[str(run_id)] = {
            "start_time": time.monotonic(),
            "provider": provider,
            "model": model,
            "stream_chunks": [],
        }

        LLMLogger.log_request(
            provider=provider,
            model=model,
            prompt_or_messages=messages,
            run_id=rid,
            metadata=metadata,
        )

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Log standard LLM invocation start."""
        if not is_llm_logging_enabled():
            return

        rid = str(run_id)[:8]
        self._runs[str(run_id)] = {
            "start_time": time.monotonic(),
            "provider": self.provider,
            "model": self.model,
            "stream_chunks": [],
        }

        LLMLogger.log_request(
            provider=self.provider,
            model=self.model,
            prompt_or_messages=prompts,
            run_id=rid,
            metadata=metadata,
        )

    def on_llm_new_token(
        self,
        token: str,
        *,
        chunk: Optional[Any] = None,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Accumulate streamed tokens so the response can be logged when stream ends."""
        run_info = self._runs.get(str(run_id))
        if run_info is not None and token:
            run_info["stream_chunks"].append(token)

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Log completion of LLM call with latency and token usage."""
        if not is_llm_logging_enabled():
            self._runs.pop(str(run_id), None)
            return

        run_info = self._runs.pop(str(run_id), {})
        start_time = run_info.get("start_time")
        latency_ms = (time.monotonic() - start_time) * 1000.0 if start_time else None

        provider = run_info.get("provider", self.provider)
        model = run_info.get("model", self.model)
        rid = str(run_id)[:8]

        # Determine output text: check LLMResult first; if empty, use accumulated streamed chunks
        output_text = LLMLogger._extract_output_text(response)
        if not output_text.strip() and run_info.get("stream_chunks"):
            output_text = "".join(run_info["stream_chunks"])

        # Extract usage stats from llm_output or message response_metadata
        usage = None
        if response.llm_output and "token_usage" in response.llm_output:
            usage = response.llm_output["token_usage"]
        elif response.generations:
            for g_list in response.generations:
                for gen in g_list:
                    msg = getattr(gen, "message", None)
                    if msg:
                        meta = getattr(msg, "response_metadata", {}) or {}
                        usage = meta.get("token_usage") or getattr(msg, "usage_metadata", None)
                        if usage:
                            break
                if usage:
                    break

        LLMLogger.log_response(
            run_id=rid,
            output=output_text,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            usage=usage,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Log error during LLM invocation."""
        run_info = self._runs.pop(str(run_id), {})
        if not is_llm_logging_enabled():
            return

        start_time = run_info.get("start_time")
        latency_ms = (time.monotonic() - start_time) * 1000.0 if start_time else None
        rid = str(run_id)[:8]

        LLMLogger.log_error(
            run_id=rid,
            error=str(error),
            provider=run_info.get("provider", self.provider),
            model=run_info.get("model", self.model),
            latency_ms=latency_ms,
        )


class LLMLogContext:
    """Context manager for tracing and logging arbitrary LLM client calls."""

    def __init__(
        self,
        provider: str,
        model: str,
        input_data: Any,
        metadata: Optional[Dict[str, Any]] = None,
        environment: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model
        self.input_data = input_data
        self.metadata = metadata or {}
        self.environment = environment
        self.run_id = str(uuid.uuid4())[:8]
        self.start_time: Optional[float] = None
        self.response: Any = None
        self.usage: Optional[Dict[str, Any]] = None

    def __enter__(self) -> "LLMLogContext":
        self.start_time = time.monotonic()
        LLMLogger.log_request(
            provider=self.provider,
            model=self.model,
            prompt_or_messages=self.input_data,
            run_id=self.run_id,
            metadata=self.metadata,
            environment=self.environment,
        )
        return self

    def set_response(self, response: Any, usage: Optional[Dict[str, Any]] = None) -> None:
        """Record the response and token usage."""
        self.response = response
        if usage:
            self.usage = usage

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        latency_ms = (time.monotonic() - self.start_time) * 1000.0 if self.start_time else None
        if exc_val is not None:
            LLMLogger.log_error(
                run_id=self.run_id,
                error=exc_val,
                provider=self.provider,
                model=self.model,
                latency_ms=latency_ms,
                environment=self.environment,
            )
        else:
            LLMLogger.log_response(
                run_id=self.run_id,
                output=self.response if self.response is not None else "[No output recorded]",
                provider=self.provider,
                model=self.model,
                latency_ms=latency_ms,
                usage=self.usage,
                metadata=self.metadata,
                environment=self.environment,
            )


def log_llm_call(
    provider: str,
    model: str,
    environment: Optional[str] = None,
) -> Callable:
    """Decorator to automatically log input parameters and returned output of LLM functions."""

    def decorator(fn: Callable) -> Callable:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                input_payload = kwargs if kwargs else args
                with LLMLogContext(
                    provider=provider,
                    model=model,
                    input_data=input_payload,
                    environment=environment,
                ) as ctx:
                    result = await fn(*args, **kwargs)
                    ctx.set_response(result)
                    return result

            return async_wrapper
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                input_payload = kwargs if kwargs else args
                with LLMLogContext(
                    provider=provider,
                    model=model,
                    input_data=input_payload,
                    environment=environment,
                ) as ctx:
                    result = fn(*args, **kwargs)
                    ctx.set_response(result)
                    return result

            return sync_wrapper

    return decorator


def get_llm_logging_callback_handler(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMLoggingCallbackHandler:
    """Factory function to instantiate an LLMLoggingCallbackHandler."""
    return LLMLoggingCallbackHandler(provider=provider, model=model)


# Direct functional shortcuts for ad-hoc logging
log_llm_request = LLMLogger.log_request
log_llm_response = LLMLogger.log_response
log_llm_error = LLMLogger.log_error
