"""Central Multi-Agent Orchestrator coordinating all 6 agents, context compaction, and memory.

All agents depend upon the Decision Maker agent. If the user does not upload files,
the system extracts documents across different domains uploaded by system super admins,
organization admins, and staff members to gather the grounded knowledge base.
The Decision Maker agent transfers content and context to the Researcher, evaluates findings,
instructs the Task Generator to create small micro-tasks, orchestrates the Task Performer
and Validator, and directs the Deployer to deploy, monitor, and alert for syntaxual & logical errors.
"""

import asyncio
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.multi_agent.agents.decision_maker import DecisionMakerAgent
from app.agent.multi_agent.agents.deployer import DeployerAgent
from app.agent.multi_agent.agents.researcher import ResearcherAgent
from app.agent.multi_agent.agents.task_executor import TaskExecutorAgent
from app.agent.multi_agent.agents.task_generator import TaskGeneratorAgent
from app.agent.multi_agent.agents.validator import ValidatorAgent
from app.agent.multi_agent.memory_bridge import MultiAgentMemoryBridge
from app.agent.multi_agent.protocol import AgentEvent, GeneratedSubTask, WorkflowInitRequest
from app.core.logging import logger
from app import database
from app.memory.context_window import ContextWindowManager
from app.models.multi_agent import (
    AgentRole,
    AgentSubTask,
    AgentWorkflow,
    SubTaskStatus,
    WorkflowStatus,
)
from app.services.domain_knowledge_service import domain_knowledge_service


def _safe_str(val: Any, default: str = "") -> str:
    """Ensure value is safely converted to a string before slicing or formatting."""
    if val is None:
        return default
    if isinstance(val, str):
        return val
    if isinstance(val, (dict, list)):
        import json
        try:
            return json.dumps(val)
        except Exception:
            return str(val)
    return str(val)


