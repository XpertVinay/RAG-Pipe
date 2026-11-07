"""Tests for meaning-aligned system prompts, semantic intent analysis, and meaning-based similarity search."""

import pytest
from httpx import AsyncClient
from langchain_core.documents import Document as LCDocument

from app.agent.meaning import (
    MeaningProfile,
    analyze_query_meaning,
    build_meaning_aligned_grounded_prompt,
    build_meaning_aligned_ungrounded_prompt,
    extract_meaning_query,
)
from app.agent.nodes import (
    generate_grounded_answer,
    retrieve_documents,
    validate_and_classify_query,
)
from app.agent.state import AgentState


def test_analyze_query_meaning_categories():
    """Verify query meaning analysis accurately identifies intent categories and personas."""
    # 1. Technical / Code implementation
    p_tech = analyze_query_meaning("Write a python function to query postgresql and format JSON output")
    assert p_tech.intent == "technical_code"
    assert "Principal Software Architect" in p_tech.role_description
    assert "clean, syntax-highlighted blocks" in p_tech.formatting_instructions

    # 2. Comparative Analysis
    p_comp = analyze_query_meaning("Compare the pros and cons of Chroma vs PostgreSQL pgvector for RAG")
    assert p_comp.intent == "comparative_analysis"
    assert "Senior Comparative Research Analyst" in p_comp.role_description
    assert any("trade-offs" in d.lower() for d in p_comp.directives)

    # 3. Summarization & Synthesis
    p_sum = analyze_query_meaning("Give me an executive summary and key takeaways of the quarterly report")
    assert p_sum.intent == "summarization_synthesis"
    assert "Executive Intelligence Analyst" in p_sum.role_description
    assert "Executive Summary" in p_sum.directives[1]

    # 4. Troubleshooting & Diagnostics
    p_err = analyze_query_meaning("Why is the worker throwing a ConnectionResetError on RabbitMQ?")
    assert p_err.intent == "troubleshooting_diagnosis"
    assert "Senior Systems Diagnostics" in p_err.role_description
    assert "Suspected Root Cause" in p_err.formatting_instructions

    # 5. Procedural Guide
    p_guide = analyze_query_meaning("Step by step guide on how to configure Nginx reverse proxy")
    assert p_guide.intent == "procedural_guide"
    assert "Technical Implementation Specialist" in p_guide.role_description
    assert "numbered" in p_guide.formatting_instructions

    # 6. Strategic Advisory
    p_strat = analyze_query_meaning("What are the recommended best practices and strategy for risk mitigation?")
    assert p_strat.intent == "strategic_advisory"
    assert "Enterprise Solutions Principal" in p_strat.role_description

    # 7. Factual Inquiry
    p_fact = analyze_query_meaning("What was the exact date and net profit margin in clause 4.2?")
    assert p_fact.intent == "factual_inquiry"
    assert "Precision Document Auditor" in p_fact.role_description

    # 8. Creative Drafting
    p_draft = analyze_query_meaning("Draft an email to stakeholders announcing the project milestones")
    assert p_draft.intent == "creative_drafting"
    assert "Technical Writer" in p_draft.role_description


def test_extract_meaning_query_cleans_fillers():
    """Verify extract_meaning_query removes conversational padding for vector similarity search."""
    q1 = "Can you please tell me about the RabbitMQ retry queue architecture?"
    meaning_q1, concepts1 = extract_meaning_query(q1)
    assert "can you please" not in meaning_q1.lower()
    assert "rabbitmq" in meaning_q1.lower()
    assert "retry queue architecture" in meaning_q1.lower()

    q2 = "I would like to know what is the database pool size and timeout?"
    meaning_q2, concepts2 = extract_meaning_query(q2)
    assert "i would like to know" not in meaning_q2.lower()
    assert "database pool size" in meaning_q2.lower()


