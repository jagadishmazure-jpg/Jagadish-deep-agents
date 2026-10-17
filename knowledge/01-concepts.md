# Deep agents: concepts

## Plan-and-execute (`deepagents/planning.py`, `deepagents/execute.py`)

The agent first decomposes a goal into an **inspectable plan**, then
executes steps against a tool registry. The plan is a first-class
artifact — you can read it, log it, and audit it — which is what
separates deep agents from "loop until done" reflex agents.

Interview line: *"Planning makes the agent's intentions legible before
it acts. Legibility is what lets you put a human or a policy check
between the plan and the irreversible step."*

## Mid-run replanning (`deepagents/replan.py`) — the four strategies

When a step fails, the recovery handler works through a bounded
ladder, in order:

1. **Retry** — same tool, simplified args.
2. **Substitute** — an alternative tool that can do the job.
3. **Skip** — drop the step if non-critical; mark the plan **degraded**.
4. **Abort** — stop with partial results, all of it logged.

A real bug caught in verification: the recovery handler only attempted
*one* replan per failure and gave up. It was rewritten as a proper
recovery loop — bounded, so it can't spin forever; persistent, so a
transient failure doesn't kill the run.

Interview line: *"Replanning is the difference between a demo and a
system. The ladder is ordered by cost — retry is cheap, abort is honest —
and every rung is logged so the failure is debuggable after the fact."*

## Episodic memory (`deepagents/memory.py`)

- Episodes persisted as JSONL — every run leaves a record.
- Keyword recall over past episodes.
- **Lesson distillation** — recurring failure patterns become lessons.
- **Memory-adjusted planning** — the second run of a similar goal avoids
  the first run's mistakes.

This is the long-term memory story: not a vector store bolted on, but
a feedback loop where experience changes future plans. See
`docs/memory-design.md` for the design.

## Module map

| Module | Role |
|---|---|
| `deepagents/planning.py` | task decomposition into inspectable plans |
| `deepagents/execute.py` | step-by-step execution against the tool registry |
| `deepagents/replan.py` | the four-strategy recovery loop |
| `deepagents/memory.py` | JSONL episodes, recall, lesson distillation |
| `deepagents/agent.py` | the assembled agent |
