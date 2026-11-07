"""Hierarchical Context Window Management and Semantic Compaction for Multi-Agent Workflows."""

from dataclasses import dataclass, field
import json
import re
from typing import Any, Dict, List, Optional
from app.core.logging import logger


@dataclass
class ContextCompactionMetrics:
    """Metrics tracking context window compaction efficiency."""
    original_tokens: int
    compacted_tokens: int
    tokens_saved: int
    compression_ratio: float
    compaction_count: int


@dataclass
class CompactedTaskContext:
    """Structured executive summary of a completed subtask."""
    task_id: str
    task_number: int
    title: str
    agent_role: str
    status: str
    key_findings: str
    artifacts_summary: str
    validation_status: str


class ContextWindowManager:
    """Manages dynamic context windows, token budgeting, and hierarchical compaction.

    Retains critical decisions, contracts, and outputs while condensing verbose tool traces
    so LLMs maintain optimal reasoning capacity without exceeding token limits.
    """

    def __init__(self, max_context_tokens: int = 6000, target_compact_tokens: int = 1500):
        self.max_context_tokens = max_context_tokens
        self.target_compact_tokens = target_compact_tokens
        self.compaction_count = 0
        self._history_summaries: List[CompactedTaskContext] = []
        self._raw_subtasks_chars = 0

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Heuristic token estimation (~4 characters per token)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def compact_subtask(
        self,
        task_id: str,
        task_number: int,
        title: str,
        agent_role: str,
        status: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        artifacts: List[Dict[str, Any]],
        validation_result: Dict[str, Any],
    ) -> CompactedTaskContext:
        """Distill a detailed atomic subtask into a high-density structured summary."""
        # Track uncompacted raw character volume before summarization
        raw_char_count = (
            len(str(input_data)) + len(str(output_data)) +
            len(str(artifacts)) + len(str(validation_result)) + len(title)
        )
        self._raw_subtasks_chars += raw_char_count

        # Extract essential findings from output
        out_str = ""
        if isinstance(output_data, dict):
            # Prefer explicit summary or text fields
            if "summary" in output_data:
                out_str = str(output_data["summary"])
            elif "result" in output_data:
                out_str = str(output_data["result"])
            else:
                out_str = " ".join(f"{k}: {str(v)[:150]}" for k, v in list(output_data.items())[:4])
        else:
            out_str = str(output_data)[:300]

        # Condense output string to vital facts
        clean_out = re.sub(r"\s+", " ", out_str).strip()[:400]

        # Artifacts summary
        art_names = [a.get("name", "artifact") for a in artifacts if isinstance(a, dict)]
        art_summary = ", ".join(art_names) if art_names else "none"

        # Validation status
        val_status = "passed" if validation_result.get("passed", True) else "needs_review"
        val_score = validation_result.get("score", 1.0)

        compact = CompactedTaskContext(
            task_id=task_id,
            task_number=task_number,
            title=title,
            agent_role=agent_role,
            status=status,
            key_findings=clean_out or "Completed with verified outputs.",
            artifacts_summary=art_summary,
            validation_status=f"{val_status} (score: {val_score})",
        )
        self._history_summaries.append(compact)
        return compact

    def build_consolidated_context(
        self,
        goal: str,
        requirements: Optional[str] = None,
        active_task_detail: Optional[str] = None,
        raw_traces: Optional[List[str]] = None,
    ) -> (str, ContextCompactionMetrics):
        """Construct the prompt context incorporating compacted past tasks and full active task detail."""
        parts: List[str] = [f"### High-Level Workflow Goal\n{goal.strip()}"]

        if requirements:
            # Keep requirements concise
            req_summary = requirements.strip()[:1000]
            parts.append(f"\n### Core Requirements & Constraints\n{req_summary}")

        # Past compacted tasks
        if self._history_summaries:
            parts.append("\n### Completed Subtasks (Compact State):")
            for item in self._history_summaries:
                parts.append(
                    f"- Subtask {item.task_number} [{item.agent_role.upper()}] '{item.title}': "
                    f"{item.key_findings} (Validation: {item.validation_status}, Artifacts: {item.artifacts_summary})"
                )

        # Active task gets full focus
        if active_task_detail:
            parts.append(f"\n### Active Task In Execution\n{active_task_detail.strip()}")

        consolidated_text = "\n".join(parts)
        compacted_tokens = self.estimate_tokens(consolidated_text)

        # Compute original tokens before compaction
        raw_total_chars = (
            len(goal) + len(requirements or "") + len(active_task_detail or "") + self._raw_subtasks_chars
        )
        if raw_traces:
            raw_total_chars += sum(len(t) for t in raw_traces)
        original_tokens = max(compacted_tokens, self.estimate_tokens(" " * raw_total_chars))

        tokens_saved = max(0, original_tokens - compacted_tokens)
        compression_ratio = round((tokens_saved / original_tokens * 100), 1) if original_tokens > 0 else 0.0

        if tokens_saved > 0:
            self.compaction_count += 1

        metrics = ContextCompactionMetrics(
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            tokens_saved=tokens_saved,
            compression_ratio=compression_ratio,
            compaction_count=self.compaction_count,
        )

        return consolidated_text, metrics
