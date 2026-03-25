"""Relevance scoring for context assembly.

Composite score: 0.40*semantic + 0.25*recency + 0.20*importance + 0.15*pressure.
Used to prioritize which story bible entries and context pieces make it
into the token-budgeted generation prompt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RelevanceInput:
    """Input data for relevance scoring."""

    semantic_similarity: float = 0.0  # 0.0 - 1.0
    source_chapter: int = 0
    importance: int = 3  # 1-5
    pressure_score: float = 0.0  # 0.0 - 1.0


class RelevanceScorer:
    """Scores context entries for relevance to current chapter."""

    # Weight coefficients
    W_SEMANTIC: float = 0.40
    W_RECENCY: float = 0.25
    W_IMPORTANCE: float = 0.20
    W_PRESSURE: float = 0.15

    def score(
        self,
        entry: RelevanceInput,
        chapter_plan: Any | None = None,
        current_chapter: int = 1,
    ) -> float:
        """Composite relevance score: 0.0 - 1.0.

        Formula: 0.40*semantic + 0.25*recency + 0.20*importance + 0.15*pressure
        """
        # Semantic similarity (0.0 - 1.0)
        semantic = max(0.0, min(1.0, entry.semantic_similarity))

        # Recency: exponential decay, more recent = higher score
        chapters_ago = max(0, current_chapter - entry.source_chapter)
        recency = math.exp(-0.1 * chapters_ago)

        # Importance: normalize 1-5 to 0.0-1.0
        importance = max(0.0, min(1.0, (entry.importance - 1) / 4.0))

        # Pressure score (0.0 - 1.0)
        pressure = max(0.0, min(1.0, entry.pressure_score))

        total = (
            self.W_SEMANTIC * semantic
            + self.W_RECENCY * recency
            + self.W_IMPORTANCE * importance
            + self.W_PRESSURE * pressure
        )

        return round(total, 4)

    def rank_entries(
        self,
        entries: list[RelevanceInput],
        chapter_plan: Any | None = None,
        current_chapter: int = 1,
    ) -> list[tuple[RelevanceInput, float]]:
        """Score and rank entries by relevance, highest first."""
        scored = [
            (entry, self.score(entry, chapter_plan, current_chapter))
            for entry in entries
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
