"""Long-term episodic memory: the agent learns across runs.

Episodes (one per task run: what was tried, what happened, what was
learned) persist to JSONL so memory survives process restarts. Recall is
keyword-overlap scoring — deterministic and inspectable; the production
path swaps this for vector similarity without changing the interface.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    return _WORD.findall(text.lower())


_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "it", "this", "that", "by", "from", "as",
}


def keywords(text: str) -> set:
    return {w for w in tokenize(text) if w not in _STOPWORDS and len(w) > 2}


@dataclass
class Episode:
    task: str
    plan_summary: List[str]          # step descriptions, in order
    outcome: str                    # success | partial | failed
    lessons: List[str] = field(default_factory=list)
    episode_id: int = 0


class EpisodicMemory:
    """Cross-session episode store backed by a JSONL file."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.episodes: List[Episode] = []
        self._load()

    # -- persistence -----------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    self.episodes.append(Episode(**json.loads(line)))

    def _append(self, episode: Episode) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(episode)) + "\n")

    # -- write -----------------------------------------------------------
    def record_episode(self, task: str, plan_summary: List[str],
                       outcome: str, lessons: Optional[List[str]] = None) -> Episode:
        episode = Episode(
            task=task,
            plan_summary=plan_summary,
            outcome=outcome,
            lessons=list(lessons or []),
            episode_id=len(self.episodes) + 1,
        )
        self.episodes.append(episode)
        self._append(episode)
        return episode

    # -- read ------------------------------------------------------------
    def recall(self, query: str, top_k: int = 3) -> List[Episode]:
        """Retrieve past episodes ranked by keyword overlap with the query."""
        query_keys = keywords(query)
        if not query_keys:
            return []
        scored = []
        for ep in self.episodes:
            haystack = keywords(ep.task + " " + " ".join(ep.lessons)
                                + " " + " ".join(ep.plan_summary))
            overlap = query_keys & haystack
            if overlap:
                # Overlap count first, then smaller/earlier episodes tie-break
                # deterministically by episode id.
                scored.append((len(overlap), -ep.episode_id, ep))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [ep for _, _, ep in scored[:top_k]]

    def distill(self) -> List[Dict[str, object]]:
        """Extract durable learnings: lessons seen across episodes.

        Returns dicts {lesson, support} sorted by support desc, then lesson
        text asc — deterministic.
        """
        counts: Dict[str, int] = {}
        for ep in self.episodes:
            for lesson in ep.lessons:
                counts[lesson] = counts.get(lesson, 0) + 1
        return [{"lesson": lesson, "support": support}
                for lesson, support in sorted(counts.items(),
                                             key=lambda kv: (-kv[1], kv[0]))]

    def suggest_from_memory(self, goal: str) -> List[str]:
        """Lessons from relevant past episodes, most relevant first."""
        seen: List[str] = []
        for ep in self.recall(goal, top_k=3):
            for lesson in ep.lessons:
                if lesson not in seen:
                    seen.append(lesson)
        return seen
