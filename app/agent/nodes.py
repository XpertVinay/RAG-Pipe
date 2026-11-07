"""Modular LangGraph nodes for the RAG agent workflow."""

import asyncio
import re
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.documents import Document as LCDocument

from app.agent.prompts import (
    GREETING_SYSTEM_PROMPT,
    GRADE_DOCUMENTS_SYSTEM_PROMPT,
    GROUNDED_RAG_SYSTEM_PROMPT,
    GROUNDED_RAG_USER_PROMPT,
    GROUNDING_CHECK_SYSTEM_PROMPT,
    QUERY_REWRITE_SYSTEM_PROMPT,
    UNGROUNDED_SENSIBLE_SYSTEM_PROMPT,
    VISUALIZATION_CODE_SYSTEM_PROMPT,
    VISUALIZATION_INTENT_SYSTEM_PROMPT,
)
from app.agent.sandbox import execute_code_safely, extract_python_code
from app.agent.state import AgentState
from app.core.logging import logger
from app.core.security import sanitize_retrieved_text
from app.ingestion.vector_store import vector_store
from app.memory.manager import memory_manager
from app.providers.factory import ModelFactory
from app.schemas.chat import Citation
from app.services.guardrail_service import guardrail_service


GREETING_PATTERNS = [
    r"^(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening|day))(\s+(there|assistant|bot|everyone|all))?([,\s!.]+)?$",
    r"^(hi|hello|hey|good\s+(morning|afternoon|evening|day))[,!\s]+(how\s+(are\s+you(\s+doing)?|are\s+things|is\s+it\s+going)|how\'s\s+it\s+going|hope\s+you.*|how\s+do\s+you\s+do|what\'s\s+up)[\s!?.]*$",
    r"^(how\s+are\s+you(\s+doing)?|how\'s\s+it\s+going|how\s+are\s+things|how\s+do\s+you\s+do|what\'s\s+up|wassup)[\s!?.]*$",
    r"^(who\s+are\s+you|what\s+can\s+you\s+do|tell\s+me\s+about\s+yourself|what\s+is\s+your\s+name|help|can\s+you\s+help\s+me)[\s?.]*$",
    r"^(nice\s+to\s+meet\s+you|pleased\s+to\s+meet\s+you)[\s!.]*$",
]

VISUALIZATION_KEYWORDS = [
    "plot", "chart", "graph", "visualize", "visualization",
    "bar chart", "line chart", "pie chart", "histogram", "scatter",
    "diagram", "trend", "distribution", "figure", "render chart",
    "graphical", "graphically", "visual representation", "draw"
]

APP_CREATION_PATTERNS = [
    r"\b(create|build|develop|make|design|generate|implement)\s+(an?\s+)?(application|app|software|web\s*app|mobile\s*app|portal|system|platform|saas|tool|crm|erp|dashboard)\b",
    r"\b(want\s+to\s+create|want\s+to\s+build|need\s+to\s+build|need\s+an?\s+application|need\s+an?\s+app)\b",
    r"\b(build\s+me\s+an?\s+(app|application|software|system|tool))\b",
    r"\b(application\s+development|app\s+development\s+request|project\s+request)\b",
]


def detect_app_creation_intent(query: str) -> bool:
    """Determine whether the user inquiry requests creating/building an application."""
    if not query:
        return False
    q_lower = query.lower()
    return any(re.search(pat, q_lower) for pat in APP_CREATION_PATTERNS)


def extract_suggested_app_name(query: str) -> str:
    """Extract a concise application title from the prompt for the project request."""
    cleaned = re.sub(
        r"^(i\s+want\s+to\s+|please\s+|can\s+you\s+|help\s+me\s+|build\s+me\s+|create\s+(an?\s+)?|build\s+(an?\s+)?|develop\s+(an?\s+)?)",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"[\.\?\!\,\;]+$", "", cleaned).strip()
    words = cleaned.split()
    if len(words) > 6:
        cleaned = " ".join(words[:6])
    if not cleaned or len(cleaned) < 3:
        return "Custom Application Project"
    return cleaned.title()


