"""Agent 1: Research & Requirement Gatherer (Internal RAG, Domain Knowledge, LTM/STM, & MCP Tools)."""

from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.logging import logger
from app.mcp.registry import mcp_registry
from app.models.multi_agent import AgentRole
from app.providers.factory import ModelFactory


RESEARCHER_SYSTEM_PROMPT = """You are Agent 1: Research & Requirement Gatherer.
Your role:
1. Synthesize factual research from domain knowledge bases, internal workspace documents, long-term memories, and anonymous web tools.
2. Produce a clear, unambiguous Requirements Specification with functional requirements, technical constraints, and testable acceptance criteria.
3. Zero tolerance for ungrounded hallucination. If certain details are unknown, state explicit assumptions.
"""


class ResearcherAgent:
    """Agent 1: Research & Requirement Gatherer."""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider
        self.model = model
        self.role = AgentRole.RESEARCHER.value

    async def gather_requirements(
        self,
        goal: str,
        strategy: Dict[str, Any],
        memory_context: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        domain_context: Optional[str] = None,
        anonymous: bool = True,
    ) -> Dict[str, Any]:
        """Perform multi-source research and compile structured requirements."""
        logger.info(f"Agent 1 [Researcher]: Gathering requirements for: '{goal[:80]}'")

        gathered_evidence: List[str] = []

        # 1. Grounded Domain Knowledge Base (from admin/staff or user uploads)
        if domain_context:
            gathered_evidence.append(f"Domain Knowledge Base:\n{domain_context}")

        # 2. Internal RAG retrieval if available or document_ids specified
        try:
            rag_res = await mcp_registry.execute_tool(
                tool_name="rag_retriever",
                arguments={"query": goal, "top_k": 4, "document_ids": document_ids},
                anonymous=anonymous,
            )
            if not rag_res.isError and rag_res.get_text():
                gathered_evidence.append(f"Vector Knowledge Index:\n{rag_res.get_text()}")
        except Exception as e:
            logger.debug(f"Researcher internal RAG query note: {e}")

        # 3. External MCP web research (anonymously)
        try:
            web_res = await mcp_registry.execute_tool(
                tool_name="web_research",
                arguments={"query": goal},
                anonymous=anonymous,
            )
            if not web_res.isError and web_res.get_text():
                gathered_evidence.append(f"External Research Findings:\n{web_res.get_text()}")
        except Exception as e:
            logger.debug(f"Researcher web research note: {e}")

        # 4. Long-Term and Short-Term Memory Context
        if memory_context:
            gathered_evidence.append(f"Historical Memory Context:\n{memory_context}")

        evidence_block = "\n\n".join(gathered_evidence) if gathered_evidence else "Standard software development baseline."

        prompt_text = (
            f"Goal: {goal}\n"
            f"Strategy Directive: {strategy.get('strategy', 'Standard execution')}\n"
            f"Domain Directives: {strategy.get('domain_directives', 'Follow architecture standards')}\n\n"
            f"Gathered Evidence:\n{evidence_block[:3000]}\n\n"
            f"Formulate a structured Requirements Specification:\n"
            f"1. Core Functional Requirements\n"
            f"2. Technical Architecture & Constraints\n"
            f"3. Security Mandates (PII anonymization, input validation)\n"
            f"4. Verifiable Acceptance Criteria (bullet points)"
        )

        try:
            chat_model = ModelFactory.get_chat_model(
                provider_name=self.provider,
                model_name=self.model,
                temperature=0.2,
                streaming=False,
            )
            resp = await chat_model.ainvoke([
                SystemMessage(content=RESEARCHER_SYSTEM_PROMPT),
                HumanMessage(content=prompt_text),
            ])
            spec_text = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            logger.warning(f"Researcher LLM generation fallback: {e}")
            spec_text = (
                f"### Requirements Specification for: {goal}\n"
                f"1. Functional Scope: Implement all capabilities required to satisfy: {goal}\n"
                f"2. Technical Architecture: Modular micro-tasks, asynchronous I/O, MCP tool interfaces.\n"
                f"3. Security Mandates: Zero PII exposure, sanitized inputs, AST-validated execution.\n"
                f"4. Acceptance Criteria: All generated subtasks execute and pass verification."
            )

        return {
            "requirements_spec": spec_text,
            "evidence_sources": len(gathered_evidence),
            "evidence_summary": evidence_block[:400],
        }
