"""Unit and integration tests for Ungrounded Sensible Output and Parallel Task Delegation with Orchestrator Prompts."""

import pytest
from app.agent.multi_agent.agents.decision_maker import DecisionMakerAgent
from app.agent.multi_agent.orchestrator import MultiAgentOrchestrator
from app.agent.multi_agent.protocol import GeneratedSubTask, WorkflowInitRequest
from app.agent.nodes import generate_grounded_answer
from app.agent.state import AgentState


@pytest.mark.asyncio
async def test_ungrounded_sensible_output_vs_requires_documentation():
    """Verify that when no grounded documents exist:
    - Queries needing confidential/proprietary files ask for documentation.
    - General/technical queries produce sensible, helpful outputs recursively.
    """
    # 1. Query requiring specific unprovided proprietary document
    doc_req_state: AgentState = {
        "query": "What is the secret code in the uploaded agreement?",
        "intent": "qa",
        "documents": [],
    }
    res_doc = await generate_grounded_answer(doc_req_state)
    assert "do not contain sufficient information" in res_doc["answer"]

    # 2. Query that can be answered sensibly and recursively without private documents
    sensible_state: AgentState = {
        "query": "Explain how distributed cache invalidation works with TTL and pub/sub.",
        "intent": "qa",
        "documents": [],
    }
    res_sensible = await generate_grounded_answer(sensible_state)
    assert "do not contain sufficient information" not in res_sensible["answer"]
    assert len(res_sensible["answer"]) > 50


@pytest.mark.asyncio
async def test_decision_maker_feasibility_analysis():
    """Verify Decision Maker commands over request analysis to determine documentation vs recursive generation."""
    dm = DecisionMakerAgent()

    # Proprietary request
    f_doc = await dm.analyze_request_feasibility(
        goal="What is the confidential passcode in the contract?",
        has_grounded_knowledge=False,
    )
    assert f_doc["requires_documentation"] is True
    assert f_doc["can_generate_recursively"] is False
    assert f_doc["execution_mode"] == "ask_documentation"

    # Recursive generative task
    f_rec = await dm.analyze_request_feasibility(
        goal="Develop an in-memory LRU cache with concurrency locks in Python",
        has_grounded_knowledge=False,
    )
    assert f_rec["requires_documentation"] is False
    assert f_rec["can_generate_recursively"] is True
    assert f_rec["execution_mode"] == "recursive_generation"


def test_decision_maker_orchestrator_prompts_and_parallel_partitioning():
    """Verify Decision Maker creates explicit orchestrator prompts and partitions tasks for parallel execution in isolation."""
    dm = DecisionMakerAgent()

    tasks = [
        GeneratedSubTask(
            task_number=1,
            title="Inspect Database Schema",
            description="Run database schema verification",
            assigned_tools=["system_monitor"],
            dependencies=[],
            can_run_parallel=True,
            acceptance_criteria=["Schema verified"],
        ),
        GeneratedSubTask(
            task_number=2,
            title="Verify Network Gateway",
            description="Run network port connectivity probe",
            assigned_tools=["system_monitor"],
            dependencies=[],
            can_run_parallel=True,
            acceptance_criteria=["Gateway live"],
        ),
        GeneratedSubTask(
            task_number=3,
            title="Deploy Caching Service",
            description="Deploy Redis cache tier",
            assigned_tools=["code_sandbox"],
            dependencies=[1, 2],
            can_run_parallel=False,
            acceptance_criteria=["Cache tier operational"],
        ),
    ]

    strategy = {"strategy": "High-throughput asynchronous architecture rollout"}
    context = "Initial system environment context."

    # 1. Verify orchestrator prompt attachment
    tasks_with_prompts = dm.formulate_orchestrator_prompts(
        goal="Setup scalable caching tier",
        strategy=strategy,
        subtasks=tasks,
        consolidated_ctx=context,
    )

    for st in tasks_with_prompts:
        assert st.orchestrator_prompt is not None
        assert f"SUBTASK {st.task_number}" in st.orchestrator_prompt
        assert "Isolation" in st.orchestrator_prompt
        assert "Collaboration Mandate" in st.orchestrator_prompt

    # 2. Verify parallel execution partitioning
    batches = dm.partition_tasks_for_parallel_execution(tasks_with_prompts)
    assert len(batches) == 2

    # Wave 1: Tasks 1 & 2 can run in parallel in isolation
    wave1_task_nums = {t.task_number for t in batches[0]}
    assert wave1_task_nums == {1, 2}

    # Wave 2: Task 3 depends on 1 and 2
    wave2_task_nums = {t.task_number for t in batches[1]}
    assert wave2_task_nums == {3}


@pytest.mark.asyncio
async def test_multi_agent_parallel_orchestrator_streaming(test_db):
    """Integration test verifying MultiAgentOrchestrator streams feasibility evaluation and parallel task execution."""
    orchestrator = MultiAgentOrchestrator()
    request = WorkflowInitRequest(
        goal="Design and verify thread-safe bounded task queue with worker pools",
        document_ids=None,
        anonymous=True,
        max_subtasks=3,
    )

    events = []
    async for frame in orchestrator.execute_workflow_stream(request=request):
        events.append(frame)

    full_output = "".join(events)

    # Verify Decision Maker analyzed feasibility
    assert "event: request_feasibility_evaluated" in full_output
    # Verify tasks generated with orchestrator directives
    assert "event: tasks_generated" in full_output
    # Verify parallel delegation triggered if independent tasks exist
    assert "event: parallel_delegation_batch_started" in full_output
    # Verify tasks validated and workflow accomplished
    assert "event: task_validated" in full_output
    assert "event: workflow_completed" in full_output
