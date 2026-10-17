"""Deep agent patterns: plan-and-execute with replanning and episodic memory."""

from .agent import DeepAgent, Trace
from .execute import ExecutionReport, PlanExecutor, StepResult, ToolError, ToolRegistry
from .memory import Episode, EpisodicMemory
from .planning import (
    FAILED, PENDING, RUNNING, SKIPPED, SUCCEEDED,
    Plan, Step, decompose, extract_subject,
)
from .replan import (
    ABORT, RETRY_MODIFIED, SKIP, SUBSTITUTE_TOOL,
    ReplanDecision, ReplanEvent, replan,
)

__all__ = [
    "DeepAgent", "Trace",
    "ExecutionReport", "PlanExecutor", "StepResult", "ToolError", "ToolRegistry",
    "Episode", "EpisodicMemory",
    "FAILED", "PENDING", "RUNNING", "SKIPPED", "SUCCEEDED",
    "Plan", "Step", "decompose", "extract_subject",
    "ABORT", "RETRY_MODIFIED", "SKIP", "SUBSTITUTE_TOOL",
    "ReplanDecision", "ReplanEvent", "replan",
]
