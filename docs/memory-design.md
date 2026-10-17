# Memory design: episodic, semantic, procedural

## The three kinds of agent memory

| Kind | What it stores | Example | This repo |
|---|---|---|---|
| **Episodic** | *What happened* in specific past runs | "On the EV-pricing run, web_search failed twice; fallback_search worked" | ✅ Implemented |
| **Semantic** | *What is true* — facts about the world | "The fallback search index refreshes hourly" | ❌ Out of scope (that's a knowledge base / RAG) |
| **Procedural** | *How to do things* — skills, routines | A reusable "compare two products" workflow | ❌ Out of scope (that's a skill library) |

This repo implements **episodic memory** because it is the kind that
makes plan-and-execute agents improve across runs: the agent remembers
which plans worked, which tools failed, and which recoveries succeeded.

## Design

- **Episode** = one task run: task text, ordered plan summary, outcome
  (`success` / `partial` / `failed`), and lessons learned.
- **Store** = append-only JSONL. Human-readable, diffable, survives
  process restarts, trivially auditable. One line per episode.
- **Recall** = keyword-overlap scoring over task + lessons + plan
  summary. Deterministic and inspectable: you can see exactly *why* an
  episode was retrieved. Ranked by overlap count, ties broken by
  episode id.
- **Distill** = aggregate lessons across episodes into durable
  learnings with support counts ("prefer X" seen in 3 episodes is
  stronger than seen once).
- **Suggest** = lessons from the top recalled episodes, deduped, most
  relevant first. The agent applies `prefer X over Y` lessons by
  rewriting planned steps *before* execution.

## Why not vectors here

Vector similarity is the production answer for recall at scale, but it
trades inspectability for fuzziness: you can't easily say why episode
#412 outranked #87. Keyword overlap is exact, testable, and sufficient
for hundreds of episodes. The `recall()` signature
(`recall(query, top_k) -> List[Episode]`) is deliberately
interface-compatible with a vector-backed drop-in.

## Production path

1. Embed episode text (task + lessons) with a sentence-embedding model;
   store vectors in pgvector / Qdrant / Azure AI Search.
2. Hybrid recall: vector similarity for candidates, keyword overlap as
   a re-ranker (keeps the inspectability).
3. Episode retention policy: cap store size, keep high-support lessons,
   archive raw episodes to cold storage.
4. Lesson promotion: `distill()` output with support above a threshold
   becomes a standing planning rule, reviewed by a human before
   promotion (memory, like code, can learn the wrong lesson).
