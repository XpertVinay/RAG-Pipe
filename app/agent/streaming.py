"""Server-Sent Events streaming handler for real-time RAG responses."""

import json
from typing import Any, AsyncGenerator, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.graph import rag_agent_app
from app.agent.prompts import GROUNDED_RAG_SYSTEM_PROMPT, GROUNDED_RAG_USER_PROMPT
from app.agent.state import AgentState
from app.core.logging import logger
from app.core.security import sanitize_retrieved_text
from app.memory.manager import memory_manager
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
    user_id: Optional[str] = None,
    room_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    top_k: int = 4,
    user_role: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Execute LangGraph RAG workflow and yield Server-Sent Events."""
    chat_history = chat_history or []
    yield format_sse("status", {"message": "Analyzing query and intent..."})

    initial_state: AgentState = {
        "query": query,
        "original_query": query,
        "chat_history": chat_history,
        "document_ids": document_ids,
        "user_id": user_id,
        "room_id": room_id,
        "memory_context": None,
        "consulted_memories": [],
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
        is_relevant = final_state.get("is_relevant", False)
        retrieval_retry_count = final_state.get("retrieval_retry_count", 0)
        generation_grounded = final_state.get("generation_grounded", True)

        # Classify response style differentiator
        if intent == "greeting":
            response_type = "greeting"
        elif not documents or not is_relevant:
            response_type = "insufficient_info"
        elif citations_list:
            response_type = "grounded"
        else:
            response_type = "general"

        consulted_memories = final_state.get("consulted_memories", [])
        is_admin_or_staff = user_role in ("admin", "staff", "staffs")
        visible_consulted_memories = consulted_memories if is_admin_or_staff else []

        meta_payload = {
            "response_type": response_type,
            "intent": intent,
            "has_citations": len(citations_list) > 0,
            "citation_count": len(citations_list),
            "consulted_memories_count": len(visible_consulted_memories),
            "consulted_memories": visible_consulted_memories,
            "retrieval_retry_count": retrieval_retry_count,
            "generation_grounded": generation_grounded,
            "provider": provider,
            "model": model,
        }
        yield format_sse("meta", meta_payload)

        yield format_sse("status", {"message": "Synthesizing answer from verified evidence..."})

        chat_model = ModelFactory.get_chat_model(
            provider_name=provider,
            model_name=model,
            temperature=temperature,
            streaming=True,
        )

        memory_context = final_state.get("memory_context")

        if intent == "greeting":
            greeting_messages = [SystemMessage(content=GROUNDED_RAG_SYSTEM_PROMPT)]
            if memory_context:
                greeting_messages.append(SystemMessage(content=memory_context))
            greeting_messages.append(HumanMessage(content=query))

            async for chunk in chat_model.astream(greeting_messages):
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
            if memory_context:
                messages.append(SystemMessage(content=memory_context))

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

        # Consolidate interaction into short-term / long-term memory
        try:
            await memory_manager.consolidate_interaction(
                query=query,
                answer=accumulated_answer,
                user_id=user_id,
                room_id=room_id,
                document_ids=document_ids,
            )
        except Exception as mem_err:
            logger.warning(f"Streaming memory consolidation skipped: {mem_err}")

        # Save assistant message with citations and rich differentiator metadata to database
        if conversation_id and accumulated_answer:
            try:
                from app import database
                async with database.AsyncSessionLocal() as db:
                    assistant_msg = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=accumulated_answer,
                        citations=citations_list,
                        metadata_info=meta_payload,
                    )
                    db.add(assistant_msg)
                    await db.commit()

                    if user_id:
                        try:
                            await memory_manager.record_chat_turn_memory(
                                user_id=user_id,
                                room_id=room_id,
                                conversation_id=conversation_id,
                                query=query,
                                answer=accumulated_answer,
                                db=db,
                            )
                        except Exception as mem_err:
                            logger.warning(f"Note during streaming chat STM/LTM persistence: {mem_err}")
            except Exception as e:
                logger.error(f"Failed to persist assistant message to database: {e}")

        yield format_sse("done", {
            "answer": accumulated_answer,
            "citations": citations_list,

            "conversation_id": conversation_id,
            "response_type": response_type,
            "intent": intent,
            "retrieval_retry_count": retrieval_retry_count,
            "generation_grounded": generation_grounded,
            "provider": provider,
            "model": model,
        })

    except Exception as e:
        logger.error(f"Error during RAG streaming: {e}", exc_info=True)
        user_safe_error = "An error occurred while generating the answer. Please verify your model settings or try again."
        yield format_sse("error", {"message": user_safe_error})
        yield format_sse("done", {
            "answer": user_safe_error,
            "citations": [],
            "conversation_id": conversation_id,
            "response_type": "error",
            "intent": "error",
            "provider": provider,
            "model": model,
        })
