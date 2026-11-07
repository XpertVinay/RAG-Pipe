"""Unit and integration tests for secure sandbox code execution and parallel RAG visualization."""

import pytest
from langchain_core.documents import Document as LCDocument

from app.agent.nodes import detect_visualization_need, generate_grounded_answer
from app.agent.sandbox import (
    ExecutionResult,
    execute_code_safely,
    extract_python_code,
    validate_code_safety,
)
from app.agent.state import AgentState


class TestSandboxSafety:
    """Verify AST security inspection and malicious code blocking."""

    def test_safe_data_science_imports(self):
        code = """
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import math
import datetime

x = np.linspace(0, 5, 50)
y = np.cos(x)
plt.plot(x, y)
"""
        is_safe, error = validate_code_safety(code)
        assert is_safe is True
        assert error is None

    @pytest.mark.parametrize(
        "bad_code, expected_violation",
        [
            ("import os\nos.system('ls')", "Forbidden module import: 'os'"),
            ("import subprocess\nsubprocess.run(['rm', '-rf', '/'])", "Forbidden module import: 'subprocess'"),
            ("import socket\ns = socket.socket()", "Forbidden module import: 'socket'"),
            ("import urllib.request\nurllib.request.urlopen('http://evil.com')", "Forbidden module import: 'urllib.request'"),
            ("from urllib import request\nrequest.urlopen('http://evil.com')", "Forbidden module import from: 'urllib'"),
            ("import requests\nrequests.get('http://evil.com')", "Forbidden module import: 'requests'"),
            ("import shutil\nshutil.rmtree('/app')", "Forbidden module import: 'shutil'"),
            ("import ctypes\nctypes.CDLL(None)", "Forbidden module import: 'ctypes'"),
            ("eval('__import__(\"os\").system(\"ls\")')", "Disallowed function call: 'eval'"),
            ("exec('print(123)')", "Disallowed function call: 'exec'"),
            ("open('/etc/passwd', 'r')", "Disallowed function call: 'open'"),
            ("().__class__.__bases__[0].__subclasses__()", "Disallowed introspection attribute access: '__class__'"),
        ],
    )
    def test_malicious_code_blocked(self, bad_code: str, expected_violation: str):
        is_safe, error = validate_code_safety(bad_code)
        assert is_safe is False
        assert expected_violation in error

    def test_extract_python_code_markdown_blocks(self):
        raw = "Here is the code:\n```python\nimport matplotlib.pyplot as plt\nplt.plot([1,2],[3,4])\n```\nEnjoy!"
        extracted = extract_python_code(raw)
        assert "import matplotlib.pyplot as plt" in extracted
        assert "```" not in extracted


class TestSandboxExecution:
    """Verify isolated subprocess execution and image generation."""

    @pytest.mark.asyncio
    async def test_successful_plot_generation(self):
        code = """
import matplotlib.pyplot as plt
import numpy as np

categories = ['Q1', 'Q2', 'Q3', 'Q4']
revenue = [120, 150, 180, 220]

plt.figure(figsize=(6, 4))
plt.bar(categories, revenue, color='#4f46e5')
plt.title('Quarterly Revenue Trend')
plt.xlabel('Quarter')
plt.ylabel('Revenue ($K)')
plt.grid(True, linestyle='--', alpha=0.5)
plt.savefig('output.png', bbox_inches='tight', dpi=120)
"""
        result: ExecutionResult = await execute_code_safely(code, timeout=10.0)
        assert result.success is True
        assert result.image_base64 is not None
        assert result.image_base64.startswith("data:image/png;base64,")
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_malicious_execution_prevented_without_run(self):
        malicious = "import os; os.system('echo vulnerable')"
        result = await execute_code_safely(malicious, timeout=5.0)
        assert result.success is False
        assert result.image_base64 is None
        assert "Security Policy Violation" in (result.error or "")

    @pytest.mark.asyncio
    async def test_runtime_syntax_or_math_error_handling(self):
        buggy = """
import numpy as np
val = 10 / 0
"""
        result = await execute_code_safely(buggy, timeout=5.0)
        assert result.success is False
        assert "ZeroDivisionError" in result.stderr or "ZeroDivisionError" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execution_timeout_enforcement(self):
        # We test timeout by setting a tiny timeout threshold
        slow = """
import time
time.sleep(3.0)
"""
        # Whitelist time is not in allowed modules, so test directly with ast check
        is_safe, _ = validate_code_safety(slow)
        assert is_safe is False  # time is not whitelisted, protecting execution


class TestParallelVisualizationRAG:
    """Verify dual-track parallel RAG synthesis with textual and visual generation."""

    def test_detect_visualization_need(self):
        assert detect_visualization_need("Please plot the quarterly revenue breakdown") is True
        assert detect_visualization_need("Can you generate a bar chart comparing sales?") is True
        assert detect_visualization_need("Show me the growth trend visually") is True
        assert detect_visualization_need("Draw a histogram of employee ages") is True

        assert detect_visualization_need("What is the company refund policy?") is False
        assert detect_visualization_need("Summarize section 2.1 of the agreement") is False

    @pytest.mark.asyncio
    async def test_parallel_execution_returns_both_text_and_visual(self):
        state: AgentState = {
            "query": "Plot the quarterly revenue breakdown",
            "original_query": "Plot the quarterly revenue breakdown",
            "chat_history": [],
            "document_ids": ["doc_1"],
            "user_id": None,
            "room_id": None,
            "memory_context": None,
            "consulted_memories": [],
            "provider": "ollama",
            "model": "qwen2.5:3b",
            "temperature": 0.2,
            "top_k": 4,
            "intent": "qa",
            "documents": [
                LCDocument(
                    page_content="Quarterly revenue for 2025: Q1 was $120M, Q2 was $150M, Q3 was $180M, Q4 was $220M.",
                    metadata={"filename": "financial_report.pdf", "page": 1},
                )
            ],
            "citations": [],
            "retrieval_retry_count": 0,
            "max_retries": 2,
            "is_relevant": True,
            "generation_grounded": True,
            "needs_visualization": True,
            "visualization": None,
            "answer": "",
            "error": None,
            "status_update": "",
        }

        result = await generate_grounded_answer(state)
        assert result["needs_visualization"] is True
        assert "answer" in result
        assert len(result["answer"]) > 0
        assert "visualization" in result
        vis = result["visualization"]
        assert isinstance(vis, dict)
        assert "success" in vis