def test_dynamic_system_prompt_correspondence():
    """Verify system prompts are dynamically synthesized with correspondence to query meaning."""
    # Technical query
    profile_tech = analyze_query_meaning("How to implement JWT authentication in FastAPI?")
    grounded_tech_prompt = build_meaning_aligned_grounded_prompt("How to implement JWT authentication in FastAPI?", profile_tech)

    assert "Principal Software Architect" in grounded_tech_prompt
    assert "Technical Implementation" in grounded_tech_prompt
    assert "<retrieved_context>" in grounded_tech_prompt
    assert "MANDATORY ETHICAL & LEGAL GUARDRAILS" in grounded_tech_prompt
    assert "STRICT GROUNDING & VERIFICATION RULES" in grounded_tech_prompt

    # Comparison query
    profile_comp = analyze_query_meaning("What is the difference between Postgres and Chroma?")
    grounded_comp_prompt = build_meaning_aligned_grounded_prompt("What is the difference between Postgres and Chroma?", profile_comp)

    assert "Senior Comparative Research Analyst" in grounded_comp_prompt
    assert "Comparative Analysis" in grounded_comp_prompt
    assert "trade-offs" in grounded_comp_prompt.lower()

    # Ungrounded prompt correspondence
    ungrounded_prompt = build_meaning_aligned_ungrounded_prompt("Explain caching algorithms", profile_tech)
    assert "Principal Software Architect" in ungrounded_prompt
    assert "general domain principles" in ungrounded_prompt.lower()
    assert "MANDATORY ETHICAL & LEGAL GUARDRAILS" in ungrounded_prompt


@pytest.mark.asyncio
async def test_validate_and_classify_query_includes_meaning():
    """Verify validate_and_classify_query populates meaning profile and semantic intent."""
    state: AgentState = {"query": "Compare the performance of SQLite vs PostgreSQL for high concurrency"}
    res = await validate_and_classify_query(state)

    assert res["intent"] == "qa"
    assert res["semantic_intent"] == "comparative_analysis"
    assert res["semantic_intent_label"] == "Comparative Analysis"
    assert "meaning_query" in res
    assert "performance" in res["meaning_query"].lower()
    assert "sqlite" in res["meaning_query"].lower()


@pytest.mark.asyncio
async def test_retrieve_documents_uses_meaning_query():
    """Verify retrieve_documents executes meaning-based similarity search."""
    state: AgentState = {
        "query": "Can you please search and tell me what the architecture of the system is?",
        "meaning_query": "architecture of the system",
        "semantic_intent_label": "Technical Implementation",
        "top_k": 3,
        "document_ids": None,
    }

    ret_res = await retrieve_documents(state)
    assert "documents" in ret_res
    assert "citations" in ret_res
    assert "meaning_query" in ret_res
    assert ret_res["meaning_query"] == "architecture of the system"
    assert "Technical Implementation" in ret_res["status_update"]


@pytest.mark.asyncio
async def test_api_chat_query_returns_semantic_intent(client: AsyncClient):
    """Verify chat query API returns semantic intent and meaning query in metadata_info."""
    payload = {
        "message": "Summarize the key takeaways and highlights from the project document",
    }
    res = await client.post("/api/chat/query", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "metadata_info" in data
    meta = data["metadata_info"]
    assert meta.get("semantic_intent") == "summarization_synthesis"
    assert meta.get("semantic_intent_label") == "Executive Summary & Synthesis"
    assert "meaning_query" in meta


@pytest.mark.asyncio
async def test_sse_stream_emits_meaning_status_and_meta(client: AsyncClient):
    """Verify Server-Sent Events stream yields meaning-aligned status updates and metadata."""
    payload = {
        "message": "Write a python script to test postgresql connection pool",
    }
    res = await client.post("/api/chat/stream", json=payload)
    assert res.status_code == 200
    body = res.text

    # Verify status updates reflecting query meaning
    assert "event: status" in body
    assert "semantic" in body.lower() or "meaning" in body.lower()

    # Verify meta event carrying semantic intent
    assert "event: meta" in body
    assert '"semantic_intent": "technical_code"' in body
    assert '"semantic_intent_label": "Technical Implementation"' in body

    # Verify done event
    assert "event: done" in body

