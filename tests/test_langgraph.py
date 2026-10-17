"""Unit tests for LangGraph RAG Agent nodes and workflow execution."""

import pytest
from langchain_core.documents import Document as LCDocument

from app.agent.graph import rag_agent_app, route_after_grading, route_after_validation
from app.agent.nodes import (
    generate_grounded_answer,
    grade_documents,
    rewrite_query,
    validate_and_classify_query,
)
from app.agent.state import AgentState


@pytest.mark.asyncio
async def test_validate_and_classify_query():
    """Verify query validation and greeting classification."""
    # Test valid question
    state_qa: AgentState = {"query": "What is the project revenue?"}
    res_qa = await validate_and_classify_query(state_qa)
    assert res_qa["intent"] == "qa"

    # Test greeting
    state_greet: AgentState = {"query": "Hello!"}
    res_greet = await validate_and_classify_query(state_greet)
    assert res_greet["intent"] == "greeting"

    # Test blank query
    state_blank: AgentState = {"query": "   "}
    res_blank = await validate_and_classify_query(state_blank)
    assert res_blank["intent"] == "invalid"


def test_routing_logic():
    """Verify LangGraph conditional routing decisions."""
    # Validation routing
    assert route_after_validation({"intent": "greeting"}) == "generate"
    assert route_after_validation({"intent": "qa"}) == "retrieve"

    # Grading routing
    assert route_after_grading({"is_relevant": True, "retrieval_retry_count": 0, "max_retries": 2}) == "generate"
    assert route_after_grading({"is_relevant": False, "retrieval_retry_count": 0, "max_retries": 2}) == "rewrite_query"
    assert route_after_grading({"is_relevant": False, "retrieval_retry_count": 2, "max_retries": 2}) == "generate"


@pytest.mark.asyncio
async def test_rewrite_query_increments_retry_count():
    """Verify rewrite_query increments the retry counter."""
    state: AgentState = {
        "query": "financials",
        "retrieval_retry_count": 0,
        "max_retries": 2,
    }
    res = await rewrite_query(state)
    assert res["retrieval_retry_count"] == 1
    assert "query" in res


@pytest.mark.asyncio
async def test_generate_answer_with_insufficient_evidence():
    """Verify agent states insufficient information when no documents match."""
    state: AgentState = {
        "query": "What is the secret code?",
        "intent": "qa",
        "documents": [],
    }
    res = await generate_grounded_answer(state)
    assert "do not contain sufficient information" in res["answer"]


@pytest.mark.asyncio
async def test_end_to_end_graph_execution():
    """Verify full LangGraph execution from start to finish."""
    initial_state: AgentState = {
        "query": "How does the ingestion work?",
        "original_query": "How does the ingestion work?",
        "chat_history": [],
        "document_ids": None,
        "provider": "ollama",
        "model": "llama3.2",
        "temperature": 0.2,
        "top_k": 4,
        "intent": "qa",
        "documents": [],
        "citations": [],
        "retrieval_retry_count": 0,
        "max_retries": 2,
        "is_relevant": False,
        "generation_grounded": True,
        "answer": "",
        "error": None,
        "status_update": "Start",
    }

    final_state = await rag_agent_app.ainvoke(initial_state)
    assert "answer" in final_state
    assert len(final_state["answer"]) > 0