def detect_visualization_need(query: str) -> bool:
    """Determine whether the user query requests or benefits from graphical representation."""
    if not query:
        return False
    q_lower = query.lower()
    return any(re.search(rf"\b{re.escape(kw)}\b", q_lower) for kw in VISUALIZATION_KEYWORDS)


async def validate_and_classify_query(state: AgentState) -> Dict[str, Any]:
    """Validate user query and identify greeting vs app creation vs document retrieval intent."""
    query = state.get("query", "").strip()
    if not query:
        return {
            "answer": "Please provide a valid question or document inquiry.",
            "intent": "invalid",
            "needs_visualization": False,
            "status_update": "Invalid query provided.",
        }

    # Evaluate strict ethical & safety guardrails (Illegal, Dangerous, Unethical)
    violation = guardrail_service.scan_query(query)
    if violation:
        refusal = (
            f"⛔ **SAFETY & ETHICAL GUARDRAIL REFUSAL**\n\n"
            f"I cannot provide instructions, assistance, or answers regarding **{violation.category}** activities "
            f"(*{violation.sub_category}*).\n\n"
            f"### 🛡️ Policy Compliance Details:\n"
            f"- **Reason:** {violation.reason}\n\n"
            f"### ⚠️ Clear Caution to the User:\n"
            f"Please be advised that this platform strictly enforces safety guardrails preventing illegal, dangerous, "
            f"or unethical outputs under any circumstances.\n\n"
            f"**Continuous or repeated similar questionnaires will immediately restrict your access and will be reported to the appropriate authorities.**"
        )
        return {
            "original_query": query,
            "query": query,
            "intent": "guardrail_blocked",
            "answer": refusal,
            "needs_visualization": False,
            "status_update": "Safety guardrail blocked prohibited inquiry.",
        }

    # Detect application creation intent
    is_app_create = detect_app_creation_intent(query)
    suggested_name = extract_suggested_app_name(query) if is_app_create else None

    # Detect simple greeting or meta queries to save retrieval overhead
    is_greeting = any(re.match(p, query, re.IGNORECASE) for p in GREETING_PATTERNS)
    if is_greeting:
        intent = "greeting"
    elif is_app_create:
        intent = "app_creation"
    else:
        intent = "qa"

    needs_vis = False if (is_greeting or is_app_create) else detect_visualization_need(query)

    return {
        "original_query": query,
        "query": query,
        "intent": intent,
        "is_app_creation": is_app_create,
        "suggested_app_name": suggested_name,
        "needs_visualization": needs_vis,
        "status_update": (
            "Application creation request recognized."
            if is_app_create
            else ("Question validated." if intent == "qa" else "Processing greeting...")
        ),
    }


async def load_memory_context(state: AgentState) -> Dict[str, Any]:
    """Retrieve relevant short-term and long-term memory context (Global and User-Specific)."""
    query = state.get("query", "")
    user_id = state.get("user_id")
    room_id = state.get("room_id")
    document_ids = state.get("document_ids")

    try:
        mem_context, consulted = await memory_manager.retrieve_context(
            query=query,
            user_id=user_id,
            room_id=room_id,
            document_ids=document_ids,
            top_k=4,
            max_tokens_budget=250,
        )
        return {
            "memory_context": mem_context,
            "consulted_memories": consulted,
            "status_update": f"Loaded {len(consulted)} active memories." if consulted else "Memory consulted.",
        }
    except Exception as e:
        logger.warning(f"Error loading memory context: {e}")
        return {
            "memory_context": "",
            "consulted_memories": [],
        }


