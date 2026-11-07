"""Agent 5: Deployer (Deploy, Monitor, and Alert for Syntaxual & Logical Errors)."""

import ast
import json
import time
from typing import Any, Dict, List, Optional

from app.core.logging import logger
from app.mcp.registry import mcp_registry
from app.models.multi_agent import AgentRole


class DeployerAgent:
    """Agent 5: Deployer (Deploy, Monitor, & Alert for syntaxual, logical, and telemetry errors)."""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider
        self.model = model
        self.role = AgentRole.DEPLOYER.value

    def verify_syntax(self, executed_tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Inspect executed task code snippets, artifacts, and input data for syntax errors."""
        syntax_errors = []

        for task_info in executed_tasks:
            t_num = task_info.get("task_number", 0)
            t_title = task_info.get("title", f"Subtask {t_num}")

            # 1. Check code in input_data
            input_data = task_info.get("input_data", {})
            code_candidates = []
            if isinstance(input_data, dict):
                if "code" in input_data and isinstance(input_data["code"], str):
                    code_candidates.append(input_data["code"])

            # 2. Check code inside artifacts or tool results
            tool_results = task_info.get("tool_results", {})
            if isinstance(tool_results, dict):
                for tname, tres in tool_results.items():
                    if isinstance(tres, dict):
                        meta = tres.get("metadata", {})
                        if isinstance(meta, dict) and "code" in meta and isinstance(meta["code"], str):
                            code_candidates.append(meta["code"])

            for code_str in code_candidates:
                try:
                    ast.parse(code_str)
                except SyntaxError as e:
                    err_detail = {
                        "task_number": t_num,
                        "task_title": t_title,
                        "line": e.lineno,
                        "message": str(e.msg),
                        "snippet": code_str[:120],
                    }
                    syntax_errors.append(err_detail)
                    logger.warning(f"Deployer syntax error detected in subtask {t_num}: {e}")

        return syntax_errors

    def verify_logic(self, executed_tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Inspect executed tasks for logical discrepancies, unsatisfied criteria, and failed tools."""
        logical_errors = []

        for task_info in executed_tasks:
            t_num = task_info.get("task_number", 0)
            t_title = task_info.get("title", f"Subtask {t_num}")

            # 1. Check validator verdict
            val_res = task_info.get("validation_result", {})
            if isinstance(val_res, dict):
                if val_res.get("passed") is False:
                    logical_errors.append({
                        "task_number": t_num,
                        "task_title": t_title,
                        "type": "validation_failure",
                        "score": val_res.get("score", 0),
                        "message": val_res.get("feedback", "Validation checks failed acceptance criteria."),
                    })

                # Check unsatisfied individual checks
                checks = val_res.get("checks", [])
                if isinstance(checks, list):
                    for c in checks:
                        if isinstance(c, dict) and c.get("satisfied") is False:
                            logical_errors.append({
                                "task_number": t_num,
                                "task_title": t_title,
                                "type": "criterion_unsatisfied",
                                "criterion": c.get("criterion", "Unknown"),
                                "note": c.get("note", "Unsatisfied"),
                            })

            # 2. Check tool execution errors
            tool_results = task_info.get("tool_results", {})
            if isinstance(tool_results, dict):
                for tname, tres in tool_results.items():
                    if isinstance(tres, dict) and tres.get("is_error"):
                        logical_errors.append({
                            "task_number": t_num,
                            "task_title": t_title,
                            "type": "tool_error",
                            "tool_name": tname,
                            "message": str(tres.get("text", "Tool reported execution failure."))[:200],
                        })

        return logical_errors

    async def deploy_and_monitor(
        self,
        workflow_id: str,
        goal: str,
        executed_tasks: List[Dict[str, Any]],
        environment: str = "production",
    ) -> Dict[str, Any]:
        """Execute deployment staging, post-rollout health monitoring, and alert dispatching."""
        logger.info(f"Agent 5 [Deployer]: Initiating deployment & monitoring for workflow '{workflow_id}'")
        logs: List[str] = []

        # 1. Rollout / Deploy via deploy simulator tool
        logs.append(f"Deploying solution package for '{goal[:40]}' to {environment}...")
        deploy_res = await mcp_registry.execute_tool(
            tool_name="deploy_simulator",
            arguments={"artifact_name": f"workflow_{workflow_id}", "environment": environment},
            anonymous=True,
        )
        logs.append(f"Deploy rollout status: {deploy_res.get_text()[:120]}")

        # 2. Run Syntax & Logical Error Analysis
        syntax_errors = self.verify_syntax(executed_tasks)
        logical_errors = self.verify_logic(executed_tasks)
        has_syntax_errors = len(syntax_errors) > 0
        has_logical_errors = len(logical_errors) > 0

        logs.append(
            f"Pre-flight Code & Logic Checks: {len(syntax_errors)} syntax errors, {len(logical_errors)} logical errors detected."
        )

        # 3. System Health & Performance Monitoring
        logs.append("Running real-time post-deployment health and telemetry checks...")
        monitor_res = await mcp_registry.execute_tool(
            tool_name="system_monitor",
            arguments={},
            anonymous=True,
        )
        telemetry_text = monitor_res.get_text()
        db_status = monitor_res.metadata.get("db_status", "healthy")
        is_unhealthy = "unhealthy" in db_status.lower()
        logs.append(f"Health Telemetry: {telemetry_text[:120]}")

        # 4. Operational Alerting (Syntax, Logical & Telemetry)
        alerts_dispatched = []

        if has_syntax_errors:
            syn_msg = (
                f"[SYNTAX ERROR] Workflow '{workflow_id}' encountered {len(syntax_errors)} syntax error(s): "
                f"{json.dumps(syntax_errors[:2])}"
            )
            await mcp_registry.execute_tool(
                tool_name="alert_dispatcher",
                arguments={"severity": "CRITICAL", "message": syn_msg, "channel": "system_log"},
                anonymous=True,
            )
            alerts_dispatched.append({"severity": "CRITICAL", "message": syn_msg})
            logs.append(f"CRITICAL Alert dispatched: Syntax error in deliverables.")

        if has_logical_errors:
            log_msg = (
                f"[LOGICAL ERROR] Workflow '{workflow_id}' encountered {len(logical_errors)} logical issue(s): "
                f"{json.dumps(logical_errors[:2])}"
            )
            await mcp_registry.execute_tool(
                tool_name="alert_dispatcher",
                arguments={"severity": "WARNING", "message": log_msg, "channel": "system_log"},
                anonymous=True,
            )
            alerts_dispatched.append({"severity": "WARNING", "message": log_msg})
            logs.append(f"WARNING Alert dispatched: Logical discrepancy detected.")

        if is_unhealthy:
            db_msg = f"[HEALTH WARNING] Workflow '{workflow_id}' system status degraded: {db_status}"
            await mcp_registry.execute_tool(
                tool_name="alert_dispatcher",
                arguments={"severity": "WARNING", "message": db_msg, "channel": "system_log"},
                anonymous=True,
            )
            alerts_dispatched.append({"severity": "WARNING", "message": db_msg})
            logs.append(f"WARNING Alert dispatched: System status unhealthy.")

        if not has_syntax_errors and not has_logical_errors and not is_unhealthy:
            clean_msg = (
                f"Multi-Agent Workflow '{workflow_id}' deployed to {environment} with ZERO syntax or logical errors. "
                f"Tasks verified: {len(executed_tasks)}. System status: {db_status}."
            )
            await mcp_registry.execute_tool(
                tool_name="alert_dispatcher",
                arguments={"severity": "INFO", "message": clean_msg, "channel": "system_log"},
                anonymous=True,
            )
            alerts_dispatched.append({"severity": "INFO", "message": clean_msg})
            logs.append(f"INFO Alert dispatched: Clean deployment verified.")

        overall_health = "optimal" if (not has_syntax_errors and not has_logical_errors and not is_unhealthy) else "degraded"

        return {
            "status": "deployed",
            "environment": environment,
            "health": overall_health,
            "db_status": db_status,
            "deployment_report": deploy_res.get_text(),
            "telemetry": telemetry_text,
            "syntax_errors": syntax_errors,
            "logical_errors": logical_errors,
            "has_syntax_errors": has_syntax_errors,
            "has_logical_errors": has_logical_errors,
            "alerts": alerts_dispatched,
            "alert": alerts_dispatched[0] if alerts_dispatched else {"severity": "INFO", "message": "Deployed."},
            "logs": logs,
            "timestamp": time.time(),
        }
