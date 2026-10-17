# Jagadish-deep-agents

Deep agent patterns: **plan-and-execute with mid-run replanning** and
**long-term episodic memory**. A study of the two capabilities that
separate brittle linear agents from agents that recover and learn.

## The problem

Most agent loops are linear: prompt → act → act → answer. The first
tool error kills the run, and nothing learned in one run carries over
to the next. In production that means:

- a transient search outage fails an entire research task instead of
  triggering a retry or a fallback source, and
- every run re-discovers the same workarounds (which source is
  reliable, which query shapes work) from scratch.

This repo implements the two classic answers, deterministically:

1. **Plan-and-execute with replanning.** The goal is decomposed into an
   inspectable plan *before* any tool runs. When a step fails, a
   replanner recovers mid-run: retry with simplified args → substitute
   an alternative tool → skip a non-critical step (plan marked
   degraded) → abort with partial results. Bounded by a replan budget.
2. **Episodic memory.** Each run records an episode (task, plan,
   outcome, lessons) to a JSONL store. Future runs recall relevant
   episodes by keyword overlap and apply their lessons — e.g. prefer
   the fallback search tool after learning the primary one is flaky.

## Architecture

```
goal
 │
 ▼
┌──────────────┐   suggest_from_memory()   ┌─────────────────┐
│  DeepAgent   │ ─────────────────────────▶│ EpisodicMemory  │
└──────┬───────┘   "prefer X over Y"        │ record/recall/  │
       │           lessons adjust plan      │ distill → JSONL │
       ▼                                    └─────────────────┘
┌──────────────┐  decompose() — rule-based, inspectable
│     Plan     │  steps: id, description, tool, args, status
└──────┬───────┘
       ▼
┌──────────────┐   per-step results, $sN.output refs
│ PlanExecutor │ ──▶ ToolRegistry (fake tools, failure injection)
└──────┬───────┘
       │ on failure
       ▼
┌──────────────┐  retry_modified → substitute_tool
│   replan()   │  → skip (degraded) → abort (partial)
└──────────────┘  every decision logged with a reason
```

## Example trace

Goal: `research EV pricing`, with the primary search tool injected to
fail twice:

```
plan:  s1 web_search("EV pricing") → s2 summarizer($s1) →
       s3 web_search("EV pricing alternatives") → s4 summarizer($s3)

s1 attempt 1: web_search failed (injected failure)
replan #1: retry_modified — "retrying web_search with simplified args"
s1 attempt 2: web_search failed (injected failure)
replan #2: substitute_tool — "substituting fallback_search"
s1 attempt 3: fallback_search → "Cached results for 'EV pricing'…" ✓
s2, s3, s4 succeed → outcome: success (plan degraded)

episode recorded: "prefer fallback_search over web_search for
'research EV pricing'"

second run, "research EV pricing trends":
memory hit → plan built with fallback_search from the start
```

## Quickstart

```bash
pip install -e .
python -m pytest  # 27 tests
```

```python
from deepagents import DeepAgent, EpisodicMemory

agent = DeepAgent(memory=EpisodicMemory("memory.jsonl"))
trace = agent.run("research EV pricing")
print(trace.outcome)            # success | partial | failed
print(trace.memory_hits)        # lessons applied from past runs
print(trace.plan.replan_log)    # every mid-run recovery decision
```

## Project layout

| Path | What |
|---|---|
| `deepagents/planning.py` | `Plan`/`Step` data model; rule-based `decompose()` |
| `deepagents/execute.py` | `PlanExecutor`, `ToolRegistry`, deterministic fake tools |
| `deepagents/replan.py` | Mid-run recovery strategies, bounded replan budget |
| `deepagents/memory.py` | `EpisodicMemory`: JSONL episodes, recall, distill |
| `deepagents/agent.py` | `DeepAgent`: memory → plan → execute → record |
| `docs/memory-design.md` | Episodic vs semantic vs procedural memory |

## Production path

- **Tools:** swap the fake registry for real tools via MCP servers;
  the `ToolRegistry.call(name, args)` contract is unchanged.
- **Memory:** replace keyword-overlap `recall()` with vector
  similarity over episode embeddings (interface-compatible).
- **Planner:** replace rule templates with an LLM decomposer; keep
  plans as inspectable data — never execute an uninspectable plan.
- **Replanning:** add cost/latency-aware strategy choice and
  human-in-the-loop before `abort` on high-stakes goals.

> Synthetic demo data only. No network calls, no API keys.

## Knowledge

Distilled notes and architecture diagrams: [knowledge/](knowledge/README.md)
