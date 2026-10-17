"""Server-Sent Events streaming handler for real-time RAG responses."""

import json
from typing import Any, AsyncGenerator, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.graph import rag_agent_app
from app.agent.prompts import GROUNDED_RAG_SYSTEM_PROMPT, GROUNDED_RAG_USER_PROMPT
from app.agent.state import AgentState
from app.core.logging import logger
from app.core.security import sanitize_retrieved_text
from app import database
from app.models.conversation import Message
from app.providers.factory import ModelFactory
from app.schemas.chat import Citation


def format_sse(event: str, data: Any) -> str:
    """Format data as a Server-Sent Event."""
    json_data = json.dumps(data)
    return f"event: {event}\ndata: {json_data}\n\n"


async def stream_rag_agent(
    query: str,
    conversation_id: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    document_ids: Optional[List[str]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    top_k: int = 4,
) -> AsyncGenerator[str, None]:
    """Execute LangGraph RAG workflow and yield Server-Sent Events."""
    chat_history = chat_history or []
    yield format_sse("status", {"message": "Analyzing query and intent..."})

    initial_state: AgentState = {
        "query": query,
        "original_query": query,
        "chat_history": chat_history,
        "document_ids": document_ids,
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "top_k": top_k,
        "intent": "qa",
        "documents": [],
        "citations": [],
        "retrieval_retry_count": 0,
        "max_retries": 2,
        "is_relevant": False,
        "generation_grounded": True,
        "answer": "",
        "error": None,
        "status_update": "Starting workflow",
    }

    citations_list: List[Dict[str, Any]] = []
    accumulated_answer: str = ""

    try:
        yield format_sse("status", {"message": "Retrieving relevant context from indexed documents..."})

        # Run workflow up to retrieval & evaluation
        final_state = await rag_agent_app.ainvoke(initial_state)

        citations_list = [
            c.model_dump() if isinstance(c, Citation) else c
            for c in final_state.get("citations", [])
        ]

        if citations_list:
            yield format_sse("citations", {"citations": citations_list})

        intent = final_state.get("intent", "qa")
        documents = final_state.get("documents", [])

        yield format_sse("status", {"message": "Synthesizing answer from verified evidence..."})

        chat_model = ModelFactory.get_chat_model(
            provider_name=provider,
            model_name=model,
            temperature=temperature,
            streaming=True,
        )

        if intent == "greeting":
            async for chunk in chat_model.astream([
                SystemMessage(content=GROUNDED_RAG_SYSTEM_PROMPT),
                HumanMessage(content=query),
            ]):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                accumulated_answer += token
                yield format_sse("token", {"token": token})

        elif not documents:
            msg = "The provided documents do not contain sufficient information to answer this question. Please upload relevant files or check your query."
            accumulated_answer = msg
            for word in msg.split(" "):
                yield format_sse("token", {"token": word + " "})

        else:
            # Format context with explicit separation and sanitization
            formatted_contexts = []
            for i, doc in enumerate(documents):
                meta = doc.metadata or {}
                source_name = meta.get("filename", f"document_{i+1}")
                page_num = meta.get("page", 1)
                cleaned = sanitize_retrieved_text(doc.page_content)
                formatted_contexts.append(f"--- Source: {source_name} (Page {page_num}) ---\n{cleaned}")

            context_str = "\n\n".join(formatted_contexts)

            messages = [SystemMessage(content=GROUNDED_RAG_SYSTEM_PROMPT)]
            for hist in chat_history[-4:]:
                if hist.get("role") == "user":
                    messages.append(HumanMessage(content=hist.get("content", "")))
                elif hist.get("role") == "assistant":
                    messages.append(SystemMessage(content=f"Previous assistant answer: {hist.get('content', '')}"))

            user_prompt = GROUNDED_RAG_USER_PROMPT.format(query=query, context=context_str)
            messages.append(HumanMessage(content=user_prompt))

            async for chunk in chat_model.astream(messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                accumulated_answer += token
                yield format_sse("token", {"token": token})

        # Save assistant message with citations to database
        if conversation_id and accumulated_answer:
            try:
                async with database.AsyncSessionLocal() as db:
                    assistant_msg = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=accumulated_answer,
                        citations=citations_list,
                        metadata_info={"provider": provider, "model": model},
                    )
                    db.add(assistant_msg)
                    await db.commit()
            except Exception as e:
                logger.error(f"Failed to persist assistant message to database: {e}")

        yield format_sse("done", {
            "answer": accumulated_answer,
            "citations": citations_list,
            "conversation_id": conversation_id,
        })

    except Exception as e:
        logger.error(f"Error during RAG streaming: {e}", exc_info=True)
        user_safe_error = "An error occurred while generating the answer. Please verify your model settings or try again."
        yield format_sse("error", {"message": user_safe_error})
        yield format_sse("done", {
            "answer": user_safe_error,
            "citations": [],
            "conversation_id": conversation_id,
        })
