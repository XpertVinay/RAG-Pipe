"""Server-Sent Events streaming handler for real-time RAG responses."""

import asyncio
import json
import re
from typing import Any, AsyncGenerator, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from app.services.guardrail_service import guardrail_service

from app.agent.graph import rag_agent_app
from app.agent.nodes import detect_visualization_need
from app.agent.prompts import (
    GROUNDED_RAG_SYSTEM_PROMPT,
    GROUNDED_RAG_USER_PROMPT,
    UNGROUNDED_SENSIBLE_SYSTEM_PROMPT,
)
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
        "needs_visualization": False,
        "visualization": None,
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

        if intent == "guardrail_blocked":
            refusal_ans = final_state.get("answer", "Safety policy refusal: Prohibited inquiry blocked.")
            meta_payload = {
                "response_type": "guardrail_violation",
                "intent": "guardrail_blocked",
                "guardrail_blocked": True,
                "has_citations": False,
                "citation_count": 0,
                "consulted_memories_count": 0,
                "consulted_memories": [],
                "retrieval_retry_count": 0,
                "generation_grounded": True,
                "has_visualization": False,
                "visualization": None,
                "provider": provider,
                "model": model,
                "guardrail_alert": "Safety Guardrail: Request blocked. Repeated violations may result in account termination and reporting to authorities.",
            }
            yield format_sse("status", {"message": "Safety Guardrail triggered: Prohibited inquiry blocked."})
            yield format_sse("meta", meta_payload)
            chunk_size = 4
            for i in range(0, len(refusal_ans), chunk_size):
                yield format_sse("token", {"token": refusal_ans[i:i+chunk_size]})
                await asyncio.sleep(0.01)

            if conversation_id:
                try:
                    from app import database
                    async with database.AsyncSessionLocal() as s_db:
                        assistant_msg = Message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=refusal_ans,
                            citations=[],
                            metadata_info=meta_payload,
                        )
                        s_db.add(assistant_msg)
                        await s_db.commit()
                except Exception as db_err:
                    logger.error(f"Failed to persist guardrail refusal: {db_err}")

            yield format_sse("done", {
                "answer": refusal_ans,
                "citations": [],
                "conversation_id": conversation_id,
                **meta_payload,
            })
            return
        documents = final_state.get("documents", [])
        is_relevant = final_state.get("is_relevant", False)
        retrieval_retry_count = final_state.get("retrieval_retry_count", 0)
        generation_grounded = final_state.get("generation_grounded", True)
        visualization_data = final_state.get("visualization")

        # Evaluate if query explicitly requires missing proprietary documentation
        requires_doc_patterns = [
            r"\b(secret code|confidential code|passcode|nda|contract clause|my invoice|my bill|my statement|uploaded file|attached document|page \d+|section \d+)\b",
            r"\b(what is the secret|what's the secret|read the attached|summarize the attached|in the uploaded)\b",
        ]
        requires_doc = any(re.search(pat, query.lower()) for pat in requires_doc_patterns)

        is_app_create = final_state.get("is_app_creation", False) or (intent == "app_creation")
        suggested_app_name = final_state.get("suggested_app_name") or "Custom Application Project"

        # Classify response style differentiator
        if intent == "greeting":
            response_type = "greeting"
        elif is_app_create:
            response_type = "app_creation"
        elif not documents or not is_relevant:
            response_type = "insufficient_info" if requires_doc else "ungrounded_sensible"
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
            "is_app_creation": is_app_create,
            "suggested_app_name": suggested_app_name,
            "communication_channels": ["Gmeet", "Teams", "Zoom", "others"],
            "has_citations": len(citations_list) > 0,
            "citation_count": len(citations_list),
            "consulted_memories_count": len(visible_consulted_memories),
            "consulted_memories": visible_consulted_memories,
            "retrieval_retry_count": retrieval_retry_count,
            "generation_grounded": generation_grounded,
            "has_visualization": bool(visualization_data and visualization_data.get("has_image")),
            "visualization": visualization_data,
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

        if is_app_create:
            yield format_sse("status", {"message": f"Architecting enterprise application blueprint for '{suggested_app_name}'..."})
            app_prompt = (
                f"You are a Principal Enterprise Solutions Architect and Technical Lead. The user wants to build and launch an application:\n\n"
                f"\"{query}\"\n\n"
                f"Provide an executive-grade, structured Application Blueprint covering:\n\n"
                f"### 🚀 1. Executive Solution Overview\n"
                f"- Project Title: **{suggested_app_name}**\n"
                f"- Core Purpose & Target Audience\n"
                f"- Key Business Value & Competitive Advantage\n\n"
                f"### 🛠️ 2. Recommended Technology Stack\n"
                f"- **Frontend:** Modern, responsive UI framework & styling\n"
                f"- **Backend & APIs:** Robust server architecture, REST/GraphQL endpoints\n"
                f"- **Database & Storage:** Scalable relational/document database & caching\n"
                f"- **Hosting & Cloud Infrastructure:** Zero-downtime containerized deployment\n\n"
                f"### 📦 3. Core Feature Specifications & MVP Deliverables\n"
                f"- User authentication, RBAC & profile management\n"
                f"- Core functional modules & workflow state machines\n"
                f"- Integrations (e.g. notifications, payments, third-party APIs)\n\n"
                f"### 🔒 4. Enterprise Security, Privacy & Compliance\n"
                f"- End-to-end data encryption (at rest & in transit)\n"
                f"- OWASP Top 10 defenses & audit logging\n\n"
                f"### 📅 5. Delivery Roadmap & Implementation Phases\n"
                f"- Phase 1: Prototype & Core Database Architecture (Weeks 1-2)\n"
                f"- Phase 2: Feature Development & Testing (Weeks 3-4)\n"
                f"- Phase 3: Production Hardening & Launch (Weeks 5-6)\n\n"
                f"---\n"
                f"💼 *A project request has been initialized on the Projects table. Fill out your contact details below to initiate a consultation call (via Google Meet, Teams, or Zoom) accompanied by the complete conversation transcripts.*"
            )
            app_messages = [
                SystemMessage(content="You are an expert enterprise solution architect creating structured, actionable software blueprints for client project requests."),
                HumanMessage(content=app_prompt),
            ]
            async for chunk in chat_model.astream(app_messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                accumulated_answer += token
                yield format_sse("token", {"token": token})

        elif intent == "greeting":
            greeting_messages = [SystemMessage(content=GROUNDED_RAG_SYSTEM_PROMPT)]
            if memory_context:
                greeting_messages.append(SystemMessage(content=memory_context))
            greeting_messages.append(HumanMessage(content=query))

            async for chunk in chat_model.astream(greeting_messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                accumulated_answer += token
                yield format_sse("token", {"token": token})

        needs_vis = final_state.get("needs_visualization", False) or detect_visualization_need(query)

        if not is_app_create and not documents and not needs_vis:
            if requires_doc:
                msg = "The provided documents do not contain sufficient information to answer this question. Please upload relevant files or check your query."
                accumulated_answer = msg
                for word in msg.split(" "):
                    yield format_sse("token", {"token": word + " "})
            else:
                ungrounded_messages = [
                    SystemMessage(content=UNGROUNDED_SENSIBLE_SYSTEM_PROMPT),
                ]
                if memory_context:
                    ungrounded_messages.append(SystemMessage(content=memory_context))
                for hist in chat_history[-4:]:
                    r = hist.get("role")
                    c = hist.get("content", "")
                    if r == "user":
                        ungrounded_messages.append(HumanMessage(content=c))
                    elif r == "assistant":
                        ungrounded_messages.append(SystemMessage(content=f"Previous assistant answer: {c}"))
                ungrounded_messages.append(HumanMessage(content=f"User Query:\n{query}\n\nProvide a comprehensive, sensible, and structured response:"))

                async for chunk in chat_model.astream(ungrounded_messages):
                    token = chunk.content if hasattr(chunk, "content") else str(chunk)
                    accumulated_answer += token
                    yield format_sse("token", {"token": token})

        elif not documents and needs_vis:
            sample_messages = [
                SystemMessage(
                    content=(
                        "You are an expert Python data analyst and scientific visualization programmer. "
                        "When no specific dataset has been uploaded to the workspace, provide a complete, working Python script using a clean sample dataset "
                        "(e.g. pandas DataFrame or synthetic time series), explain the structure of the data and visualization, "
                        "and clearly inform the user that they can upload their custom dataset file (CSV/JSON/Excel) in the workspace sidebar to visualize their own data."
                    )
                ),
                HumanMessage(
                    content=f"User Query:\n{query}\n\nProvide the complete Python visualization program and clear explanation:"
                ),
            ]
            async for chunk in chat_model.astream(sample_messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                accumulated_answer += token
                yield format_sse("token", {"token": token})

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

        # Emit visualization event if chart artifact was generated
        if visualization_data:
            yield format_sse("visualization", visualization_data)

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
            "visualization": visualization_data,
            "conversation_id": conversation_id,
            "response_type": response_type,
            "intent": intent,
            "is_app_creation": is_app_create,
            "suggested_app_name": suggested_app_name,
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