class MultiAgentOrchestrator:
    """Coordinates collaborative execution across the 6 specialized agents centered on Decision Maker."""

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model
        self.decision_maker = DecisionMakerAgent(provider=provider, model=model)
        self.researcher = ResearcherAgent(provider=provider, model=model)
        self.task_generator = TaskGeneratorAgent(provider=provider, model=model)
        self.task_executor = TaskExecutorAgent(provider=provider, model=model)
        self.validator = ValidatorAgent(provider=provider, model=model)
        self.deployer = DeployerAgent(provider=provider, model=model)

    async def execute_workflow_stream(
        self,
        request: WorkflowInitRequest,
        user_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Execute the multi-agent pipeline and stream structured SSE events."""
        wf_id = workflow_id or str(uuid.uuid4())
        context_mgr = ContextWindowManager()
        t_start = time.perf_counter()

        logger.info(f"Starting Multi-Agent Workflow '{wf_id}' for goal: '{request.goal[:80]}'")

        yield AgentEvent(
            event_type="workflow_started",
            phase="initialization",
            agent_role="orchestrator",
            message=f"Initialized Multi-Agent Workflow '{wf_id}'.",
            progress=5,
            data={"workflow_id": wf_id, "goal": request.goal, "anonymous": request.anonymous},
        ).to_sse()

        # Database initialization
        async with database.AsyncSessionLocal() as session:
            wf_record = AgentWorkflow(
                id=wf_id,
                user_id=user_id,
                room_id=request.room_id,
                title=request.title or request.goal[:60],
                goal=request.goal,
                status=WorkflowStatus.PLANNING.value,
                is_anonymous=request.anonymous,
            )
            session.add(wf_record)
            await session.commit()

        # Extract Domain Knowledge Base (Admin/Staff if user uploaded no files, or User Provided)
        async with database.AsyncSessionLocal() as session:
            domain_res = await domain_knowledge_service.extract_domain_knowledge(
                db=session,
                document_ids=request.document_ids,
                room_id=request.room_id,
                user_id=user_id,
            )

        if not request.document_ids:
            yield AgentEvent(
                event_type="domain_knowledge_extracted",
                phase="0. Decision Maker",
                agent_role=AgentRole.DECISION_MAKER.value,
                message=(
                    f"Extracted domain knowledge base from {domain_res.total_documents} document(s) "
                    f"uploaded by system super admin / organization admins / staffs across "
                    f"{len(domain_res.documents_by_domain)} domain(s)."
                ),
                progress=10,
                data={
                    "total_documents": domain_res.total_documents,
                    "domains": list(domain_res.documents_by_domain.keys()),
                    "source_type": domain_res.source_type,
                },
            ).to_sse()
        else:
            yield AgentEvent(
                event_type="domain_knowledge_extracted",
                phase="0. Decision Maker",
                agent_role=AgentRole.DECISION_MAKER.value,
                message=f"Ingested {len(request.document_ids)} user-provided document(s) for task grounding.",
                progress=10,
                data={
                    "total_documents": len(request.document_ids),
                    "source_type": "user_provided",
                },
            ).to_sse()

        # Phase 0: Decision Maker Advisor & Strategic Blueprint
        yield AgentEvent(
            event_type="agent_phase",
            phase="0. Decision Maker",
            agent_role=AgentRole.DECISION_MAKER.value,
            message="Agent 0: Formulating customer advisory and strategic execution blueprint...",
            progress=15,
        ).to_sse()

        memory_ctx, consulted_mems = await MultiAgentMemoryBridge.retrieve_workflow_context(
            goal=request.goal,
            user_id=user_id,
            room_id=request.room_id,
        )

        strategy = await self.decision_maker.advise_and_plan(
            goal=request.goal,
            domain_knowledge=domain_res.domain_context_str,
            memory_context=memory_ctx,
            user_provided_docs=bool(request.document_ids),
        )

        feasibility = strategy.get("feasibility", {})
        if feasibility:
            yield AgentEvent(
                event_type="request_feasibility_evaluated",
                phase="0. Decision Maker",
                agent_role=AgentRole.DECISION_MAKER.value,
                message=(
                    f"Decision Maker Analysis: {'Document upload requested' if feasibility.get('requires_documentation') else 'Producing valid sensible output recursively'} - {feasibility.get('reason', '')}"
                ),
                progress=18,
                data=feasibility,
            ).to_sse()

        customer_advice = _safe_str(strategy.get("customer_advice"), "")
        yield AgentEvent(
            event_type="user_advisory",
            phase="0. Decision Maker",
            agent_role=AgentRole.DECISION_MAKER.value,
            message=f"Decision Maker Advice: {customer_advice[:160]}...",
            progress=22,
            data={
                "customer_advice": customer_advice,
                "strategy": strategy.get("strategy"),
                "domain_directives": strategy.get("domain_directives"),
                "feasibility": feasibility,
            },
        ).to_sse()

        strategy_str = _safe_str(strategy.get("strategy"), "Execution plan prepared.")
        yield AgentEvent(
            event_type="agent_thought",
            phase="0. Decision Maker",
            agent_role=AgentRole.DECISION_MAKER.value,
            message=f"Strategy defined: {strategy_str[:160]}...",
            progress=25,
            data={"strategy": strategy, "consulted_memories_count": len(consulted_mems)},
        ).to_sse()

        # Phase 1: Decision Maker transfers content and context to Researcher & Requirement Gatherer
        yield AgentEvent(
            event_type="agent_phase",
            phase="1. Researcher",
            agent_role=AgentRole.RESEARCHER.value,
            message="Agent 1: Decision Maker transferred domain context. Gathering grounded requirements...",
            progress=35,
        ).to_sse()

        effective_doc_ids = request.document_ids or domain_res.extracted_doc_ids

        research_data = await self.decision_maker.delegate_to_researcher(
            researcher=self.researcher,
            goal=request.goal,
            strategy=strategy,
            domain_context=domain_res.domain_context_str,
            document_ids=effective_doc_ids,
            memory_context=memory_ctx,
            anonymous=request.anonymous,
        )
        req_spec = research_data["requirements_spec"]

        # Context compaction check after research
        consolidated_ctx, ctx_metrics = context_mgr.build_consolidated_context(
            goal=request.goal,
            requirements=req_spec,
        )

        yield AgentEvent(
            event_type="context_compacted",
            phase="1. Researcher",
            agent_role="context_manager",
            message=f"Context Window Compaction: {ctx_metrics.compacted_tokens} tokens ({ctx_metrics.compression_ratio}% reduction)",
            progress=40,
            data={"metrics": ctx_metrics.__dict__},
        ).to_sse()

        # Phase 2: Decision Maker delegates to Task Generator to create small micro-tasks
        yield AgentEvent(
            event_type="agent_phase",
            phase="2. Task Generator",
            agent_role=AgentRole.TASK_GENERATOR.value,
            message="Agent 2: Decision Maker delegated requirement spec. Decomposing into small micro-tasks...",
            progress=45,
        ).to_sse()

        subtasks = await self.decision_maker.delegate_to_task_generator(
            task_generator=self.task_generator,
            goal=request.goal,
            requirements_spec=req_spec,
            max_subtasks=request.max_subtasks,
        )

        # Decision Maker formulates explicit orchestrator prompts defining isolation boundaries & collaboration mandates
        subtasks = self.decision_maker.formulate_orchestrator_prompts(
            goal=request.goal,
            strategy=strategy,
            subtasks=subtasks,
            consolidated_ctx=consolidated_ctx,
        )

        yield AgentEvent(
            event_type="tasks_generated",
            phase="2. Task Generator",
            agent_role=AgentRole.TASK_GENERATOR.value,
            message=f"Generated {len(subtasks)} discrete atomic micro-tasks with Decision Maker orchestrator directives.",
            progress=50,
            data={"tasks": [t.model_dump() for t in subtasks]},
        ).to_sse()

        # Save generated tasks to DB
        async with database.AsyncSessionLocal() as session:
            for st in subtasks:
                sub_rec = AgentSubTask(
                    id=str(uuid.uuid4()),
                    workflow_id=wf_id,
                    task_number=st.task_number,
                    title=st.title,
                    description=st.description,
                    assigned_tools=st.assigned_tools,
                    mcp_provider=st.mcp_provider,
                    is_anonymous=request.anonymous,
                    input_data=st.input_data,
                    status=SubTaskStatus.PENDING.value,
                )
                session.add(sub_rec)
            await session.commit()

        # Phase 3 & 4: Task Execution & Validation Loop orchestrated by Decision Maker
        # Partition tasks for parallel execution when agents can execute in isolation with each other
        parallel_batches = self.decision_maker.partition_tasks_for_parallel_execution(subtasks)
        executed_tasks: List[Dict[str, Any]] = []
        total_subtasks = len(subtasks)
        completed_count = 0

        for wave_idx, batch in enumerate(parallel_batches, start=1):
            is_parallel = len(batch) > 1
            batch_titles = ", ".join(f"#{t.task_number} '{t.title}'" for t in batch)

            if is_parallel:
                yield AgentEvent(
                    event_type="parallel_delegation_batch_started",
                    phase=f"3. Parallel Task Delegation (Wave {wave_idx})",
                    agent_role=AgentRole.DECISION_MAKER.value,
                    message=f"Decision Maker delegating {len(batch)} tasks in PARALLEL to agents executing in isolation: {batch_titles}",
                    progress=50 + int((completed_count / (total_subtasks + 1)) * 30),
                    data={
                        "wave": wave_idx,
                        "parallel_tasks_count": len(batch),
                        "tasks": [t.model_dump() for t in batch],
                    },
                ).to_sse()

            # Emit start events for each task in this wave
            for st in batch:
                st_progress = 50 + int((completed_count / (total_subtasks + 1)) * 30)
                yield AgentEvent(
                    event_type="agent_phase",
                    phase=f"3. Task Executor (Subtask {st.task_number}/{total_subtasks})",
                    agent_role=AgentRole.TASK_EXECUTOR.value,
                    message=f"Agent 3: Decision Maker delegated Subtask {st.task_number}: '{st.title}'...",
                    progress=st_progress,
                    data={"task_number": st.task_number, "title": st.title, "orchestrator_prompt": st.orchestrator_prompt},
                ).to_sse()

            # Concurrently execute tasks that can perform in isolation with each other
            async def _run_subtask(subtask_item: GeneratedSubTask):
                return await self.decision_maker.delegate_to_task_performer_and_validator(
                    task_executor=self.task_executor,
                    validator=self.validator,
                    subtask=subtask_item,
                    consolidated_ctx=consolidated_ctx,
                    anonymous=request.anonymous,
                )

            batch_results = await asyncio.gather(*[_run_subtask(t) for t in batch])

            # Process validated results and update collaborative context
            for subtask, (exec_res, val_res) in zip(batch, batch_results):
                completed_count += 1
                sub_progress = 50 + int((completed_count / (total_subtasks + 1)) * 30)
                executed_tasks.append(exec_res)

                # Persist executed subtask state, output, and validation to the database
                async with database.AsyncSessionLocal() as session:
                    from sqlalchemy import select
                    q_st = await session.execute(
                        select(AgentSubTask).where(
                            AgentSubTask.workflow_id == wf_id,
                            AgentSubTask.task_number == subtask.task_number,
                        )
                    )
                    sub_rec_db = q_st.scalar_one_or_none()
                    if sub_rec_db:
                        sub_rec_db.status = (
                            SubTaskStatus.COMPLETED.value
                            if val_res.get("passed", True)
                            else SubTaskStatus.FAILED.value
                        )
                        sub_rec_db.output_data = exec_res.get("output_data", {})
                        sub_rec_db.validation_result = val_res
                        sub_rec_db.validation_score = float(val_res.get("score", 1.0))
                        sub_rec_db.execution_logs = exec_res.get("logs", [])
                        await session.commit()

                # Save intermediate task to Short-Term Memory (STM)
                await MultiAgentMemoryBridge.save_subtask_stm(
                    workflow_id=wf_id,
                    task_number=subtask.task_number,
                    title=subtask.title,
                    output_summary=exec_res.get("output_data", {}).get("summary", ""),
                    user_id=user_id,
                    room_id=request.room_id,
                )

                # Context compaction of completed subtask
                compacted_item = context_mgr.compact_subtask(
                    task_id=f"task_{subtask.task_number}",
                    task_number=subtask.task_number,
                    title=subtask.title,
                    agent_role="task_executor",
                    status="validated" if val_res.get("passed") else "needs_review",
                    input_data=subtask.input_data,
                    output_data=exec_res.get("output_data", {}),
                    artifacts=exec_res.get("artifacts", []),
                    validation_result=val_res,
                )

                yield AgentEvent(
                    event_type="task_validated",
                    phase="4. Tasks Validator",
                    agent_role=AgentRole.VALIDATOR.value,
                    message=f"Subtask {subtask.task_number} Validation: {'PASSED' if val_res.get('passed') else 'FLAGGED'} (Score: {val_res.get('score')})",
                    progress=min(sub_progress + 4, 84),
                    data={
                        "task_number": subtask.task_number,
                        "validation": val_res,
                        "compacted_summary": compacted_item.key_findings,
                    },
                ).to_sse()

            # Rebuild consolidated context after wave completion so peer agents collaborate with completed findings
            consolidated_ctx, _ = context_mgr.build_consolidated_context(
                goal=request.goal,
                requirements=req_spec,
            )

        # Phase 5: Deployer (Deploy, Monitor, and Alert for Syntaxual & Logical Errors)
        yield AgentEvent(
            event_type="agent_phase",
            phase="5. Deployer",
            agent_role=AgentRole.DEPLOYER.value,
            message="Agent 5: Deploying solution, running syntax & logical error checks, monitoring health...",
            progress=85,
        ).to_sse()

        deploy_info = await self.decision_maker.delegate_to_deployer(
            deployer=self.deployer,
            workflow_id=wf_id,
            goal=request.goal,
            executed_tasks=executed_tasks,
        )

        has_syn = deploy_info.get("has_syntax_errors", False)
        has_log = deploy_info.get("has_logical_errors", False)
        err_msg = "CLEAN (Zero syntax/logical errors)" if not (has_syn or has_log) else "ERRORS DETECTED"

        yield AgentEvent(
            event_type="deployment_updated",
            phase="5. Deployer",
            agent_role=AgentRole.DEPLOYER.value,
            message=f"Deployment {deploy_info.get('status').upper()}. Health: {deploy_info.get('health').upper()}. Checks: {err_msg}.",
            progress=92,
            data=deploy_info,
        ).to_sse()

        # Final Context Compaction & Synthesis by Decision Maker
        final_ctx, final_metrics = context_mgr.build_consolidated_context(
            goal=request.goal,
            requirements=req_spec,
        )

        final_report = await self.decision_maker.synthesize_final_report(
            goal=request.goal,
            strategy=strategy,
            executed_tasks=executed_tasks,
            deployment_info=deploy_info,
            context_metrics=final_metrics.__dict__,
        )

        # Persist strategic knowledge into Long-Term Memory (LTM)
        strat_summary = _safe_str(strategy.get("strategy"), "Standard execution")
        await MultiAgentMemoryBridge.save_decision_or_spec_ltm(
            title=f"Workflow_{wf_id[:8]}_{request.goal[:30]}",
            content=f"Goal: {request.goal}. Strategy: {strat_summary[:300]}. Deployment: {deploy_info.get('status')}.",
            category="workflow_deliverable",
            user_id=user_id,
            room_id=request.room_id,
        )

        # Update Database with final record
        total_duration_s = round(time.perf_counter() - t_start, 2)
        async with database.AsyncSessionLocal() as session:
            from sqlalchemy import select
            q = await session.execute(select(AgentWorkflow).where(AgentWorkflow.id == wf_id))
            wf_db = q.scalar_one_or_none()
            if wf_db:
                wf_db.status = WorkflowStatus.COMPLETED.value
                wf_db.executive_summary = final_report
                wf_db.requirements_spec = req_spec
                wf_db.deployment_info = deploy_info
                wf_db.metrics = {
                    "duration_seconds": total_duration_s,
                    "context_compaction": final_metrics.__dict__,
                    "task_count": len(executed_tasks),
                    "customer_advice": customer_advice,
                    "domain_documents_count": domain_res.total_documents,
                }
                await session.commit()

        yield AgentEvent(
            event_type="workflow_completed",
            phase="completion",
            agent_role=AgentRole.DECISION_MAKER.value,
            message=f"Workflow '{wf_id}' successfully accomplished by agent team in {total_duration_s}s.",
            progress=100,
            data={
                "workflow_id": wf_id,
                "final_report": final_report,
                "customer_advice": customer_advice,
                "duration_seconds": total_duration_s,
                "metrics": final_metrics.__dict__,
                "deployment": deploy_info,
            },
        ).to_sse()

    async def advise_and_execute(
        self,
        request: WorkflowInitRequest,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronously execute the full multi-agent collaborative pipeline and return the deliverable."""
        wf_id = str(uuid.uuid4())
        last_event_data = {}
        events = []

        async for sse_frame in self.execute_workflow_stream(request=request, user_id=user_id, workflow_id=wf_id):
            events.append(sse_frame)
            if "event: workflow_completed" in sse_frame:
                import json
                for line in sse_frame.split("\n"):
                    if line.startswith("data: "):
                        try:
                            last_event_data = json.loads(line[6:])
                        except Exception:
                            pass

        return {
            "workflow_id": wf_id,
            "goal": request.goal,
            "completed": bool(last_event_data),
            "customer_advice": last_event_data.get("data", {}).get("customer_advice") or "Execution completed.",
            "final_report": last_event_data.get("data", {}).get("final_report", ""),
            "deployment": last_event_data.get("data", {}).get("deployment", {}),
            "events_count": len(events),
        }


# Global Orchestrator instance
multi_agent_orchestrator = MultiAgentOrchestrator()
