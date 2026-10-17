"""Deterministic, rule-based task decomposition.

Plans are plain data: ordered steps with ids, descriptions, tool names and
args. A plan can be inspected, serialized and reasoned about before a
single tool runs — that inspectability is the whole point of
plan-and-execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

# Step lifecycle states
PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class Step:
    """One executable unit of a plan."""

    id: str
    description: str
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    status: str = PENDING
    critical: bool = True  # non-critical steps may be skipped on failure


@dataclass
class Plan:
    """An ordered, inspectable decomposition of a goal."""

    goal: str
    steps: List[Step] = field(default_factory=list)
    degraded: bool = False  # True once a step was skipped or substituted
    replans_used: int = 0
    replan_log: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rule-based decomposition
# ---------------------------------------------------------------------------

_LEAD_VERBS = {
    "research", "investigate", "compare", "summarize", "calculate",
    "compute", "analyze", "analyse", "find", "look", "please",
}

# Each template: keywords that trigger it and the step skeletons it emits.
# "$subject" is replaced with the extracted subject; "$sN.output" in args is
# resolved by the executor to a prior step's output.
_TEMPLATES: List[Dict[str, Any]] = [
    {
        "name": "research_compare",
        "keywords": {"research", "compare", "pricing", "prices", "price",
                     "versus", "vs", "investigate", "evaluate"},
        "steps": [
            ("web_search", "Search the web for {subject}",
             {"query": "{subject}"}, True),
            ("summarizer", "Distill key facts about {subject}",
             {"text": "$s1.output", "focus": "key facts"}, True),
            ("web_search", "Search for alternatives to {subject}",
             {"query": "{subject} alternatives"}, False),
            ("summarizer", "Compare and recommend on {subject}",
             {"text": "$s3.output", "focus": "comparison and recommendation"}, True),
        ],
    },
    {
        "name": "calculate",
        "keywords": {"calculate", "compute", "math", "total", "sum", "average"},
        "steps": [
            ("calculator", "Compute {subject}",
             {"expression": "{subject}"}, True),
            ("summarizer", "Explain the result of {subject}",
             {"text": "$s1.output", "focus": "plain-language explanation"}, True),
        ],
    },
    {
        "name": "summarize",
        "keywords": {"summarize", "summary", "tldr", "brief"},
        "steps": [
            ("web_search", "Gather material on {subject}",
             {"query": "{subject}"}, True),
            ("summarizer", "Summarize {subject}",
             {"text": "$s1.output", "focus": "concise summary"}, True),
        ],
    },
]

_GENERIC_TEMPLATE = {
    "name": "generic",
    "steps": [
        ("web_search", "Gather information about {subject}",
         {"query": "{subject}"}, True),
        ("summarizer", "Summarize findings on {subject}",
         {"text": "$s1.output", "focus": "summary"}, True),
    ],
}


def extract_subject(goal: str) -> str:
    """Strip leading verb filler to find what the goal is about."""
    tokens = goal.strip().split()
    while tokens and tokens[0].lower().strip(".,!?") in _LEAD_VERBS:
        tokens.pop(0)
    subject = " ".join(tokens).strip()
    return subject or goal.strip()


def _score_template(goal_tokens: Set[str], template: Dict[str, Any]) -> int:
    return len(goal_tokens & template["keywords"])


def decompose(goal: str, available_tools: Set[str] | List[str]) -> Plan:
    """Break a goal into an ordered, inspectable Plan.

    Picks the keyword template with the most hits; falls back to a generic
    two-step plan. Steps whose tool is not registered are dropped and
    ``$sN.output`` references are remapped to the surviving step ids.
    """
    available = set(available_tools)
    tokens = {t.lower().strip(".,!?") for t in goal.split()}
    subject = extract_subject(goal)

    best = max(_TEMPLATES, key=lambda t: _score_template(tokens, t))
    candidates = [best, _GENERIC_TEMPLATE] if _score_template(tokens, best) else [_GENERIC_TEMPLATE]

    for template in candidates:
        raw_steps = []
        for pos, (tool, desc, args, critical) in enumerate(template["steps"], start=1):
            if tool not in available:
                continue
            step_id = f"s{pos}"  # template position; remapped below if steps dropped
            raw_steps.append((pos, Step(
                id=step_id,
                description=desc.replace("{subject}", subject),
                tool=tool,
                args={k: (v.replace("{subject}", subject) if isinstance(v, str) else v)
                      for k, v in args.items()},
                critical=critical,
            )))
        if not raw_steps:
            continue
        # Remap ids to 1..N over surviving steps and fix $sN.output refs.
        # A ref to a dropped step is rewired to the nearest surviving step
        # before it; a ref with no surviving predecessor is left dangling
        # and the executor will fail the step with a clear error.
        surviving_positions = sorted(pos for pos, _ in raw_steps)
        old_to_new = {pos: f"s{i}" for i, pos in enumerate(surviving_positions, start=1)}

        def rewire(old_ref: str, current_pos: int) -> str:
            if old_ref in old_to_new:
                return old_to_new[old_ref]
            earlier = [p for p in surviving_positions if p < current_pos]
            if earlier:
                return old_to_new[max(earlier)]
            return old_ref  # dangling; executor reports it

        steps: List[Step] = []
        for pos, step in raw_steps:
            step.id = old_to_new[pos]
            fixed_args = {}
            for k, v in step.args.items():
                if isinstance(v, str) and v.startswith("$s") and v.endswith(".output"):
                    old_ref = v[1:].split(".")[0]
                    v = f"${rewire(old_ref, pos)}.output"
                fixed_args[k] = v
            step.args = fixed_args
            steps.append(step)
        return Plan(goal=goal, steps=steps)

    return Plan(goal=goal, steps=[])
