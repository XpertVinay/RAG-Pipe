"""End-to-end test suite for Multi-Agent Orchestration with Decision Maker as central authority.

Tests scenarios where:
1. User does not upload any files -> System extracts domain documents uploaded by
   super admin, org admin, and staff members into a grounded knowledge base.
   Decision Maker advises the customer/user, delegates to researcher, generates
   small tasks, performs them, validates quality, deploys with syntax & logical
   error monitoring and alerts, accomplishing the task.
2. User provides their own document -> Decision Maker advises the user accordingly
   with the provided document for development and accomplishes the task.
3. Deployer detects syntaxual and logical errors and dispatches operational alerts.
4. HTTP API endpoints (/api/v1/agents/advise and /api/v1/agents/workflows/stream).
"""

import json
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.agent.multi_agent.agents.decision_maker import DecisionMakerAgent
from app.agent.multi_agent.agents.deployer import DeployerAgent
from app.agent.multi_agent.orchestrator import MultiAgentOrchestrator
from app.agent.multi_agent.protocol import GeneratedSubTask, WorkflowInitRequest
from app.main import app
from app.models.document import Document, DocumentChunk
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.services.domain_knowledge_service import domain_knowledge_service


@pytest.mark.asyncio
async def test_domain_knowledge_extraction_when_no_user_files(test_db):
    """Verify that when a user does not upload files, documents uploaded by

    super admin, org admin, and staff across different domains are extracted.
    """
    # 1. Create Super Admin, Org Admin, and Staff users
    super_admin = User(
        id=str(uuid.uuid4()),
        username="super_admin_user",
        email="superadmin@corp.io",
        hashed_password="hash",
        role="admin",
    )
    staff_user = User(
        id=str(uuid.uuid4()),
        username="staff_devops_lead",
        email="staff_devops@corp.io",
        hashed_password="hash",
        role="staff",
    )
    test_db.add_all([super_admin, staff_user])
    await test_db.commit()

    # 2. Upload Admin & Staff domain documents
    doc_arch = Document(
        id=str(uuid.uuid4()),
        user_id=super_admin.id,
        uploader_username=super_admin.username,
        filename="system_architecture_spec.md",
        file_type="md",
        file_size=2048,
        storage_path="/tmp/system_architecture_spec.md",
        status="completed",
        chunk_count=1,
        audit_metadata={"domain": "Architecture & System Design"},
    )
    chunk_arch = DocumentChunk(
        id=str(uuid.uuid4()),
        document_id=doc_arch.id,
        chunk_index=0,
        content="System Architecture Standard: Microservices must communicate via asynchronous protocols with sub-second latencies.",
    )

    doc_sec = Document(
        id=str(uuid.uuid4()),
        user_id=super_admin.id,
        uploader_username=super_admin.username,
        filename="security_auth_policy.md",
        file_type="md",
        file_size=1500,
        storage_path="/tmp/security_auth_policy.md",
        status="completed",
        chunk_count=1,
        audit_metadata={"domain": "Security, Auth & Compliance"},
    )
    chunk_sec = DocumentChunk(
        id=str(uuid.uuid4()),
        document_id=doc_sec.id,
        chunk_index=0,
        content="Security Policy: Zero PII transmission to external providers. Strict AST validation on sandboxed scripts.",
    )

    doc_infra = Document(
        id=str(uuid.uuid4()),
        user_id=staff_user.id,
        uploader_username=staff_user.username,
        filename="staff_deployment_guide.md",
        file_type="md",
        file_size=1800,
        storage_path="/tmp/staff_deployment_guide.md",
        status="completed",
        chunk_count=1,
        audit_metadata={"domain": "DevOps, Deployment & Infrastructure"},
    )
    chunk_infra = DocumentChunk(
        id=str(uuid.uuid4()),
        document_id=doc_infra.id,
        chunk_index=0,
        content="DevOps Standard: Canary deployment mandatory. Active telemetry monitoring with syntax and logical error alerting.",
    )

    test_db.add_all([doc_arch, chunk_arch, doc_sec, chunk_sec, doc_infra, chunk_infra])
    await test_db.commit()

    # 3. Call DomainKnowledgeService without user document IDs
    result = await domain_knowledge_service.extract_domain_knowledge(
        db=test_db,
        document_ids=None,
    )

    assert result.source_type == "admin_staff_knowledge_base"
    assert result.total_documents >= 3
    assert doc_arch.id in result.extracted_doc_ids
    assert doc_sec.id in result.extracted_doc_ids
    assert doc_infra.id in result.extracted_doc_ids
    assert "Architecture & System Design" in result.documents_by_domain
    assert "Security, Auth & Compliance" in result.documents_by_domain
    assert "DevOps, Deployment & Infrastructure" in result.documents_by_domain
    assert "Zero PII transmission" in result.domain_context_str


