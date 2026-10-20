"""Agent 3: Task Executor (Collaborative MCP Tool Execution with Anonymous Scrubbing)."""

import time
from typing import Any, Dict, List, Optional
from app.agent.multi_agent.protocol import GeneratedSubTask
from app.core.logging import logger
from app.mcp.registry import mcp_registry
from app.models.multi_agent import AgentRole


class TaskExecutorAgent:
    """Agent 3: Task Executor."""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider
        self.model = model
        self.role = AgentRole.TASK_EXECUTOR.value

    async def execute_subtask(
        self,
        subtask: GeneratedSubTask,
        context_str: str,
        anonymous: bool = True,
    ) -> Dict[str, Any]:
        """Execute atomic subtask using assigned tools via MCP client or native registry."""
        t0 = time.perf_counter()
        logger.info(
            f"Agent 3 [Task Executor]: Executing Subtask {subtask.task_number}: '{subtask.title}' "
            f"(Tools: {subtask.assigned_tools}, Anonymous: {anonymous})"
        )

        logs: List[str] = [
            f"Started execution of Subtask {subtask.task_number}: {subtask.title}",
            f"Target provider: {subtask.mcp_provider} | Anonymous proxying: {anonymous}",
        ]
        tool_results: Dict[str, Any] = {}
        artifacts: List[Dict[str, Any]] = []

        # Execute all tools assigned to this subtask
        for tool_name in subtask.assigned_tools:
            tool_args = dict(subtask.input_data)
            logs.append(f"Invoking tool '{tool_name}' via MCP client...")

            call_res = await mcp_registry.execute_tool(
                tool_name=tool_name,
                arguments=tool_args,
                anonymous=anonymous,
                provider=subtask.mcp_provider if subtask.mcp_provider != "native" else None,
            )

            res_text = call_res.get_text()
            tool_results[tool_name] = {
                "is_error": call_res.isError,
                "text": res_text,
                "metadata": call_res.metadata,
            }
            logs.append(f"Tool '{tool_name}' finished (Error: {call_res.isError}). Output preview: {res_text[:120]}")

            if not call_res.isError:
                artifacts.append({
                    "name": f"{tool_name}_output",
                    "type": "text/plain",
                    "preview": res_text[:300],
                })

        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        logs.append(f"Subtask {subtask.task_number} completed execution in {duration_ms}ms")

        # Synthesize output data
        primary_tool_output = "\n".join(
            v["text"] for v in tool_results.values() if isinstance(v, dict) and "text" in v
        )
        if not primary_tool_output:
            primary_tool_output = f"Subtask '{subtask.title}' completed successfully."

        return {
            "task_number": subtask.task_number,
            "title": subtask.title,
            "status": "completed",
            "execution_duration_ms": duration_ms,
            "tool_results": tool_results,
            "output_data": {
                "summary": primary_tool_output[:600],
                "details": primary_tool_output,
            },
            "artifacts": artifacts,
            "execution_logs": logs,
        }
