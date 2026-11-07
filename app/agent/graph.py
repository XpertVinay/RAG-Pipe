"""LangGraph workflow definition for the RAG agent."""

from typing import Literal
from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    check_grounding,
    generate_grounded_answer,
    grade_documents,
    load_memory_context,
    retrieve_documents,
    rewrite_query,
    validate_and_classify_query,
)
from app.agent.state import AgentState
from app.config import get_settings

settings = get_settings()


def route_after_validation(state: AgentState) -> Literal["generate", "retrieve"]:
    """Route after validating query and loading memory: skip retrieval for greetings or safety guardrails."""
    if state.get("intent") in ["greeting", "invalid", "guardrail_blocked", "app_creation"]:
        return "generate"
    return "retrieve"


def route_after_grading(state: AgentState) -> Literal["generate", "rewrite_query"]:
    """Route after document grading: retry with rewritten query if irrelevant."""
    is_relevant = state.get("is_relevant", False)
    retries = state.get("retrieval_retry_count", 0)
    max_retries = state.get("max_retries", settings.MAX_RETRIEVAL_RETRIES)

    if not is_relevant and retries < max_retries:
        return "rewrite_query"
    return "generate"


def build_rag_graph() -> StateGraph:
    """Build and compile the LangGraph RAG workflow with memory integration."""
    workflow = StateGraph(AgentState)

    # Register nodes
    workflow.add_node("validate_query", validate_and_classify_query)
    workflow.add_node("load_memory", load_memory_context)
    workflow.add_node("retrieve", retrieve_documents)
    workflow.add_node("grade_docs", grade_documents)
    workflow.add_node("rewrite_query", rewrite_query)
    workflow.add_node("generate", generate_grounded_answer)
    workflow.add_node("check_grounding", check_grounding)

    # Set entry point
    workflow.set_entry_point("validate_query")

    # Edge from validation to memory loading
    workflow.add_edge("validate_query", "load_memory")

    # Conditional edge from memory loading (to generate for greetings, retrieve for QA)
    workflow.add_conditional_edges(
        "load_memory",
        route_after_validation,
        {
            "generate": "generate",
            "retrieve": "retrieve",
        },
    )


    # Edge from retrieve to grading
    workflow.add_edge("retrieve", "grade_docs")

    # Add conditional edge from grading
    workflow.add_conditional_edges(
        "grade_docs",
        route_after_grading,
        {
            "rewrite_query": "rewrite_query",
            "generate": "generate",
        },
    )

    # Edge from rewrite back to retrieve
    workflow.add_edge("rewrite_query", "retrieve")

    # Edge from generate to grounding check and end
    workflow.add_edge("generate", "check_grounding")
    workflow.add_edge("check_grounding", END)

    return workflow.compile()


# Compiled agent graph instance
rag_agent_app = build_rag_graph()