@pytest.mark.asyncio
async def test_end_to_end_user_call_without_files_advised_by_decision_maker(test_db):
    """End-to-End Test: User initiates a call WITHOUT uploading files.

    - System extracts domain knowledge base from super admin and staff uploads.
    - Decision Maker advises customer/user accordingly with the domain documents.
    - Decision Maker delegates to Researcher with domain context.
    - Task Generator generates small micro-tasks.
    - Task Performer executes and Validator verifies tasks.
    - Deployer checks for syntaxual and logical errors and dispatches alerts.
    - Decision Maker synthesizes final delivery report.
    """
    # 1. Setup admin domain knowledge
    admin = User(
        id=str(uuid.uuid4()),
        username="admin_architect",
        email="architect@enterprise.org",
        hashed_password="hash",
        role="admin",
    )
    test_db.add(admin)
    await test_db.commit()

    doc = Document(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        uploader_username=admin.username,
        filename="system_design_blueprint.md",
        file_type="md",
        file_size=1024,
        storage_path="/tmp/system_design_blueprint.md",
        status="completed",
        chunk_count=1,
    )
    chunk = DocumentChunk(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        chunk_index=0,
        content="Grounded Architecture Spec: Build high-performance stateless micro-tasks with automatic health checks.",
    )
    test_db.add_all([doc, chunk])
    await test_db.commit()

    # 2. Regular user initiates a call without files
    user = User(
        id=str(uuid.uuid4()),
        username="customer_user",
        email="customer@client.com",
        hashed_password="hash",
        role="user",
    )
    test_db.add(user)
    await test_db.commit()

    orchestrator = MultiAgentOrchestrator()
    request = WorkflowInitRequest(
        goal="Develop secure high-throughput caching tier adhering to architecture standards",
        document_ids=None,  # No files uploaded by user!
        anonymous=True,
        max_subtasks=2,
    )

    # 3. Stream execution and verify SSE progression
    events_received = []
    async for sse_chunk in orchestrator.execute_workflow_stream(request=request, user_id=user.id):
        events_received.append(sse_chunk)

    full_stream = "".join(events_received)

    # Verify domain knowledge was extracted
    assert "event: domain_knowledge_extracted" in full_stream
    assert "super admin / organization admins / staffs" in full_stream

    # Verify Decision Maker advised the customer/user
    assert "event: user_advisory" in full_stream
    assert "customer_advice" in full_stream

    # Verify small tasks were generated, validated, and deployed
    assert "event: tasks_generated" in full_stream
    assert "event: task_validated" in full_stream
    assert "event: deployment_updated" in full_stream
    assert "event: workflow_completed" in full_stream


