"""DeepAgent: plan-and-execute with mid-run replanning and episodic memory.

``run(goal)``:
1. ask episodic memory for relevant lessons,
2. let memory adjust the plan (e.g. prefer a tool that worked before),
3. decompose the goal into an inspectable plan,
4. execute with replanning on failure,
5. record the episode — including what the replanner learned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .execute import ExecutionReport, PlanExecutor, ToolRegistry
from .memory import Episode, EpisodicMemory
from .planning import PENDING, Plan, decompose
from .replan import ABORT, SKIP, SUBSTITUTE_TOOL, reset_attempt_counters

_PREFER_RE = re.compile(r"prefer (\w+) over (\w+)")


@dataclass
class Trace:
    """Everything that happened during one run — the inspectable record."""

    goal: str
    plan: Plan
    report: ExecutionReport
    memory_suggestions: List[str] = field(default_factory=list)
    memory_hits: List[str] = field(default_factory=list)
    outcome: str = "pending"
    episode: Optional[Episode] = None


class DeepAgent:
    def __init__(self, registry: Optional[ToolRegistry] = None,
                 memory: Optional[EpisodicMemory] = None,
                 max_replans: int = 3) -> None:
        self.registry = registry or ToolRegistry()
        self.memory = memory
        self.executor = PlanExecutor(self.registry, max_replans=max_replans)

    # -- memory-guided planning -----------------------------------------
    def _apply_memory(self, plan: Plan, suggestions: List[str]) -> List[str]:
        """Rewrite plan steps using 'prefer X over Y' lessons. Returns hits."""
        hits = []
        for lesson in suggestions:
            m = _PREFER_RE.search(lesson)
            if not m:
                continue
            preferred, avoided = m.group(1), m.group(2)
            if preferred not in self.registry.tool_names():
                continue
            for step in plan.steps:
                if step.tool == avoided and step.status == PENDING:
                    step.tool = preferred
                    plan.degraded = True
                    hits.append(
                        f"step {step.id}: memory lesson applied — "
                        f"{preferred} instead of {avoided}")
        return hits

    # -- episode lessons --------------------------------------------------
    def _lessons_from_run(self, plan: Plan, report: ExecutionReport) -> List[str]:
        lessons: List[str] = []
        for event in plan.replan_log:
            strategy = event["strategy"]
            if strategy == SUBSTITUTE_TOOL:
                reason = event["reason"]
                m = re.search(r"substituting (\w+)", reason)
                new_tool = m.group(1) if m else "alternative"
                m2 = re.search(r"(\w+) failed twice", reason)
                old_tool = m2.group(1) if m2 else "tool"
                lessons.append(
                    f"prefer {new_tool} over {old_tool} for '{plan.goal}'")
            elif strategy == "retry_modified":
                lessons.append(
                    f"retry with simplified args often recovers a failed "
                    f"{event['step_id']}")
            elif strategy == SKIP:
                lessons.append(
                    f"step {event['step_id']} is safely skippable when its "
                    f"tool is unavailable")
            elif strategy == ABORT:
                lessons.append(
                    f"goal '{plan.goal}' aborted at {event['step_id']}: "
                    f"{event['reason'][:80]}")
        if report.outcome == "success" and not plan.replan_log:
            lessons.append(f"plan template for '{plan.goal}' works first-try")
        return lessons

    # -- main entry --------------------------------------------------------
    def run(self, goal: str) -> Trace:
        suggestions = (self.memory.suggest_from_memory(goal)
                       if self.memory else [])
        plan = decompose(goal, set(self.registry.tool_names()))
        reset_attempt_counters(plan)
        memory_hits = self._apply_memory(plan, suggestions)

        report = self.executor.run(plan)

        outcome = report.outcome
        lessons = self._lessons_from_run(plan, report)
        episode = None
        if self.memory is not None:
            episode = self.memory.record_episode(
                task=goal,
                plan_summary=[s.description for s in plan.steps],
                outcome=outcome,
                lessons=lessons,
            )

        return Trace(
            goal=goal,
            plan=plan,
            report=report,
            memory_suggestions=suggestions,
            memory_hits=memory_hits,
            outcome=outcome,
            episode=episode,
        )