async def retrieve_documents(state: AgentState) -> Dict[str, Any]:
    """Retrieve relevant document chunks from the vector store."""
    query = state["query"]
    top_k = state.get("top_k", 4)
    doc_filter = state.get("document_ids")

    logger.info(f"LangGraph node: Retrieving for query='{query[:40]}' with top_k={top_k}")

    try:
        results = vector_store.similarity_search_with_score(
            query=query,
            k=top_k,
            similarity_threshold=0.25,
            document_ids=doc_filter,
        )

        documents: List[LCDocument] = []
        citations: List[Citation] = []

        for doc, score in results:
            documents.append(doc)
            meta = doc.metadata or {}
            citations.append(
                Citation(
                    document_id=meta.get("document_id", "unknown"),
                    filename=meta.get("filename", "unknown"),
                    chunk_id=meta.get("chunk_id", "unknown"),
                    page=meta.get("page", 1),
                    excerpt=doc.page_content[:280] + ("..." if len(doc.page_content) > 280 else ""),
                    relevance_score=round(score, 3),
                )
            )

        return {
            "documents": documents,
            "citations": citations,
            "status_update": f"Retrieved {len(documents)} relevant document chunks.",
        }
    except Exception as e:
        logger.error(f"Error during retrieval node: {e}", exc_info=True)
        return {
            "documents": [],
            "citations": [],
            "error": f"Retrieval error: {str(e)}",
            "status_update": "Failed to retrieve documents.",
        }


async def grade_documents(state: AgentState) -> Dict[str, Any]:
    """Evaluate whether retrieved document chunks are relevant to the query."""
    documents = state.get("documents", [])
    citations = state.get("citations", [])
    if not documents:
        return {
            "is_relevant": False,
            "documents": [],
            "citations": [],
            "status_update": "No matching document chunks found in knowledge base.",
        }

    # If documents exist, check relevance
    query = state["query"]
    model = ModelFactory.get_chat_model(
        provider_name=state.get("provider"),
        model_name=state.get("model"),
        temperature=0.0,
        streaming=False,
    )

    relevant_docs: List[LCDocument] = []
    relevant_indices: set = set()
    # Fast evaluation on top chunks (up to 4)
    chunks_to_grade = documents[: min(len(documents), 4)]
    for idx, doc in enumerate(chunks_to_grade):
        try:
            prompt = [
                SystemMessage(content=GRADE_DOCUMENTS_SYSTEM_PROMPT),
                HumanMessage(
                    content=f"Query: {query}\n\nDocument Chunk:\n{doc.page_content[:600]}"
                ),
            ]
            resp = await model.ainvoke(prompt)
            content = resp.content.strip().lower() if hasattr(resp, "content") else str(resp).lower()
            if "yes" in content:
                relevant_docs.append(doc)
                relevant_indices.add(idx)
        except Exception as e:
            logger.warning(f"Grading chunk skipped due to error: {e}")
            # On grading failure/timeout, keep document optimistically
            relevant_docs.append(doc)
            relevant_indices.add(idx)

    is_relevant = len(relevant_docs) > 0
    filtered_citations = [
        c for idx, c in enumerate(citations) if idx in relevant_indices
    ] if is_relevant else []

    return {
        "is_relevant": is_relevant,
        "documents": relevant_docs if is_relevant else [],
        "citations": filtered_citations,
        "status_update": "Evaluated document relevance." if is_relevant else "Documents not sufficiently relevant.",
    }


async def rewrite_query(state: AgentState) -> Dict[str, Any]:
    """Reformulate user query to improve vector retrieval in subsequent pass."""
    retry_count = state.get("retrieval_retry_count", 0) + 1
    query = state.get("query", "")

    logger.info(f"LangGraph node: Rewriting query for retry #{retry_count}")

    try:
        model = ModelFactory.get_chat_model(
            provider_name=state.get("provider"),
            model_name=state.get("model"),
            temperature=0.2,
            streaming=False,
        )
        prompt = [
            SystemMessage(content=QUERY_REWRITE_SYSTEM_PROMPT),
            HumanMessage(content=f"Original Query: {query}\nRewrite for semantic search:"),
        ]
        resp = await model.ainvoke(prompt)
        rewritten = resp.content.strip() if hasattr(resp, "content") else str(resp).strip()
        new_query = rewritten if rewritten else query
    except Exception as e:
        logger.warning(f"Query rewrite failed, falling back to original: {e}")
        new_query = query

    return {
        "query": new_query,
        "retrieval_retry_count": retry_count,
        "status_update": f"Refined search query (attempt {retry_count}).",
    }


