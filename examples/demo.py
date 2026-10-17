"""Run 1: primary search fails twice and the agent recovers. Run 2: memory applies the lesson."""
import tempfile
from pathlib import Path

from deepagents import DeepAgent, EpisodicMemory
from deepagents.execute import ToolRegistry

with tempfile.TemporaryDirectory() as tmp:
    memory = EpisodicMemory(str(Path(tmp) / "memory.jsonl"))

    registry = ToolRegistry()
    registry.fail_next("web_search", count=2)
    trace = DeepAgent(registry=registry, memory=memory).run("research EV pricing")
    print("Run 1 plan:")
    for s in trace.plan.steps:
        print(f"  {s.id} {s.tool:<16} {s.description}")
    print("Replan log:")
    for e in trace.plan.replan_log:
        print(f"  {e['step_id']} {e['strategy']}: {e['reason']}")
    print("Outcome:", trace.outcome, "| degraded:", trace.plan.degraded)
    print("Lessons recorded:", trace.episode.lessons)

    trace2 = DeepAgent(memory=memory).run("research EV pricing trends")
    print("Run 2 memory hits:")
    for h in trace2.memory_hits:
        print("  ", h)
    print("Run 2 replans:", len(trace2.plan.replan_log), "| outcome:", trace2.outcome)

    registry3 = ToolRegistry()
    registry3.fail_next("web_search", count=5)
    registry3.fail_next("fallback_search", count=5)
    trace3 = DeepAgent(registry=registry3).run("research EV pricing")
    print("Run 3 (both search tools down):", trace3.outcome)
    for e in trace3.plan.replan_log:
        print(f"  {e['step_id']} {e['strategy']}")
