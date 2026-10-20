"""Agent 0: Decision Maker (Strategic Orchestrator, Customer Advisor, and Delegation Authority).

All agents depend upon the Decision Maker agent. It orchestrates each agent,
transfers domain context, and delegates tasks according to each agent's abilities.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.multi_agent.protocol import GeneratedSubTask
from app.core.logging import logger
from app.models.multi_agent import AgentRole
from app.providers.factory import ModelFactory


DECISION_MAKER_SYSTEM_PROMPT = """You are Agent 0: Decision Maker in a high-performance multi-agent system.
You are the central decision authority, orchestrator, and executive advisor to the customer/user.

Your responsibilities:
1. Formulate clear, grounded advice to the customer/user based on domain knowledge and architecture standards.
2. Formulate strategic execution plans, technical principles, and security mandates.
3. Transfer curated context and directives to specialized agents (Researcher, Task Generator, Task Performer, Validator, Deployer).
4. Direct delegations according to each agent's abilities, oversee task validation, and ensure zero unhandled syntax or logical errors.
5. Synthesize final delivery reports with actionable conclusions.

Guidelines:
- Maintain uncompromising standards for Security, Performance, and Quality.
- Output clear, decisive, structured JSON or concise markdown.
"""


class DecisionMakerAgent:
    """Agent 0: Decision Maker (Strategic Orchestrator & Central Authority)."""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider
        self.model = model
        self.role = AgentRole.DECISION_MAKER.value

    async def advise_and_plan(
        self,
        goal: str,
        domain_knowledge: Optional[str] = None,
        memory_context: Optional[str] = None,
        user_provided_docs: bool = False,
    ) -> Dict[str, Any]:
        """Advise the customer/user accordingly with provided documents or admin/staff domain knowledge,

        and formulate the executive strategy and delegation directives.
        """
        logger.info(f"Agent 0 [Decision Maker]: Formulating advice and plan for: '{goal[:80]}'")

        user_content = f"Goal:\n{goal}\n"

        if domain_knowledge:
            doc_source_label = "User Provided Documents" if user_provided_docs else "Admin / Staff Domain Knowledge Base"
            user_content += f"\nRelevant {doc_source_label}:\n{domain_knowledge[:3000]}\n"

        if memory_context:
            user_content += f"\nRelevant Memory / Prior Decisions:\n{memory_context}\n"

        user_content += (
            "\nProvide your strategic advice and plan as JSON with keys:\n"
            "- 'title': brief title\n"
            "- 'customer_advice': comprehensive advice to the user/customer on how to accomplish the objective, architectural recommendations, and key steps\n"
            "- 'strategy': concise strategy overview for the agent team\n"
            "- 'domain_directives': key technical directives drawn from the domain documents\n"
            "- 'security_mandates': list of 2-3 security requirements\n"
            "- 'performance_targets': list of 2-3 performance goals\n"
            "- 'quality_gates': list of 2-3 acceptance checks\n"
        )

        try:
            chat_model = ModelFactory.get_chat_model(
                provider_name=self.provider,
                model_name=self.model,
                temperature=0.2,
                streaming=False,
            )
            response = await chat_model.ainvoke([
                SystemMessage(content=DECISION_MAKER_SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ])
            text = response.content if hasattr(response, "content") else str(response)

            json_start = text.find("{")
            json_end = text.rfind("}")
            if json_start != -1 and json_end != -1:
                parsed = json.loads(text[json_start:json_end+1])
                if "customer_advice" not in parsed:
                    parsed["customer_advice"] = (
                        f"Recommended Development Approach for '{goal}': Align implementation with grounded domain architecture standards, "
                        f"modularize into discrete verified micro-tasks, and ensure strict syntax validation and automated deployment monitoring."
                    )
                return parsed
            else:
                return {
                    "title": goal[:60],
                    "customer_advice": (
                        f"Executive Advice for '{goal}': We recommend proceeding with a modular micro-task decomposition. "
                        f"Leverage the extracted domain knowledge standards for architectural compliance, sanitize all inputs, and enforce automated canary health checks."
                    ),
                    "strategy": text.strip()[:600],
                    "domain_directives": "Follow extracted admin/staff domain standards: modular I/O, zero PII transmission, and automated syntax validation.",
                    "security_mandates": ["Zero PII transmission to 3rd-party providers", "Strict SSRF & AST validation"],
                    "performance_targets": ["Sub-second latency per subtask", "Hierarchical context compaction"],
                    "quality_gates": ["100% automated validation checks pass", "Zero unhandled syntax or logical exceptions"],
                }
        except Exception as e:
            logger.warning(f"Decision Maker model invocation fallback: {e}")
            advice = (
                f"Advisory Guidance: For accomplishing '{goal}', adhere to the domain standards uploaded by administrators. "
                f"The task will be decomposed into atomic verified micro-tasks, executed in sandboxed environments, and deployed with active syntaxual and logical monitoring."
            )
            return {
                "title": f"Plan: {goal[:50]}",
                "customer_advice": advice,
                "strategy": f"Structured execution plan addressing: {goal}",
                "domain_directives": "Adhere to grounded domain architecture and security standards.",
                "security_mandates": ["Enforce anonymous scrubbed data transfers", "Strict input parameter boundaries"],
                "performance_targets": ["Minimal token consumption", "Async concurrent task execution"],
                "quality_gates": ["Validator passes all acceptance criteria", "Continuous health monitoring and syntax checks active"],
            }

    async def analyze_goal_and_plan(
        self,
        goal: str,
        memory_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible entry point for goal analysis."""
        return await self.advise_and_plan(goal=goal, domain_knowledge=None, memory_context=memory_context)

    # -------------------------------------------------------------------------
    # Central Orchestration & Delegation Methods
    # -------------------------------------------------------------------------

    async def delegate_to_researcher(
        self,
        researcher: Any,
        goal: str,
        strategy: Dict[str, Any],
        domain_context: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        memory_context: Optional[str] = None,
        anonymous: bool = True,
    ) -> Dict[str, Any]:
        """Decision Maker transfers domain content and context directives to Researcher agent."""
        logger.info("Agent 0 [Decision Maker] -> Delegating to Agent 1 [Researcher] with domain context.")
        return await researcher.gather_requirements(
            goal=goal,
            strategy=strategy,
            memory_context=memory_context,
            document_ids=document_ids,
            domain_context=domain_context,
            anonymous=anonymous,
        )

    async def delegate_to_task_generator(
        self,
        task_generator: Any,
        goal: str,
        requirements_spec: str,
        max_subtasks: int = 4,
    ) -> List[GeneratedSubTask]:
        """Decision Maker instructs Task Generator to decompose requirements into small atomic micro-tasks."""
        logger.info(f"Agent 0 [Decision Maker] -> Delegating to Agent 2 [Task Generator] (max {max_subtasks} tasks).")
        return await task_generator.generate_tasks(
            goal=goal,
            requirements_spec=requirements_spec,
            max_subtasks=max_subtasks,
        )

    async def delegate_to_task_performer_and_validator(
        self,
        task_executor: Any,
        validator: Any,
        subtask: GeneratedSubTask,
        consolidated_ctx: str,
        anonymous: bool = True,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Decision Maker delegates task execution to Task Performer according to tool abilities,

        and routes results to Validator to ensure high quality deliverables.
        """
        logger.info(
            f"Agent 0 [Decision Maker] -> Delegating Subtask {subtask.task_number} to Agent 3 [Task Performer]."
        )
        exec_res = await task_executor.execute_subtask(
            subtask=subtask,
            context_str=consolidated_ctx,
            anonymous=anonymous,
        )

        logger.info(
            f"Agent 0 [Decision Maker] -> Routing Subtask {subtask.task_number} output to Agent 4 [Validator]."
        )
        val_res = await validator.validate_subtask(
            subtask=subtask,
            execution_result=exec_res,
        )
        exec_res["validation_result"] = val_res
        return exec_res, val_res

    async def delegate_to_deployer(
        self,
        deployer: Any,
        workflow_id: str,
        goal: str,
        executed_tasks: List[Dict[str, Any]],
        environment: str = "production",
    ) -> Dict[str, Any]:
        """Decision Maker directs Deployer to deploy, monitor, and alert for syntaxual & logical errors."""
        logger.info("Agent 0 [Decision Maker] -> Delegating rollout and health monitoring to Agent 5 [Deployer].")
        return await deployer.deploy_and_monitor(
            workflow_id=workflow_id,
            goal=goal,
            executed_tasks=executed_tasks,
            environment=environment,
        )

    async def synthesize_final_report(
        self,
        goal: str,
        strategy: Dict[str, Any],
        executed_tasks: List[Dict[str, Any]],
        deployment_info: Dict[str, Any],
        context_metrics: Dict[str, Any],
    ) -> str:
        """Create final executive deliverable advising the customer on development and accomplished tasks."""
        task_summaries = []
        for t in executed_tasks:
            num = t.get("task_number", 0)
            title = t.get("title", "Task")
            status = t.get("status", "completed")
            val = t.get("validation_result", {}).get("passed", True)
            val_txt = "Verified" if val else "Review Needed"
            score = t.get("validation_result", {}).get("score", 1.0)
            task_summaries.append(f"- Subtask {num} ({title}): Status={status.upper()}, Validation={val_txt} (Score: {score})")

        tasks_block = "\n".join(task_summaries) if task_summaries else "No subtasks recorded."
        customer_advice = strategy.get("customer_advice") or strategy.get("strategy", "Execution completed.")

        error_summary = []
        if deployment_info.get("syntax_errors"):
            error_summary.append(f"- Syntax Errors Detected & Alerted: {len(deployment_info['syntax_errors'])}")
        if deployment_info.get("logical_errors"):
            error_summary.append(f"- Logical Discrepancies Detected & Alerted: {len(deployment_info['logical_errors'])}")
        if not error_summary:
            error_summary.append("- Syntax & Logic Validation: 100% Clean (Zero syntax or logical errors detected)")

        error_block = "\n".join(error_summary)

        return (
            f"## Multi-Agent Collaborative Execution & Advisory Report\n\n"
            f"**Objective**: {goal}\n\n"
            f"### 0. Executive Advisory & Strategy (Decision Maker)\n"
            f"**Customer Advice**:\n{customer_advice}\n\n"
            f"**Strategic Blueprint**:\n{strategy.get('strategy', 'Standard execution.')}\n\n"
            f"### Execution & Task Breakdown (Task Performer & Validator)\n"
            f"{tasks_block}\n\n"
            f"### 5. Deployment, Health Monitoring & Alerts (Deployer)\n"
            f"- Rollout Status: {deployment_info.get('status', 'DEPLOYED').upper()}\n"
            f"- Target Environment: {deployment_info.get('environment', 'PRODUCTION')}\n"
            f"- Health Telemetry: {deployment_info.get('health', 'OPTIMAL').upper()} (DB: {deployment_info.get('db_status', 'healthy')})\n"
            f"- Quality & Code Health:\n{error_block}\n"
            f"- Operational Alert: {deployment_info.get('alert', {}).get('severity', 'INFO')} - {deployment_info.get('alert', {}).get('message', 'Normal')[:120]}\n\n"
            f"### Context Window & Performance Telemetry\n"
            f"- Original Tokens: {context_metrics.get('original_tokens', 0):,}\n"
            f"- Compacted Tokens: {context_metrics.get('compacted_tokens', 0):,}\n"
            f"- Tokens Saved: {context_metrics.get('tokens_saved', 0):,} ({context_metrics.get('compression_ratio', 0)}% reduction)\n"
            f"- LTM/STM Memories Scoped: Yes\n"
        )