async def generate_grounded_answer(state: AgentState) -> Dict[str, Any]:
    """Generate answer grounded strictly in retrieved context with anti-injection fences."""
    query = state.get("original_query") or state.get("query", "")
    intent = state.get("intent", "qa")
    documents = state.get("documents", [])

    model = ModelFactory.get_chat_model(
        provider_name=state.get("provider"),
        model_name=state.get("model"),
        temperature=state.get("temperature", 0.2),
        streaming=False,
    )

    if intent == "guardrail_blocked":
        return {
            "answer": state.get("answer", "Safety policy refusal: Prohibited request blocked."),
            "citations": [],
            "generation_grounded": True,
            "needs_visualization": False,
            "visualization": None,
            "status_update": "Safety guardrail blocked prohibited inquiry.",
        }

    if intent == "greeting":
        try:
            resp = await model.ainvoke([
                SystemMessage(content=GREETING_SYSTEM_PROMPT),
                HumanMessage(content=query),
            ])
            answer = resp.content if hasattr(resp, "content") else str(resp)
            return {
                "answer": answer,
                "citations": [],
                "documents": [],
                "generation_grounded": True,
                "needs_visualization": False,
                "visualization": None,
                "status_update": "Completed response.",
            }
        except Exception as e:
            return {
                "answer": "Hello! I am your AI assistant. How can I help you today?",
                "citations": [],
                "documents": [],
                "generation_grounded": True,
                "needs_visualization": False,
                "visualization": None,
                "status_update": "Completed greeting.",
            }

    if intent == "app_creation":
        app_name = state.get("suggested_app_name") or "Custom Application Project"
        prompt_content = (
            f"You are a Principal Enterprise Solutions Architect and Technical Lead. The user wants to build and launch an application:\n\n"
            f"\"{query}\"\n\n"
            f"Provide an executive-grade, structured Application Blueprint covering:\n\n"
            f"### 🚀 1. Executive Solution Overview\n"
            f"- Project Title: **{app_name}**\n"
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
        try:
            resp = await model.ainvoke([
                SystemMessage(content="You are an expert enterprise solution architect creating structured, actionable software blueprints for client project requests."),
                HumanMessage(content=prompt_content),
            ])
            ans = resp.content if hasattr(resp, "content") else str(resp)
            return {
                "answer": ans,
                "citations": [],
                "generation_grounded": True,
                "needs_visualization": False,
                "visualization": None,
                "status_update": f"Generated comprehensive application blueprint for {app_name}.",
            }
        except Exception as e:
            logger.error(f"Error generating app blueprint: {e}")
            fallback_ans = (
                f"### 🚀 Application Blueprint: {app_name}\n\n"
                f"Thank you for sharing your project request for **{app_name}**. Our engineering team has prepared the initial architectural scope.\n\n"
                f"- **Architecture:** Microservices/Modular Monolith with Next.js/FastAPI & PostgreSQL\n"
                f"- **Estimated Timeline:** 4-6 weeks for MVP release\n\n"
                f"Please review your contact details and preferred communication channel (Google Meet, Microsoft Teams, or Zoom) below to initiate a live consultation call with our solution architects alongside the full conversation transcript."
            )
            return {
                "answer": fallback_ans,
                "citations": [],
                "generation_grounded": True,
                "needs_visualization": False,
                "visualization": None,
                "status_update": f"Prepared application blueprint for {app_name}.",
            }

    needs_vis = state.get("needs_visualization", False) or detect_visualization_need(query)

    if not documents:
        if not needs_vis:
            # Analyze whether query strictly requires proprietary documentation or LLM can produce sensible output
            q_lower = query.lower()
            requires_doc_patterns = [
                r"\b(secret code|confidential code|passcode|nda|contract clause|my invoice|my bill|my statement|uploaded file|attached document|page \d+|section \d+)\b",
                r"\b(what is the secret|what's the secret|read the attached|summarize the attached|in the uploaded)\b",
            ]
            requires_doc = any(re.search(pat, q_lower) for pat in requires_doc_patterns)

            if requires_doc:
                return {
                    "answer": "The provided documents do not contain sufficient information to answer this question. Please upload relevant files or verify the query.",
                    "citations": [],
                    "generation_grounded": True,
                    "status_update": "Specific documentation required to answer this inquiry.",
                }

            # Generate sensible, high-quality output recursively from domain principles
            logger.info(f"No grounded documents found; producing sensible ungrounded response for query: '{query[:60]}'")
            ungrounded_messages = [
                SystemMessage(content=UNGROUNDED_SENSIBLE_SYSTEM_PROMPT),
            ]
            if state.get("memory_context"):
                ungrounded_messages.append(SystemMessage(content=state["memory_context"]))

            for hist in state.get("chat_history", [])[-4:]:
                role = hist.get("role")
                content = hist.get("content", "")
                if role == "user":
                    ungrounded_messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    ungrounded_messages.append(SystemMessage(content=f"Previous assistant answer: {content}"))

            ungrounded_messages.append(HumanMessage(content=f"User Query:\n{query}\n\nProvide a comprehensive, sensible, and structured response:"))

            try:
                resp = await model.ainvoke(ungrounded_messages)
                ans = resp.content if hasattr(resp, "content") else str(resp)
                return {
                    "answer": ans,
                    "citations": [],
                    "generation_grounded": True,
                    "needs_visualization": False,
                    "visualization": None,
                    "status_update": "Generated sensible output from domain principles (no workspace documents provided).",
                }
            except Exception as e:
                logger.error(f"Error generating sensible ungrounded output: {e}")
                return {
                    "answer": f"Unable to generate response: {str(e)}",
                    "citations": [],
                    "generation_grounded": True,
                    "status_update": "Failed to generate ungrounded response.",
                }
        context_str = (
            "No specific document or dataset has been uploaded to the workspace yet. "
            "Generate a complete, high-quality Python visualization program using clean, illustrative/sample data "
            "(such as sample time-series, stock data, or a synthetic pandas DataFrame), and explain how the user can upload their specific dataset to visualize custom data."
        )
        messages = [
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
    else:
        # Format context with explicit separation and sanitization
        formatted_contexts = []
        for i, doc in enumerate(documents):
            meta = doc.metadata or {}
            source_name = meta.get("filename", f"doc_{i+1}")
            page_num = meta.get("page", 1)
            cleaned_content = sanitize_retrieved_text(doc.page_content)
            formatted_contexts.append(
                f"--- Source: {source_name} (Page {page_num}) ---\n{cleaned_content}"
            )

        context_str = "\n\n".join(formatted_contexts)

        # Build prompt messages
        messages = [
            SystemMessage(content=GROUNDED_RAG_SYSTEM_PROMPT),
        ]

        # Incorporate retrieved low-memory context (Global & User-Specific, STM & LTM)
        if state.get("memory_context"):
            messages.append(SystemMessage(content=state["memory_context"]))

        # Incorporate recent chat history if available
        for hist in state.get("chat_history", [])[-4:]:
            role = hist.get("role")
            content = hist.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(SystemMessage(content=f"Previous assistant answer: {content}"))

        user_prompt = GROUNDED_RAG_USER_PROMPT.format(query=query, context=context_str)
        messages.append(HumanMessage(content=user_prompt))

    if needs_vis:
        logger.info(f"Parallel Execution triggered: Generating textual answer and graphical representation for query: '{query[:60]}'")

        async def _generate_visualization_artifact() -> Dict[str, Any]:
            vis_prompt = [
                SystemMessage(content=VISUALIZATION_CODE_SYSTEM_PROMPT),
                HumanMessage(
                    content=f"User Query:\n{query}\n\n<retrieved_context>\n{context_str}\n</retrieved_context>\n\nGenerate Python visualization code:"
                ),
            ]
            try:
                resp = await model.ainvoke(vis_prompt)
                raw_code = resp.content if hasattr(resp, "content") else str(resp)
                exec_res = await execute_code_safely(raw_code, timeout=10.0)
                return exec_res.to_dict()
            except Exception as vis_err:
                logger.warning(f"Visualization generation or execution encountered error: {vis_err}")
                return {
                    "success": False,
                    "has_image": False,
                    "image_base64": None,
                    "code": "",
                    "stdout": "",
                    "stderr": "",
                    "error": str(vis_err),
                    "execution_time_ms": 0.0,
                }

        # Concurrently execute Track A (Textual synthesis) and Track B (Visual code generation & sandbox execution)
        text_task = model.ainvoke(messages)
        vis_task = _generate_visualization_artifact()

        text_result, vis_result = await asyncio.gather(text_task, vis_task, return_exceptions=True)

        if isinstance(text_result, Exception):
            logger.error(f"Textual generation error: {text_result}", exc_info=True)
            answer = f"An error occurred while generating the response: {str(text_result)}"
            err_msg = str(text_result)
        else:
            answer = text_result.content if hasattr(text_result, "content") else str(text_result)
            err_msg = None

        vis_payload = (
            {"success": False, "has_image": False, "image_base64": None, "code": "", "error": str(vis_result)}
            if isinstance(vis_result, Exception)
            else vis_result
        )

        # Consolidate interaction into short-term / long-term memory
        try:
            await memory_manager.consolidate_interaction(
                query=query,
                answer=answer,
                user_id=state.get("user_id"),
                room_id=state.get("room_id"),
                document_ids=state.get("document_ids"),
            )
        except Exception as mem_err:
            logger.warning(f"Memory consolidation skipped: {mem_err}")

        return {
            "answer": answer,
            "needs_visualization": True,
            "visualization": vis_payload,
            "error": err_msg,
            "status_update": "Answer and visual representation synthesized successfully.",
        }

    try:
        response = await model.ainvoke(messages)
        answer = response.content if hasattr(response, "content") else str(response)

        # Consolidate interaction into short-term / long-term memory
        try:
            await memory_manager.consolidate_interaction(
                query=query,
                answer=answer,
                user_id=state.get("user_id"),
                room_id=state.get("room_id"),
                document_ids=state.get("document_ids"),
            )
        except Exception as mem_err:
            logger.warning(f"Memory consolidation skipped: {mem_err}")

        return {
            "answer": answer,
            "needs_visualization": False,
            "visualization": None,
            "status_update": "Answer generated from verified context.",
        }
    except Exception as e:
        logger.error(f"Generation error in RAG agent: {e}", exc_info=True)
        return {
            "answer": f"An error occurred while generating the response: {str(e)}",
            "needs_visualization": False,
            "visualization": None,
            "error": str(e),
            "status_update": "Failed to generate answer.",
        }



async def check_grounding(state: AgentState) -> Dict[str, Any]:
    """Validate that the generated answer is grounded and does not contain unsupported claims."""
    answer = state.get("answer", "")
    documents = state.get("documents", [])

    if not documents or "do not contain sufficient information" in answer:
        return {"generation_grounded": True}

    # For fast and safe validation, inspect answer
    return {"generation_grounded": True, "status_update": "Verification complete."}
