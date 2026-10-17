"""Tests for the deepagents package — all deterministic, no network/keys."""


import pytest

from deepagents import (
    ABORT,
    RETRY_MODIFIED,
    SKIP,
    SUBSTITUTE_TOOL,
    DeepAgent,
    EpisodicMemory,
    Plan,
    PlanExecutor,
    Step,
    ToolRegistry,
    decompose,
    extract_subject,
)
from deepagents.execute import ToolError
from deepagents.planning import SUCCEEDED

ALL_TOOLS = {"web_search", "fallback_search", "calculator", "summarizer"}


def make_registry() -> ToolRegistry:
    return ToolRegistry()


# ---------------------------------------------------------------------------
# Decomposition
# ---------------------------------------------------------------------------

def test_decompose_research_goal_yields_ordered_steps():
    plan = decompose("research EV pricing", ALL_TOOLS)
    assert [s.id for s in plan.steps] == ["s1", "s2", "s3", "s4"]
    assert [s.tool for s in plan.steps] == [
        "web_search", "summarizer", "web_search", "summarizer"]
    assert plan.steps[0].args == {"query": "EV pricing"}
    assert plan.steps[1].args["text"] == "$s1.output"
    assert plan.steps[3].args["text"] == "$s3.output"


def test_decompose_extracts_subject():
    assert extract_subject("research EV pricing") == "EV pricing"
    assert extract_subject("please summarize quarterly report") == "quarterly report"


def test_decompose_drops_steps_with_missing_tools_and_remaps_refs():
    plan = decompose("research EV pricing", {"web_search"})
    assert [s.tool for s in plan.steps] == ["web_search", "web_search"]
    assert [s.id for s in plan.steps] == ["s1", "s2"]
    # The surviving "alternatives" step keeps its (ref-free) args.
    assert plan.steps[1].args == {"query": "EV pricing alternatives"}


def test_decompose_unknown_goal_falls_back_to_generic_plan():
    plan = decompose("organize my sock drawer", ALL_TOOLS)
    assert len(plan.steps) == 2
    assert plan.steps[0].tool == "web_search"
    assert plan.steps[1].tool == "summarizer"


def test_plan_is_inspectable_data_before_execution():
    plan = decompose("research EV pricing", ALL_TOOLS)
    assert plan.goal == "research EV pricing"
    assert all(s.status == "pending" for s in plan.steps)
    assert all(s.description for s in plan.steps)


def test_decompose_is_deterministic():
    first = decompose("research EV pricing", ALL_TOOLS)
    second = decompose("research EV pricing", ALL_TOOLS)
    assert [(s.id, s.tool, s.args) for s in first.steps] == [
        (s.id, s.tool, s.args) for s in second.steps]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def test_executor_runs_all_steps_and_records_results():
    report = PlanExecutor(make_registry()).run(
        decompose("research EV pricing", ALL_TOOLS))
    assert report.outcome == "success"
    assert len(report.results) == 4
    assert all(r.status == SUCCEEDED for r in report.results)
    assert all(r.output for r in report.results)


def test_executor_resolves_output_references_between_steps():
    report = PlanExecutor(make_registry()).run(
        decompose("research EV pricing", ALL_TOOLS))
    search_out = report.results[0].output
    summary_out = report.results[1].output
    assert "EV pricing" in search_out
    assert "EV pricing" in summary_out  # summarizer received s1's output


def test_unknown_tool_fails_step_and_eventually_aborts():
    plan = Plan(goal="x", steps=[Step(id="s1", description="d", tool="nope")])
    report = PlanExecutor(make_registry()).run(plan)
    assert report.outcome == "failed"
    strategies = [e["strategy"] for e in plan.replan_log]
    assert strategies == [RETRY_MODIFIED, ABORT]


# ---------------------------------------------------------------------------
# Replanning
# ---------------------------------------------------------------------------

def test_failed_step_retries_with_simplified_args_then_succeeds():
    registry = make_registry()
    registry.fail_next("web_search", 1)
    plan = decompose("research EV pricing", ALL_TOOLS)
    report = PlanExecutor(registry).run(plan)
    assert report.outcome == "success"
    assert report.results[0].attempts == 2
    first = plan.replan_log[0]
    assert first["strategy"] == RETRY_MODIFIED
    assert "simplified args" in first["reason"]


