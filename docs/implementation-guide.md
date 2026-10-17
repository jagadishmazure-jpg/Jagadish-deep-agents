# Implementation guide: from offline build to Azure

> Status: **planned**. Nothing here has been deployed. The offline build in this
> repository is what exists today; this guide is how it would be taken to a
> real Azure environment.

## Azure service mapping

| Offline component | Azure service (planned) | Notes |
|---|---|---|
| Planner | Azure OpenAI with structured output for the Plan schema | Validate before executing |
| Tools | MCP servers or Azure Functions behind `ToolRegistry.call` |  |
| Episodic memory | Cosmos DB with vector search over episodes | Add expiry |
| Traces | Application Insights / OpenTelemetry spans per step and replan |  |

## Steps

1. Replace the fake registry with real tools; keep the `call(name, args)` contract.
2. Have an LLM produce the Plan as JSON and validate it against the schema before running.
3. Move memory to a vector store and add lesson expiry and confidence.
4. Add a human approval step before abort on high-stakes goals.

## Guardrails to keep when going live

- The plan exists as data before any tool runs, so it can be inspected or approved.
- Replanning is bounded by a budget; no unbounded retry loops.
- Skipping a step marks the plan degraded instead of hiding it.
- Every recovery decision is logged with its reason.

## What to measure before calling it production-ready

- Task success rate with injected tool failures.
- Replans per run before and after memory.
- Share of runs that end degraded or aborted.
