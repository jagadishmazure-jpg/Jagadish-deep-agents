"""Plan execution against a registry of (fake) tools.

The executor runs steps in order, resolves ``$sN.output`` references to
prior step outputs, records a result per step, and hands failures to the
replanner instead of aborting — mid-run recovery is the point.
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .planning import (
    FAILED, PENDING, RUNNING, SKIPPED, SUCCEEDED, Plan, Step,
)
from .replan import ReplanEvent, replan


class ToolError(Exception):
    """A tool call failed (deterministic, injectable for tests)."""


# ---------------------------------------------------------------------------
# Fake tools — deterministic stand-ins for real MCP / API tools
# ---------------------------------------------------------------------------

def fake_web_search(query: str) -> str:
    return (f"Results for '{query}': "
            f"[1] {query} — overview and specs; "
            f"[2] {query} — pricing and reviews")


def fake_fallback_search(query: str) -> str:
    return f"Cached results for '{query}': [1] {query} — cached snapshot"


def fake_summarizer(text: str, focus: str = "summary") -> str:
    snippet = text[:80].replace("\n", " ")
    return f"Summary({focus}): {snippet}..."


_SAFE_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ToolError(f"unsupported expression element: {ast.dump(node)[:60]}")


def fake_calculator(expression: str) -> str:
    try:
        value = _safe_eval(ast.parse(expression.strip(), mode="eval"))
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 - deterministic wrap
        raise ToolError(f"cannot evaluate {expression!r}: {exc}") from exc
    return f"{expression.strip()} = {value}"


class ToolRegistry:
    """Named tools plus deterministic failure injection for tests."""

    def __init__(self) -> None:
        self._tools: Dict[str, Callable[..., str]] = {}
        self._failures: Dict[str, List[Exception]] = {}
        self.register("web_search", lambda query: fake_web_search(query))
        self.register("fallback_search", lambda query: fake_fallback_search(query))
        self.register("calculator", lambda expression: fake_calculator(expression))
        self.register("summarizer",
                       lambda text, focus="summary": fake_summarizer(text, focus))

    def register(self, name: str, fn: Callable[..., str]) -> None:
        self._tools[name] = fn

    def tool_names(self) -> List[str]:
        return sorted(self._tools.keys())

    def fail_next(self, tool: str, count: int = 1,
                  error: Optional[Exception] = None) -> None:
        """Make the next `count` calls to `tool` raise (test hook)."""
        self._failures.setdefault(tool, []).extend(
            [error or ToolError(f"injected failure in {tool}")] * count)

    def call(self, name: str, args: Dict[str, Any]) -> str:
        if name not in self._tools:
            raise ToolError(f"unknown tool: {name}")
        if self._failures.get(name):
            raise self._failures[name].pop(0)
        try:
            return self._tools[name](**args)
        except TypeError as exc:
            raise ToolError(f"bad args for {name}: {exc}") from exc


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    step_id: str
    status: str
    output: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0


@dataclass
class ExecutionReport:
    plan: Plan
    results: List[StepResult] = field(default_factory=list)
    outcome: str = "pending"  # success | partial | failed

    def output_of(self, step_id: str) -> Optional[str]:
        for r in self.results:
            if r.step_id == step_id and r.status == SUCCEEDED:
                return r.output
        return None


def resolve_args(args: Dict[str, Any], report: ExecutionReport) -> Dict[str, Any]:
    """Resolve ``$sN.output`` references against completed step results."""
    resolved = {}
    for k, v in args.items():
        if isinstance(v, str) and v.startswith("$s") and v.endswith(".output"):
            ref = v[1:].split(".")[0]
            output = report.output_of(ref)
            if output is None:
                raise ToolError(f"unresolvable reference {v!r}: "
                                f"step {ref} has no successful output")
            resolved[k] = output
        else:
            resolved[k] = v
    return resolved


class PlanExecutor:
    """Runs a Plan step by step, replanning on failure instead of aborting."""

    def __init__(self, registry: ToolRegistry, max_replans: int = 3) -> None:
        self.registry = registry
        self.max_replans = max_replans

    def run(self, plan: Plan) -> ExecutionReport:
        report = ExecutionReport(plan=plan)
        by_id = {s.id: s for s in plan.steps}

        for step in plan.steps:
            step.status = RUNNING
            result = StepResult(step_id=step.id, status=RUNNING)
            report.results.append(result)
            try:
                args = resolve_args(step.args, report)
                result.attempts += 1
                result.output = self.registry.call(step.tool, args)
                result.status = SUCCEEDED
                step.status = SUCCEEDED
            except Exception as exc:  # noqa: BLE001 - every failure goes to replan
                self._handle_failure(plan, step, result, report, str(exc),
                                     by_id)
                if report.outcome == "failed":
                    break
        if report.outcome == "pending":
            report.outcome = ("success" if all(
                r.status in (SUCCEEDED, SKIPPED) for r in report.results)
                else "partial")
        return report

    def _handle_failure(self, plan: Plan, step: Step, result: StepResult,
                        report: ExecutionReport, error: str,
                        by_id: Dict[str, Step]) -> None:
        # Recovery loop: retry -> substitute -> skip/abort, bounded by the
        # replan budget. Each iteration consumes one replan (except abort).
        tried = getattr(step, "_tried_tools", set())
        tried.add(step.tool)
        step._tried_tools = tried  # noqa: SLF001 - bookkeeping on the step
        while True:
            decision = replan(plan, step, error, self.registry,
                              max_replans=self.max_replans)
            plan.replan_log.append(ReplanEvent(
                seq=len(plan.replan_log) + 1,
                step_id=step.id,
                strategy=decision.strategy,
                reason=decision.reason,
            ).__dict__)

            if decision.strategy == "abort":
                result.status = FAILED
                result.error = error
                step.status = FAILED
                report.outcome = "failed"
                return

            plan.replans_used += 1
            if decision.strategy == "retry_modified":
                step.args = decision.new_args or step.args
            elif decision.strategy == "substitute_tool":
                step.tool = decision.new_tool or step.tool
                if decision.new_args:
                    step.args = decision.new_args
                plan.degraded = True
            elif decision.strategy == "skip":
                result.status = SKIPPED
                result.error = error
                step.status = SKIPPED
                plan.degraded = True
                return

            # Attempt the recovery; on failure, loop back into replan.
            step.status = RUNNING
            try:
                args = resolve_args(step.args, report)
                result.attempts += 1
                result.output = self.registry.call(step.tool, args)
                result.status = SUCCEEDED
                result.error = None
                step.status = SUCCEEDED
                return
            except Exception as exc2:  # noqa: BLE001
                tried.add(step.tool)
                error = str(exc2)
