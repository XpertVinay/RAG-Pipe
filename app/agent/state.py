"""LangGraph Agent State definition."""

from typing import Annotated, Any, Dict, List, Optional
from typing_extensions import TypedDict
from langchain_core.documents import Document as LCDocument

from app.schemas.chat import Citation


class AgentState(TypedDict):
    """Internal state passed across nodes in the LangGraph workflow."""

    query: str
    original_query: str
    chat_history: List[Dict[str, str]]
    document_ids: Optional[List[str]]
    provider: Optional[str]
    model: Optional[str]
    temperature: float
    top_k: int
    intent: str  # "qa", "greeting", "clarification"
    documents: List[LCDocument]
    citations: List[Citation]
    retrieval_retry_count: int
    max_retries: int
    is_relevant: bool
    generation_grounded: bool
    user_id: Optional[str]
    room_id: Optional[str]
    memory_context: Optional[str]
    consulted_memories: Optional[List[Dict[str, Any]]]
    answer: str
    error: Optional[str]
    status_update: Optional[str]
    needs_visualization: bool
    visualization: Optional[Dict[str, Any]]
    is_app_creation: Optional[bool]
    suggested_app_name: Optional[str]
