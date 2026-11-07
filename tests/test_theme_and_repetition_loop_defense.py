"""Tests verifying Theme switching controls and Stream Repetition Loop defenses."""

from typing import List
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.agent.nodes import generate_grounded_answer
from app.agent.streaming import (
    MAX_STREAMING_CHARS,
    detect_repetition_loop,
    safe_stream_tokens,
)
from app.agent.state import AgentState
from app.providers.ollama import OllamaChatProvider


def test_detect_repetition_loop_identifies_repeating_phrase():
    """Verify detect_repetition_loop catches repeated phrases and returns the cut index."""
    repeated_phrase = "In this example, we declare a variable called myVariable and assign it. "
    text = "Here is how to print a variable in JavaScript:\n" + (repeated_phrase * 4)
    cut = detect_repetition_loop(text)
    assert cut is not None
    # Truncated text contains the introductory statement and only 1 occurrence of repeated_phrase
    trimmed = text[:cut].rstrip()
    assert repeated_phrase.strip() in trimmed
    assert trimmed.count(repeated_phrase.strip()) == 1


def test_detect_repetition_loop_identifies_code_repetition():
    """Verify detect_repetition_loop catches repeated lines of code."""
    line = "print(myVariable);\n"
    text = "let myVariable = 'Hello, World!';\n" + (line * 4)
    cut = detect_repetition_loop(text)
    assert cut is not None
    trimmed = text[:cut].rstrip()
    assert trimmed.count("print(myVariable);") == 1


def test_detect_repetition_loop_ignores_normal_text_and_separators():
    """Verify normal repetitive structures (separators, natural lists) are not flagged."""
    normal_text = "This is a great question. We have item 1, item 2, and item 3 for the user."
    assert detect_repetition_loop(normal_text) is None

    separator = "=================================================="
    assert detect_repetition_loop(separator) is None

    code_sample = "let a = 1;\nlet b = 2;\nlet c = 3;\nlet d = 4;"
    assert detect_repetition_loop(code_sample) is None


@pytest.mark.asyncio
async def test_safe_stream_tokens_terminates_on_degenerate_loop():
    """Verify safe_stream_tokens terminates generator immediately when loop is detected."""
    # Simulate an LLM stream that starts repeating an identical token pattern
    tokens = [
        "To ", "print ", "a ", "variable:\n",
        "console.log(myVar);\n",
        "console.log(myVar);\n",
        "console.log(myVar);\n",
        "console.log(myVar);\n",
        "console.log(myVar);\n",
        "console.log(myVar);\n",
    ]

    class FakeChunk:
        def __init__(self, c: str):
            self.content = c

    async def fake_astream(messages):
        for t in tokens:
            yield FakeChunk(t)

    mock_chat_model = MagicMock()
    mock_chat_model.astream = fake_astream

    emitted: List[str] = []
    async for tok in safe_stream_tokens(mock_chat_model, messages=[]):
        emitted.append(tok)

    # Must terminate before emitting all 7 copies
    full_emitted_text = "".join(emitted)
    assert full_emitted_text.count("console.log(myVar);\n") < 5


@pytest.mark.asyncio
async def test_safe_stream_tokens_enforces_max_ceiling():
    """Verify safe_stream_tokens caps total characters at max_chars ceiling."""
    class FakeChunk:
        def __init__(self, c: str):
            self.content = c

    async def fake_long_stream(messages):
        # 100 tokens of 50 chars each = 5000 chars
        for i in range(100):
            yield FakeChunk(f"segment_{i}_abcdefghijklmnopqrstuvwxyz_1234567890\n")

    mock_chat_model = MagicMock()
    mock_chat_model.astream = fake_long_stream

    emitted: List[str] = []
    ceiling = 400
    async for tok in safe_stream_tokens(mock_chat_model, messages=[], max_chars=ceiling):
        emitted.append(tok)

    total_chars = sum(len(t) for t in emitted)
    assert total_chars >= ceiling
    # Should not run all 100 chunks (~5000 chars)
    assert total_chars < 1000


def test_ollama_provider_includes_repetition_and_ceiling_defaults(monkeypatch):
    """Verify OllamaChatProvider includes repeat_penalty, repeat_last_n, and num_predict defaults."""
    provider = OllamaChatProvider(base_url="http://localhost:11434")

    # Mock ChatOllama to inspect kwargs passed
    mock_chat_ollama_cls = MagicMock()
    monkeypatch.setattr("app.providers.ollama.ChatOllama", mock_chat_ollama_cls)

    provider.get_chat_model(model_name="qwen:0.5b", temperature=0.2, streaming=True)

    assert mock_chat_ollama_cls.called
    call_kwargs = mock_chat_ollama_cls.call_args[1]
    assert call_kwargs.get("repeat_penalty") == 1.18
    assert call_kwargs.get("repeat_last_n") == 64
    assert call_kwargs.get("num_predict") == 2048
    assert call_kwargs.get("top_p") == 0.9


@pytest.mark.asyncio
async def test_stream_mode_skips_redundant_sync_llm_execution(monkeypatch):
    """Verify generate_grounded_answer returns immediately when stream_mode=True, avoiding double LLM execution."""
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock()
    monkeypatch.setattr("app.providers.factory.ModelFactory.get_chat_model", lambda **kw: mock_model)

    state: AgentState = {
        "query": "What is Python?",
        "original_query": "What is Python?",
        "conversation_id": "test-conv",
        "chat_history": [],
        "document_ids": [],
        "provider": "ollama",
        "model": "qwen:0.5b",
        "temperature": 0.2,
        "top_k": 4,
        "intent": "qa",
        "semantic_intent": None,
        "semantic_intent_label": None,
        "meaning_query": None,
        "meaning_profile": None,
        "documents": [],
        "citations": [],
        "retrieval_retry_count": 0,
        "max_retries": 2,
        "is_relevant": False,
        "generation_grounded": False,
        "needs_visualization": False,
        "visualization": None,
        "answer": "",
        "error": None,
        "status_update": "",
        "stream_mode": True,
    }

    result = await generate_grounded_answer(state)
    # model.ainvoke MUST NOT be called because stream_mode is True
    assert not mock_model.ainvoke.called
    assert result.get("answer") == ""
    assert "Streaming" in result.get("status_update", "")


def test_chat_html_theme_buttons_contain_required_classes():
    """Verify chat.html contains .theme-option class on all profile theme choice buttons."""
    from pathlib import Path
    chat_html_path = Path(__file__).resolve().parent.parent / "app" / "templates" / "components" / "chat.html"
    content = chat_html_path.read_text(encoding="utf-8")

    assert 'class="profile-theme-btn theme-option active" data-theme-choice="system"' in content
    assert 'class="profile-theme-btn theme-option" data-theme-choice="dark"' in content
    assert 'class="profile-theme-btn theme-option" data-theme-choice="cyber"' in content
    assert 'class="profile-theme-btn theme-option" data-theme-choice="sunset"' in content
    assert 'class="profile-theme-btn theme-option" data-theme-choice="light"' in content

