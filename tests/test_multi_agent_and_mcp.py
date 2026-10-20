"""Comprehensive test suite for Multi-Agent Collaborative System, MCP Client/Server, and Context Compaction."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.agent.multi_agent.agents.decision_maker import DecisionMakerAgent
from app.agent.multi_agent.agents.deployer import DeployerAgent
from app.agent.multi_agent.agents.researcher import ResearcherAgent
from app.agent.multi_agent.agents.task_executor import TaskExecutorAgent
from app.agent.multi_agent.agents.task_generator import TaskGeneratorAgent
from app.agent.multi_agent.agents.validator import ValidatorAgent
from app.agent.multi_agent.orchestrator import MultiAgentOrchestrator
from app.agent.multi_agent.protocol import GeneratedSubTask, WorkflowInitRequest
from app.main import app
from app.mcp.client import MCPClient
from app.mcp.protocol import CallToolResult, MCPClientConfig, MCPTool
from app.mcp.registry import mcp_registry
from app.mcp.security import AnonymousScrubber, SSRFProtector
from app.mcp.server import mcp_server
from app.memory.context_window import ContextWindowManager


# ---------------------------------------------------------------------
# 1. Security & Anonymization Tests
# ---------------------------------------------------------------------

def test_anonymous_scrubber_pii_and_keys():
    """Verify AnonymousScrubber strips emails, API keys, JWTs, IPs, and internal file paths."""
    sensitive_text = (
        "Contact alice.smith@enterprise.org or bob@corp.internal. "
        "OpenAI key is sk-proj1234567890abcdef1234567890. "
        "User file located at /Users/vinaykumar/Desktop/project/file.py. "
        "Host is at 192.168.1.50 and public IP 93.184.216.34."
    )
    scrubbed = AnonymousScrubber.anonymize_text(sensitive_text)

    # Assert no raw emails leak
    assert "alice.smith@enterprise.org" not in scrubbed
    assert "anonymous_user_" in scrubbed
    # Assert no API key leaks
    assert "sk-proj1234567890abcdef1234567890" not in scrubbed
    assert "[REDACTED_API_KEY]" in scrubbed
    # Assert no private user paths leak
    assert "/Users/vinaykumar" not in scrubbed
    assert "/workspace/project" in scrubbed


def test_anonymous_scrubber_payload():
    """Verify recursive payload dictionary anonymization."""
    payload = {
        "auth_token": "secret_bearer_12345",
        "user_id": "usr_998877",
        "nested": {
            "query": "Send report to support@mycorp.com",
            "retries": 3,
        },
    }
    scrubbed = AnonymousScrubber.anonymize_payload(payload)

    assert scrubbed["auth_token"] == "[REDACTED_SECRET]"
    assert scrubbed["user_id"].startswith("anon_")
    assert "support@mycorp.com" not in scrubbed["nested"]["query"]
    assert scrubbed["nested"]["retries"] == 3


def test_ssrf_protector():
    """Verify SSRF protector blocks private cloud metadata and invalid schemes."""
    assert not SSRFProtector.validate_url("ftp://example.com")
    assert not SSRFProtector.validate_url("http://169.254.169.254/latest/meta-data", allow_local_for_dev=False)
    assert SSRFProtector.validate_url("https://api.github.com/mcp")


# ---------------------------------------------------------------------
# 2. MCP Server & Client Roundtrip Tests
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_server_initialize_and_ping():
    """Test MCP Server initialize and ping JSON-RPC handlers."""
    init_req = {
        "jsonrpc": "2.0",
        "id": "init-1",
        "method": "initialize",
        "params": {},
    }
    resp = await mcp_server.handle_request(init_req)
    assert resp["id"] == "init-1"
    assert "serverInfo" in resp["result"]
    assert resp["result"]["protocolVersion"] == "2024-11-05"

    ping_req = {
        "jsonrpc": "2.0",
        "id": "ping-1",
        "method": "ping",
        "params": {},
    }
    ping_resp = await mcp_server.handle_request(ping_req)
    assert ping_resp["id"] == "ping-1"
    assert ping_resp["result"] == {}


@pytest.mark.asyncio
async def test_mcp_server_tools_list_and_call():
    """Test discovering and invoking tools via MCP Server."""
    tools_req = {
        "jsonrpc": "2.0",
        "id": "tools-1",
        "method": "tools/list",
        "params": {},
    }
    tools_resp = await mcp_server.handle_request(tools_req)
    tools = tools_resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    assert "web_research" in tool_names
    assert "code_sandbox" in tool_names
    assert "system_monitor" in tool_names

    # Test calling system_monitor via MCP server
    call_req = {
        "jsonrpc": "2.0",
        "id": "call-1",
        "method": "tools/call",
        "params": {
            "name": "system_monitor",
            "arguments": {},
        },
    }
    call_resp = await mcp_server.handle_request(call_req)
    assert not call_resp.get("error")
    assert "System Telemetry" in call_resp["result"]["content"][0]["text"]


# ---------------------------------------------------------------------
# 3. Native Tools Execution Tests
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_native_tools_code_sandbox():
    """Verify code_sandbox executes python code and handles forbidden commands."""
    # Safe code
    res = await mcp_registry.execute_tool(
        tool_name="code_sandbox",
        arguments={"code": "x = 10 * 5\nprint(f'Computed: {x}')"},
        anonymous=True,
    )
    assert not res.isError
    assert "Computed: 50" in res.get_text()

    # Forbidden security test
    forbidden_res = await mcp_registry.execute_tool(
        tool_name="code_sandbox",
        arguments={"code": "import os; os.system('echo bad')"},
        anonymous=True,
    )
    assert forbidden_res.isError
    assert "Security rejection" in forbidden_res.get_text()


@pytest.mark.asyncio
async def test_native_tools_deploy_simulator_and_alert():
    """Verify deploy_simulator and alert_dispatcher tools."""
    deploy_res = await mcp_registry.execute_tool(
        tool_name="deploy_simulator",
        arguments={"artifact_name": "test_pkg", "environment": "staging"},
    )
    assert not deploy_res.isError
    assert "STAGING" in deploy_res.get_text()

    alert_res = await mcp_registry.execute_tool(
        tool_name="alert_dispatcher",
        arguments={"severity": "INFO", "message": "Test system alert message"},
    )
    assert not alert_res.isError
    assert "Dispatched Successfully" in alert_res.get_text()


# ---------------------------------------------------------------------
# 4. Context Compaction & Token Budgeting Tests
# ---------------------------------------------------------------------

def test_context_window_compaction():
    """Verify hierarchical summarization compacts earlier subtasks and measures token savings."""
    mgr = ContextWindowManager(max_context_tokens=4000)

    # Compact 3 subtasks
    for i in range(1, 4):
        mgr.compact_subtask(
            task_id=f"t_{i}",
            task_number=i,
            title=f"Detailed Microtask {i}",
            agent_role="task_executor",
            status="validated",
            input_data={"data": f"input details for task {i}"},
            output_data={"result": f"Output details and computed artifacts for task {i} " * 15},
            artifacts=[{"name": f"artifact_{i}.json"}],
            validation_result={"passed": True, "score": 0.95},
        )

    text, metrics = mgr.build_consolidated_context(
        goal="Build and verify token authentication",
        requirements="Strict requirements with rate limiting",
        active_task_detail="Currently running deploy check",
        raw_traces=["A very long verbose trace log " * 50],
    )

    assert "Subtask 1 [TASK_EXECUTOR]" in text
    assert "Subtask 2 [TASK_EXECUTOR]" in text
    assert "Active Task In Execution" in text
    assert metrics.compacted_tokens > 0
    assert metrics.tokens_saved > 0
    assert metrics.compression_ratio > 0.0


# ---------------------------------------------------------------------
# 5. Multi-Agent Pipeline Components Tests (Agents 0 through 5)
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_six_agents_individual_execution():
    """Verify all 6 agents (0 through 5) execute their individual functional contracts."""
    goal = "Implement resilient rate limiting and session validation"

    # Agent 0: Decision Maker
    agent0 = DecisionMakerAgent()
    strategy = await agent0.analyze_goal_and_plan(goal)
    assert "strategy" in strategy
    assert "security_mandates" in strategy

    # Agent 1: Researcher
    agent1 = ResearcherAgent()
    research = await agent1.gather_requirements(goal, strategy)
    assert "requirements_spec" in research

    # Agent 2: Task Generator
    agent2 = TaskGeneratorAgent()
    subtasks = await agent2.generate_tasks(goal, research["requirements_spec"], max_subtasks=2)
    assert len(subtasks) >= 1
    first_task = subtasks[0]

    # Agent 3: Task Executor
    agent3 = TaskExecutorAgent()
    exec_res = await agent3.execute_subtask(first_task, "Consolidated context", anonymous=True)
    assert exec_res["status"] == "completed"
    assert "output_data" in exec_res

    # Agent 4: Validator
    agent4 = ValidatorAgent()
    val_res = await agent4.validate_subtask(first_task, exec_res)
    assert "passed" in val_res
    assert "score" in val_res

    # Agent 5: Deployer
    agent5 = DeployerAgent()
    deploy_res = await agent5.deploy_and_monitor("wf_test_123", goal, [exec_res])
    assert deploy_res["status"] == "deployed"
    assert "db_status" in deploy_res


# ---------------------------------------------------------------------
# 6. End-to-End Orchestrator Streaming Test
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestrator_streaming_execution(test_db):
    """Verify full end-to-end multi-agent streaming pipeline yields all expected event types."""
    orchestrator = MultiAgentOrchestrator()
    request = WorkflowInitRequest(
        goal="Test multi-agent collaborative pipeline end-to-end",
        anonymous=True,
        max_subtasks=2,
    )

    events_received = []
    async for sse_chunk in orchestrator.execute_workflow_stream(request):
        events_received.append(sse_chunk)

    combined_stream = "".join(events_received)
    assert "event: workflow_started" in combined_stream
    assert "event: agent_phase" in combined_stream
    assert "event: tasks_generated" in combined_stream
    assert "event: task_validated" in combined_stream
    assert "event: deployment_updated" in combined_stream
    assert "event: workflow_completed" in combined_stream


# ---------------------------------------------------------------------
# 7. FastAPI API Endpoints Tests
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_agents_endpoints(client):
    """Verify /api/v1/agents/tools, /api/v1/agents/workflows, and /api/v1/mcp/messages."""
    # Test tools discovery
    tools_resp = await client.get("/api/v1/agents/tools")
    assert tools_resp.status_code == 200
    tools_data = tools_resp.json()
    assert len(tools_data) >= 5

    # Test creating workflow record
    create_resp = await client.post(
        "/api/v1/agents/workflows",
        json={"goal": "API integration test for workflow creation", "anonymous": True},
    )
    assert create_resp.status_code == 201
    wf_id = create_resp.json()["workflow_id"]

    # Test listing workflows
    list_resp = await client.get("/api/v1/agents/workflows")
    assert list_resp.status_code == 200
    assert any(w["id"] == wf_id for w in list_resp.json())

    # Test MCP message endpoint
    mcp_msg_resp = await client.post(
        "/api/v1/mcp/messages",
        json={"jsonrpc": "2.0", "id": "test-rpc-1", "method": "ping", "params": {}},
    )
    assert mcp_msg_resp.status_code == 200
    assert mcp_msg_resp.json()["id"] == "test-rpc-1"
