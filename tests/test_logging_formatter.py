"""Unit tests for RedactingFormatter, JSONLFormatter, and redact_sensitive_string in app.core.logging."""

import json
import logging
from app.core.logging import JSONLFormatter, RedactingFormatter, redact_sensitive_string


def test_redact_sensitive_string_various_patterns():
    # 3-group pattern
    text_api_key = "Connected with api-key: my-secret-api-key-123 to service"
    redacted = redact_sensitive_string(text_api_key)
    assert "my-secret-api-key-123" not in redacted
    assert "***REDACTED***" in redacted

    # 1-group pattern (Razorpay live / test) - previously raised re.error invalid group reference 3
    text_rzp = "Payment initialized with key rzp_live_998877665544332211"
    redacted_rzp = redact_sensitive_string(text_rzp)
    assert "rzp_live_998877665544332211" not in redacted_rzp
    assert "***REDACTED***" in redacted_rzp

    # Standalone keys like OpenAI
    text_openai = "Using model with sk-12345678901234567890abcdef"
    redacted_openai = redact_sensitive_string(text_openai)
    assert "sk-12345678901234567890abcdef" not in redacted_openai
    assert "***REDACTED***" in redacted_openai


def test_redacting_formatter_format():
    formatter = RedactingFormatter(fmt="%(levelname)s: %(message)s")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Processing rzp_live_ABC123456XYZ with bearer token_123456",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert "rzp_live_ABC123456XYZ" not in formatted
    assert "token_123456" not in formatted
    assert "***REDACTED***" in formatted


def test_jsonl_formatter_format():
    formatter = JSONLFormatter()
    record = logging.LogRecord(
        name="audit",
        level=logging.INFO,
        pathname=__file__,
        lineno=20,
        msg={"action": "checkout", "token": "rzp_test_secret998877", "key": "password: super_secret_pass"},
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    parsed = json.loads(formatted)
    assert "super_secret_pass" not in formatted
    assert "rzp_test_secret998877" not in formatted
    assert "***REDACTED***" in formatted
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "audit"