@pytest.mark.asyncio
async def test_end_to_end_user_call_with_provided_document(test_db):
    """End-to-End Test: User initiates a call WITH their own document provided.

    - Decision Maker advises the customer/user accordingly with the provided document.
    - Tasks are generated, executed, validated, and deployed.
    """
    user = User(
        id=str(uuid.uuid4()),
        username="enterprise_client",
        email="client@acme.corp",
        hashed_password="hash",
        role="user",
    )
    test_db.add(user)
    await test_db.commit()

    # User uploads a specific requirement document
    user_doc = Document(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploader_username=user.username,
        filename="acme_custom_requirements.md",
        file_type="md",
        file_size=512,
        storage_path="/tmp/acme_custom_requirements.md",
        status="completed",
        chunk_count=1,
    )
    user_chunk = DocumentChunk(
        id=str(uuid.uuid4()),
        document_id=user_doc.id,
        chunk_index=0,
        content="Acme Requirement: Implement OAuth2 token refresh logic with 15-minute rotation intervals.",
    )
    test_db.add_all([user_doc, user_chunk])
    await test_db.commit()

    orchestrator = MultiAgentOrchestrator()
    request = WorkflowInitRequest(
        goal="Implement Acme OAuth2 token rotation workflow",
        document_ids=[user_doc.id],  # Document provided by user!
        anonymous=True,
        max_subtasks=2,
    )

    result = await orchestrator.advise_and_execute(request=request, user_id=user.id)

    assert result["completed"] is True
    assert "customer_advice" in result
    assert len(result["customer_advice"]) > 20
    assert result["deployment"]["status"] == "deployed"
    assert "OAuth2" in result["final_report"] or "token" in result["final_report"] or "Acme" in result["final_report"]


@pytest.mark.asyncio
async def test_deployer_syntax_and_logical_error_checks_and_alerting():
    """Verify DeployerAgent detects syntaxual and logical errors and dispatches alerts."""
    deployer = DeployerAgent()

    # Case 1: Tasks with Python syntax error
    tasks_with_syntax_err = [
        {
            "task_number": 1,
            "title": "Broken Script Task",
            "status": "completed",
            "input_data": {"code": "def invalid_syntax(\n  return 42"},  # Syntax error!
            "validation_result": {"passed": True, "score": 1.0},
        }
    ]

    syntax_res = deployer.verify_syntax(tasks_with_syntax_err)
    assert len(syntax_res) >= 1
    assert syntax_res[0]["task_number"] == 1

    # Case 2: Tasks with logical error (validation failure / unsatisfied criteria)
    tasks_with_logical_err = [
        {
            "task_number": 2,
            "title": "Failed Calculation Task",
            "status": "completed",
            "validation_result": {
                "passed": False,
                "score": 0.2,
                "feedback": "Logical error: Output did not match expected business invariants.",
                "checks": [{"criterion": "Accurate summation", "satisfied": False}],
            },
            "tool_results": {
                "code_sandbox": {"is_error": True, "text": "ZeroDivisionError: division by zero"}
            },
        }
    ]

    logical_res = deployer.verify_logic(tasks_with_logical_err)
    assert len(logical_res) >= 2  # validation failure + unsatisfied check + tool error
    types = [err["type"] for err in logical_res]
    assert "validation_failure" in types
    assert "tool_error" in types

    # Case 3: Deployer deploy_and_monitor triggers alerts
    report = await deployer.deploy_and_monitor(
        workflow_id="test_wf_errors",
        goal="Test error alerting",
        executed_tasks=tasks_with_syntax_err + tasks_with_logical_err,
    )

    assert report["has_syntax_errors"] is True
    assert report["has_logical_errors"] is True
    assert report["health"] == "degraded"
    assert any(a["severity"] == "CRITICAL" for a in report["alerts"])
    assert any(a["severity"] == "WARNING" for a in report["alerts"])


@pytest.mark.asyncio
async def test_api_advise_endpoint(client, test_db):
    """Verify POST /api/v1/agents/advise where user initiates a call and

    Decision Maker advises accordingly and accomplishes tasks.
    """
    resp = await client.post(
        "/api/v1/agents/advise",
        json={
            "goal": "Build robust API rate limiter with token bucket algorithm",
            "anonymous": True,
            "max_subtasks": 2,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "workflow_id" in data
    assert "customer_advice" in data
    assert len(data["customer_advice"]) > 0
    assert data["completed"] is True
    assert "final_report" in data
    assert "deployment" in data