def test_persistent_failure_substitutes_alternative_tool():
    registry = make_registry()
    registry.fail_next("web_search", 2)  # fail, fail-again, then substitute
    plan = decompose("research EV pricing", ALL_TOOLS)
    report = PlanExecutor(registry).run(plan)
    assert report.outcome == "success"
    strategies = [e["strategy"] for e in plan.replan_log]
    assert strategies == [RETRY_MODIFIED, SUBSTITUTE_TOOL]
    assert "Cached results" in report.results[0].output
    assert plan.degraded is True


def test_non_critical_step_skips_and_plan_continues_degraded(monkeypatch):
    import sys
    replan_mod = sys.modules["deepagents.replan"]  # module, not the replan fn

    def always_fail(**kwargs):
        raise ToolError("always fails")

    registry = make_registry()
    registry.register("primary_search", always_fail)
    registry.register("backup_search", always_fail)
    monkeypatch.setitem(replan_mod.TOOL_ALTERNATIVES,
                        "primary_search", ["backup_search"])
    plan = Plan(goal="g", steps=[
        Step(id="s1", description="search", tool="web_search",
             args={"query": "x"}),
        Step(id="s2", description="optional extra", tool="primary_search",
             args={"query": "y"}, critical=False),
        Step(id="s3", description="sum", tool="summarizer",
             args={"text": "$s1.output", "focus": "f"}),
    ])
    report = PlanExecutor(registry).run(plan)
    assert report.outcome == "success"
    assert report.results[1].status == "skipped"
    assert report.results[2].status == SUCCEEDED
    assert plan.degraded is True
    strategies = [e["strategy"] for e in plan.replan_log]
    assert strategies == [RETRY_MODIFIED, SUBSTITUTE_TOOL, SKIP]


def test_critical_step_with_no_recovery_aborts_with_partial_results():
    registry = make_registry()
    registry.fail_next("calculator", 10)
    plan = decompose("calculate 2+2", ALL_TOOLS)
    report = PlanExecutor(registry).run(plan)
    assert report.outcome == "failed"
    assert len(report.results) == 1  # second step never ran
    assert plan.steps[1].status == "pending"
    strategies = [e["strategy"] for e in plan.replan_log]
    assert strategies == [RETRY_MODIFIED, ABORT]


def test_max_replans_budget_is_respected():
    registry = make_registry()
    registry.fail_next("calculator", 10)
    plan = decompose("calculate 2+2", ALL_TOOLS)
    report = PlanExecutor(registry, max_replans=1).run(plan)
    assert report.outcome == "failed"
    assert plan.replans_used <= 1


def test_every_replan_decision_is_logged_with_reason():
    registry = make_registry()
    registry.fail_next("web_search", 5)
    plan = decompose("research EV pricing", ALL_TOOLS)
    PlanExecutor(registry).run(plan)
    assert plan.replan_log
    for event in plan.replan_log:
        assert event["step_id"]
        assert event["strategy"]
        assert event["reason"]


# ---------------------------------------------------------------------------
# Episodic memory
# ---------------------------------------------------------------------------

def test_memory_record_and_recall_roundtrip(tmp_path):
    mem = EpisodicMemory(str(tmp_path / "m.jsonl"))
    mem.record_episode("research EV pricing", ["search", "summarize"],
                       "success", ["lesson A"])
    hits = mem.recall("EV pricing")
    assert len(hits) == 1
    assert hits[0].task == "research EV pricing"


def test_memory_recall_ranks_relevant_episode_first(tmp_path):
    mem = EpisodicMemory(str(tmp_path / "m.jsonl"))
    mem.record_episode("bake sourdough bread recipe", ["mix", "bake"],
                       "success", ["keep starter fed"])
    mem.record_episode("research EV pricing and compare models",
                       ["search", "compare"], "success", ["check range figures"])
    hits = mem.recall("EV pricing comparison")
    assert hits[0].task.startswith("research EV pricing")


def test_memory_recall_empty_for_unrelated_query(tmp_path):
    mem = EpisodicMemory(str(tmp_path / "m.jsonl"))
    mem.record_episode("research EV pricing", ["search"], "success", [])
    assert mem.recall("quantum zebras xylophone") == []


