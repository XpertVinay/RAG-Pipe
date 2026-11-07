"""Agent 2: Task Generator (Atomic Micro-Task Decomposition and Tool Mapping)."""

import json
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.multi_agent.protocol import GeneratedSubTask
from app.core.logging import logger
from app.models.multi_agent import AgentRole
from app.providers.factory import ModelFactory


TASK_GENERATOR_SYSTEM_PROMPT = """You are Agent 2: Task Generator.
Your sole job is to take a high-level goal and requirements specification, then break it down into SMALL, ATOMIC, INDEPENDENT, and TESTABLE micro-tasks.

Rules:
1. Each micro-task must focus on one single concrete action (e.g., configure schema, implement logic, execute verification script).
2. Assign the appropriate MCP or native tool (e.g., 'code_sandbox', 'web_research', 'rag_retriever', 'system_monitor', 'deploy_simulator').
3. Identify if tasks can execute in ISOLATION with each other in PARALLEL ("can_run_parallel": true). If a task requires outputs from earlier tasks, list those task numbers in "dependencies" and set "can_run_parallel": false.
4. Specify 1-2 unambiguous acceptance criteria per task.
5. Output a strict JSON list of task objects:
   [
     {
       "task_number": 1,
       "title": "Short title",
       "description": "Specific action instructions",
       "assigned_tools": ["code_sandbox"],
       "mcp_provider": "native",
       "dependencies": [],
       "can_run_parallel": true,
       "acceptance_criteria": ["Criteria 1", "Criteria 2"],
       "input_data": {"key": "val"}
     }
   ]
"""


class TaskGeneratorAgent:
    """Agent 2: Task Generator (Small tasks)."""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider
        self.model = model
        self.role = AgentRole.TASK_GENERATOR.value

    async def generate_tasks(
        self,
        goal: str,
        requirements_spec: str,
        max_subtasks: int = 4,
    ) -> List[GeneratedSubTask]:
        """Decompose requirements into small atomic tasks."""
        logger.info(f"Agent 2 [Task Generator]: Decomposing goal into small tasks (max {max_subtasks})")

        prompt = (
            f"Goal: {goal}\n\n"
            f"Requirements Specification:\n{requirements_spec[:1200]}\n\n"
            f"Generate between 2 and {max_subtasks} atomic micro-tasks as a JSON list:"
        )

        try:
            chat_model = ModelFactory.get_chat_model(
                provider_name=self.provider,
                model_name=self.model,
                temperature=0.2,
                streaming=False,
            )
            resp = await chat_model.ainvoke([
                SystemMessage(content=TASK_GENERATOR_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            text = resp.content if hasattr(resp, "content") else str(resp)

            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                raw_list = json.loads(text[start:end+1])
                subtasks = []
                for idx, item in enumerate(raw_list[:max_subtasks], start=1):
                    deps = item.get("dependencies", [])
                    can_parallel = item.get("can_run_parallel", len(deps) == 0)
                    subtasks.append(GeneratedSubTask(
                        task_number=idx,
                        title=item.get("title", f"Subtask {idx}"),
                        description=item.get("description", "Execute operation"),
                        assigned_tools=item.get("assigned_tools", ["code_sandbox"]),
                        mcp_provider=item.get("mcp_provider", "native"),
                        dependencies=deps,
                        can_run_parallel=can_parallel,
                        acceptance_criteria=item.get("acceptance_criteria", ["Executes without error"]),
                        input_data=item.get("input_data", {}),
                    ))
                if subtasks:
                    return subtasks
        except Exception as e:
            logger.warning(f"Task Generator LLM fallback: {e}")

        # Deterministic robust fallback with parallel task isolation modeling
        return [
            GeneratedSubTask(
                task_number=1,
                title="Verify Architecture & Dependencies",
                description=f"Validate configuration, environment, and prerequisites for '{goal[:40]}'",
                assigned_tools=["system_monitor"],
                mcp_provider="native",
                dependencies=[],
                can_run_parallel=True,
                acceptance_criteria=["System and database connections verified"],
                input_data={"target": goal},
            ),
            GeneratedSubTask(
                task_number=2,
                title="Execute Solution Implementation Logic",
                description=f"Run computational logic and verify implementation contracts for '{goal[:40]}'",
                assigned_tools=["code_sandbox"],
                mcp_provider="native",
                dependencies=[],
                can_run_parallel=True,
                acceptance_criteria=["Output generated without errors and meets constraints"],
                input_data={"code": "print('Multi-agent verification run successfully.')"},
            ),
            GeneratedSubTask(
                task_number=3,
                title="Inspect Grounded Workspace Knowledge",
                description=f"Cross-reference solution with workspace documents for '{goal[:40]}'",
                assigned_tools=["rag_retriever"],
                mcp_provider="native",
                dependencies=[1, 2],
                can_run_parallel=False,
                acceptance_criteria=["Relevant document references checked"],
                input_data={"query": goal},
            ),
        ]
