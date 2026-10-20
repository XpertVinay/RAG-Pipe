"""Domain Knowledge Service for extracting and organizing domain knowledge bases.

If a user does not upload any files, this service extracts documents for different
domains that have been uploaded by system super admins, organization admins, and staff
members, assembling a grounded domain knowledge base for the Decision Maker agent.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import logger
from app.models.document import Document, DocumentChunk
from app.models.organization import OrganizationMember
from app.models.room import Room, RoomDocument
from app.models.user import User


@dataclass
class DomainKnowledgeResult:
    """Structured domain knowledge base extracted from admin/staff documents."""
    extracted_doc_ids: List[str]
    domain_context_str: str
    documents_by_domain: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    total_documents: int = 0
    source_type: str = "admin_staff_knowledge_base"  # "admin_staff_knowledge_base" or "user_provided"


class DomainKnowledgeService:
    """Extracts, categorizes, and formats domain documents for multi-agent orchestration."""

    DOMAIN_KEYWORDS = {
        "Architecture & System Design": ["architecture", "system", "design", "component", "spec", "blueprint", "pattern"],
        "Security, Auth & Compliance": ["security", "auth", "rbac", "compliance", "privacy", "token", "jwt", "anonym"],
        "DevOps, Deployment & Infrastructure": ["deploy", "devops", "docker", "infra", "kubernetes", "cloud", "monitor", "alert"],
        "API, Data Models & Database": ["api", "schema", "database", "sql", "model", "endpoint", "crud", "query"],
        "Testing & Quality Assurance": ["test", "validation", "qa", "criteria", "benchmark", "syntax", "audit"],
        "Business Logic & Requirements": ["requirement", "business", "billing", "pricing", "feature", "workflow", "policy"],
    }

    @classmethod
    def classify_domain(cls, filename: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Classify a document into a domain based on metadata or filename keywords."""
        if metadata and metadata.get("domain"):
            return str(metadata["domain"])

        name_lower = filename.lower()
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            if any(k in name_lower for k in keywords):
                return domain

        return "General System & Domain Standards"

    @classmethod
    async def extract_domain_knowledge(
        cls,
        db: AsyncSession,
        document_ids: Optional[List[str]] = None,
        room_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> DomainKnowledgeResult:
        """Extract domain knowledge base.

        If document_ids is provided and non-empty, uses those documents (user provided).
        If document_ids is None or empty, automatically extracts documents across domains
        uploaded by system super admins, organization admins, and staff members.
        """
        logger.info(
            f"DomainKnowledgeService: Extracting knowledge (explicit_ids={document_ids}, room_id={room_id})"
        )

        extracted_docs: List[Document] = []
        source_type = "admin_staff_knowledge_base"

        # Case 1: User explicitly provided specific document IDs
        if document_ids:
            source_type = "user_provided"
            stmt = (
                select(Document)
                .options(selectinload(Document.chunks))
                .where(Document.id.in_(document_ids))
            )
            res = await db.execute(stmt)
            extracted_docs = list(res.scalars().all())

        # Case 2: User did NOT upload files -> Extract domain knowledge uploaded by admin / org admin / staff
        if not extracted_docs and not document_ids:
            source_type = "admin_staff_knowledge_base"

            # 1. Identify admin and staff user IDs
            admin_staff_users_stmt = select(User.id).where(
                User.role.in_(["admin", "superadmin", "staff", "staffs"])
            )
            as_res = await db.execute(admin_staff_users_stmt)
            admin_staff_user_ids = set(as_res.scalars().all())

            # 2. Identify org admin and staff user IDs
            org_member_stmt = select(OrganizationMember.user_id).where(
                OrganizationMember.role.in_(["admin", "staff", "staffs", "owner"])
            )
            om_res = await db.execute(org_member_stmt)
            org_admin_staff_ids = set(om_res.scalars().all())

            eligible_uploader_ids = admin_staff_user_ids | org_admin_staff_ids

            # Query documents uploaded by eligible admins/staff, or marked as shared system docs
            doc_query = select(Document).options(selectinload(Document.chunks))

            conds = [
                Document.is_shared.is_(True),
            ]
            if eligible_uploader_ids:
                conds.append(Document.user_id.in_(list(eligible_uploader_ids)))

            # If room_id is specified, include room documents
            if room_id:
                room_doc_subquery = (
                    select(RoomDocument.document_id).where(RoomDocument.room_id == room_id)
                )
                conds.append(Document.id.in_(room_doc_subquery))

            doc_query = doc_query.where(or_(*conds)).order_by(Document.created_at.desc())
            q_res = await db.execute(doc_query)
            extracted_docs = list(q_res.scalars().all())

        # If still no documents in DB (e.g. freshly initialized environment without uploads),
        # return a structured baseline domain knowledge base
        if not extracted_docs:
            baseline_text = (
                "### Default System Architecture & Engineering Standards (System Knowledge Base)\n"
                "- [Architecture]: Modular multi-agent service design, decoupled micro-tasks, asynchronous I/O.\n"
                "- [Security]: Strict RBAC isolation, zero PII transmission to external tools, AST-validated execution.\n"
                "- [Quality]: Uncompromising acceptance criteria validation, syntax & logical error verification.\n"
                "- [DevOps]: Automated canary deployment, real-time health telemetry, proactive error alerting.\n"
            )
            return DomainKnowledgeResult(
                extracted_doc_ids=[],
                domain_context_str=baseline_text,
                documents_by_domain={"Core Architecture & Standards": []},
                total_documents=0,
                source_type=source_type,
            )

        # Categorize documents by domain and extract content snippets
        docs_by_domain: Dict[str, List[Dict[str, Any]]] = {}
        formatted_sections: List[str] = []
        doc_ids: List[str] = []

        for doc in extracted_docs:
            domain = cls.classify_domain(doc.filename, doc.audit_metadata)
            doc_ids.append(doc.id)

            # Retrieve content snippet from chunks, file on disk, or metadata
            snippet = ""
            if doc.chunks:
                # Concatenate first 2-3 chunks for domain knowledge context
                snippet = "\n".join(c.content.strip() for c in doc.chunks[:3] if c.content)
            elif doc.storage_path and os.path.exists(doc.storage_path):
                try:
                    with open(doc.storage_path, "r", encoding="utf-8", errors="ignore") as f:
                        snippet = f.read(1200)
                except Exception as e:
                    logger.debug(f"Could not read document file {doc.storage_path}: {e}")

            if not snippet:
                snippet = f"Document: {doc.filename} (Type: {doc.file_type}, Chunks: {doc.chunk_count})"

            doc_info = {
                "id": doc.id,
                "filename": doc.filename,
                "file_type": doc.file_type,
                "domain": domain,
                "uploader_username": doc.uploader_username or "system_admin",
                "uploader_role": "admin/staff" if source_type == "admin_staff_knowledge_base" else "user",
                "snippet": snippet[:600],
            }

            docs_by_domain.setdefault(domain, []).append(doc_info)

        # Build formatted markdown domain context string
        header = (
            "### Domain Knowledge Base (Extracted from Super Admin / Org Admin / Staff Documents):\n"
            if source_type == "admin_staff_knowledge_base"
            else "### Grounded Knowledge Base (User Provided Documents):\n"
        )
        formatted_sections.append(header)

        for domain, d_list in docs_by_domain.items():
            formatted_sections.append(f"#### Domain: {domain}")
            for item in d_list:
                uploader = f"Uploaded by @{item['uploader_username']} [{item['uploader_role']}]"
                formatted_sections.append(
                    f"- **{item['filename']}** ({uploader}):\n  {item['snippet'][:300]}"
                )

        domain_context_str = "\n".join(formatted_sections)

        return DomainKnowledgeResult(
            extracted_doc_ids=doc_ids,
            domain_context_str=domain_context_str,
            documents_by_domain=docs_by_domain,
            total_documents=len(extracted_docs),
            source_type=source_type,
        )


domain_knowledge_service = DomainKnowledgeService()