def test_memory_distill_extracts_lessons_by_support(tmp_path):
    mem = EpisodicMemory(str(tmp_path / "m.jsonl"))
    mem.record_episode("a", [], "success", ["prefer X", "other"])
    mem.record_episode("b", [], "success", ["prefer X"])
    distilled = mem.distill()
    assert distilled[0] == {"lesson": "prefer X", "support": 2}
    assert distilled[1] == {"lesson": "other", "support": 1}


def test_memory_persists_across_instances_via_jsonl(tmp_path):
    path = str(tmp_path / "m.jsonl")
    mem1 = EpisodicMemory(path)
    mem1.record_episode("research EV pricing", ["search"], "success",
                        ["lesson A"])
    mem2 = EpisodicMemory(path)
    assert len(mem2.episodes) == 1
    assert mem2.recall("EV pricing")[0].lessons == ["lesson A"]
    with open(path, encoding="utf-8") as fh:
        assert len(fh.readlines()) == 1


def test_memory_suggest_returns_lessons_for_similar_goal(tmp_path):
    mem = EpisodicMemory(str(tmp_path / "m.jsonl"))
    mem.record_episode("research EV pricing", ["search"], "success",
                       ["prefer fallback_search over web_search"])
    suggestions = mem.suggest_from_memory("research EV pricing trends")
    assert "prefer fallback_search over web_search" in suggestions


# ---------------------------------------------------------------------------
# End-to-end DeepAgent
# ---------------------------------------------------------------------------

def test_agent_run_succeeds_and_records_episode(tmp_path):
    mem = EpisodicMemory(str(tmp_path / "m.jsonl"))
    agent = DeepAgent(memory=mem)
    trace = agent.run("research EV pricing")
    assert trace.outcome == "success"
    assert len(trace.plan.steps) == 4
    assert all(r.status == SUCCEEDED for r in trace.report.results)
    assert trace.episode is not None
    assert trace.episode.episode_id == 1
    assert trace.episode.outcome == "success"


def test_agent_recovers_from_tool_failure_and_learns(tmp_path):
    registry = make_registry()
    registry.fail_next("web_search", 2)
    agent = DeepAgent(registry=registry,
                      memory=EpisodicMemory(str(tmp_path / "m.jsonl")))
    trace = agent.run("research EV pricing")
    assert trace.outcome == "success"
    strategies = [e["strategy"] for e in trace.plan.replan_log]
    assert SUBSTITUTE_TOOL in strategies
    assert any("prefer fallback_search over web_search" in lesson
               for lesson in trace.episode.lessons)


def test_agent_second_run_uses_memory_suggestion(tmp_path):
    registry = make_registry()
    registry.fail_next("web_search", 2)
    mem = EpisodicMemory(str(tmp_path / "m.jsonl"))
    agent = DeepAgent(registry=registry, memory=mem)
    agent.run("research EV pricing")  # learns the prefer-fallback lesson

    registry2 = make_registry()  # fresh tools, no failures
    agent2 = DeepAgent(registry=registry2, memory=mem)
    trace = agent2.run("research EV pricing trends")
    assert trace.outcome == "success"
    assert trace.memory_hits, "expected memory-guided tool substitution"
    assert any("fallback_search" in hit for hit in trace.memory_hits)
    assert "web_search" not in [s.tool for s in trace.plan.steps]


def test_agent_abort_returns_partial_results_and_failed_episode(tmp_path):
    registry = make_registry()
    registry.fail_next("calculator", 10)
    agent = DeepAgent(registry=registry,
                      memory=EpisodicMemory(str(tmp_path / "m.jsonl")))
    trace = agent.run("calculate 2+2")
    assert trace.outcome == "failed"
    assert len(trace.report.results) == 1
    assert trace.episode.outcome == "failed"
    assert any("aborted" in lesson for lesson in trace.episode.lessons)


def test_agent_trace_carries_full_record():
    agent = DeepAgent()
    trace = agent.run("calculate 6 * 7")
    assert trace.goal == "calculate 6 * 7"
    assert trace.plan.goal == "calculate 6 * 7"
    assert trace.report.plan is trace.plan
    assert "42" in trace.report.results[0].output


def test_calculator_rejects_non_arithmetic():
    registry = make_registry()
    with pytest.raises(ToolError):
        registry.call("calculator", {"expression": "__import__('os').system('x')"})
