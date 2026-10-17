"""Mid-run replanning.

When a step fails, the replanner picks a recovery strategy instead of
aborting the whole plan:

- ``retry_modified`` — retry the same tool with simplified args
- ``substitute_tool`` — swap in an alternative tool for the same purpose
- ``skip`` — drop a non-critical step and mark the plan degraded
- ``abort`` — stop with partial results (critical step, no options left)

Every decision carries a human-readable reason and is appended to the
plan's replan log. Replanning is bounded by ``max_replans``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # avoid a runtime import cycle with execute.py
    from .execute import ToolRegistry
    from .planning import Plan, Step

RETRY_MODIFIED = "retry_modified"
SUBSTITUTE_TOOL = "substitute_tool"
SKIP = "skip"
ABORT = "abort"

# Alternative tools that serve the same purpose (checked against the registry).
TOOL_ALTERNATIVES: Dict[str, List[str]] = {
    "web_search": ["fallback_search"],
    "fallback_search": ["web_search"],
    "calculator": [],
    "summarizer": [],
}


@dataclass
class ReplanDecision:
    strategy: str
    reason: str
    new_tool: Optional[str] = None
    new_args: Optional[Dict[str, Any]] = None


@dataclass
class ReplanEvent:
    seq: int
    step_id: str
    strategy: str
    reason: str


def _simplify_args(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic arg simplification for a retry."""
    simplified = dict(args)
    if tool in ("web_search", "fallback_search") and "query" in simplified:
        query = str(simplified["query"])
        # Drop anything that looks like a $ref or a long tail; keep the head.
        head = query.split("$")[0].strip().split()
        simplified["query"] = " ".join(head[:4]) or query
    return simplified


def replan(plan: "Plan", failed_step: "Step", error: str,
           registry: "ToolRegistry", max_replans: int = 3) -> ReplanDecision:
    """Choose a recovery strategy for a failed step."""
    if plan.replans_used >= max_replans:
        return ReplanDecision(
            strategy=ABORT,
            reason=(f"replan budget exhausted ({plan.replans_used}/{max_replans}); "
                    f"aborting at step {failed_step.id}: {error}"),
        )

    attempts = getattr(failed_step, "_attempts", 0)
    tried = getattr(failed_step, "_tried_tools", set())

    # 1. Retry once with simplified args before trying anything drastic.
    if attempts == 0:
        failed_step._attempts = 1  # noqa: SLF001 - bookkeeping on the step
        return ReplanDecision(
            strategy=RETRY_MODIFIED,
            reason=(f"step {failed_step.id} failed on first attempt ({error}); "
                    f"retrying {failed_step.tool} with simplified args"),
            new_args=_simplify_args(failed_step.tool, failed_step.args),
        )

    # 2. Substitute an alternative tool registered for the same purpose,
    #    skipping tools already tried for this step.
    available = set(registry.tool_names())
    for alt in TOOL_ALTERNATIVES.get(failed_step.tool, []):
        if alt in available and alt != failed_step.tool and alt not in tried:
            return ReplanDecision(
                strategy=SUBSTITUTE_TOOL,
                reason=(f"step {failed_step.id}: {failed_step.tool} failed twice "
                        f"({error}); substituting {alt}"),
                new_tool=alt,
            )

    # 3. Skip if the step is not critical; the plan continues degraded.
    if not failed_step.critical:
        return ReplanDecision(
            strategy=SKIP,
            reason=(f"step {failed_step.id} is non-critical and has no working "
                    f"tool ({error}); skipping, plan marked degraded"),
        )

    # 4. Nothing left: abort with partial results.
    return ReplanDecision(
        strategy=ABORT,
        reason=(f"step {failed_step.id} is critical and no recovery applies "
                f"({error}); aborting with partial results"),
    )


def reset_attempt_counters(plan: "Plan") -> None:
    """Clear per-step retry bookkeeping (used between independent runs)."""
    for step in plan.steps:
        for attr in ("_attempts", "_tried_tools"):
            if hasattr(step, attr):
                delattr(step, attr)
