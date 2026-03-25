"""Semantic context assembly for chapter generation.

The crown jewel of the Living Story Bible system. Builds semantically
relevant context blocks from vector-indexed bible entries, filtered by
character knowledge, re-ranked by a composite score, and fitted within
a token budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    CharacterKnowledge,
    ChekhovGun,
    ContextRetrievalLog,
)
from aiwebnovel.db.vector import SearchResult, VectorStore

if TYPE_CHECKING:
    from aiwebnovel.llm.provider import LLMProvider

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class SemanticContextEntry:
    """A single entry selected for inclusion in the context block."""

    entry_id: int
    content: str
    entry_type: str
    composite_score: float
    token_estimate: int


@dataclass
class SemanticContext:
    """Assembled semantic context ready for injection into prompts."""

    entries: list[SemanticContextEntry] = field(default_factory=list)
    formatted_text: str = ""
    total_tokens: int = 0
    retrieval_log_id: int | None = None


# ---------------------------------------------------------------------------
# SemanticRetriever
# ---------------------------------------------------------------------------


class SemanticRetriever:
    """Assembles semantically relevant context from the story bible."""

    def __init__(
        self,
        llm: LLMProvider,
        vector_store: VectorStore,
        settings: Settings,
    ) -> None:
        self.llm = llm
        self.vector_store = vector_store
        self.settings = settings

    async def assemble_semantic_context(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_plan: Any,  # ChapterPlan ORM model or duck-typed
        token_budget: int = 3000,
        pov_character_id: int | None = None,
    ) -> SemanticContext:
        """Assemble bible-powered context for chapter generation.

        Pipeline:
        1. Build query string from chapter_plan
        2. Embed query via LLMProvider.embed()
        3. Retrieve top-K candidates from vector store (K=50)
        4. Filter by character knowledge if pov_character_id is set
        5. Re-rank by composite score
        6. Select entries within token budget
        7. Log retrieval to ContextRetrievalLog
        8. Format as context block string
        """
        # 1. Build query
        query_text = self.build_query_from_plan(chapter_plan)

        # 2. Embed
        embeddings = await self.llm.embed(query_text)
        query_embedding = embeddings[0]

        # 3. Retrieve candidates
        candidates = await self.vector_store.search(
            query_embedding,
            top_k=50,
            filters={"novel_id": novel_id},
        )

        if not candidates:
            # Log empty retrieval
            log = ContextRetrievalLog(
                novel_id=novel_id,
                chapter_number=getattr(chapter_plan, "chapter_number", 0),
                query_text=query_text,
                retrieved_entry_ids=[],
                relevance_scores=[],
                total_token_estimate=0,
            )
            session.add(log)
            await session.flush()

            return SemanticContext(
                entries=[],
                formatted_text="",
                total_tokens=0,
                retrieval_log_id=log.id,
            )

        # 4. Filter by character knowledge
        if pov_character_id is not None:
            candidate_ids = [int(c.id) for c in candidates]
            known_ids = await self.get_character_filtered_entries(
                session, pov_character_id, candidate_ids
            )
            # Also include public knowledge entries
            candidates = [
                c for c in candidates
                if int(c.id) in known_ids
                or c.metadata.get("is_public_knowledge", True)
            ]

        # Get current chapter number for recency calculation
        current_chapter = getattr(chapter_plan, "chapter_number", 1)

        # Load chekhov gun pressure scores for foreshadowing entries
        pressure_map = await self._get_pressure_map(session, novel_id)

        # 5. Re-rank by composite score
        scored: list[tuple[SearchResult, float]] = []
        for candidate in candidates:
            chapter_of_entry = candidate.metadata.get("chapter", 1)
            chapters_since = max(0, current_chapter - chapter_of_entry)
            importance = candidate.metadata.get("importance", 3)

            # Narrative pressure from Chekhov guns
            narrative_pressure = 0.0
            entry_type = candidate.metadata.get("entry_type", "")
            if entry_type in ("foreshadowing", "promise", "mystery"):
                entry_id_int = int(candidate.id)
                narrative_pressure = pressure_map.get(entry_id_int, 0.0)

            composite = self._compute_composite_score(
                semantic_similarity=candidate.score,
                chapters_since=chapters_since,
                importance=importance,
                narrative_pressure=narrative_pressure,
            )
            scored.append((candidate, composite))

        scored.sort(key=lambda x: x[1], reverse=True)

        # 6. Select within token budget
        selected_entries: list[SemanticContextEntry] = []
        total_tokens = 0

        for candidate, composite in scored:
            token_est = self.llm.estimate_tokens(candidate.text)
            if total_tokens + token_est > token_budget:
                continue
            selected_entries.append(
                SemanticContextEntry(
                    entry_id=int(candidate.id),
                    content=candidate.text,
                    entry_type=candidate.metadata.get("entry_type", "unknown"),
                    composite_score=composite,
                    token_estimate=token_est,
                )
            )
            total_tokens += token_est

        # 7. Format context block
        formatted = self._format_context_block(selected_entries)

        # 8. Log retrieval
        log = ContextRetrievalLog(
            novel_id=novel_id,
            chapter_number=current_chapter,
            query_text=query_text,
            retrieved_entry_ids=[e.entry_id for e in selected_entries],
            relevance_scores=[round(e.composite_score, 4) for e in selected_entries],
            total_token_estimate=total_tokens,
        )
        session.add(log)
        await session.flush()

        logger.info(
            "semantic_context_assembled",
            novel_id=novel_id,
            chapter=current_chapter,
            candidates=len(candidates),
            selected=len(selected_entries),
            total_tokens=total_tokens,
        )

        return SemanticContext(
            entries=selected_entries,
            formatted_text=formatted,
            total_tokens=total_tokens,
            retrieval_log_id=log.id,
        )

    async def get_character_filtered_entries(
        self,
        session: AsyncSession,
        character_id: int,
        entry_ids: list[int],
    ) -> list[int]:
        """Filter entries by what this character knows. Return IDs they know about."""
        if not entry_ids:
            return []

        stmt = select(CharacterKnowledge.bible_entry_id).where(
            and_(
                CharacterKnowledge.character_id == character_id,
                CharacterKnowledge.bible_entry_id.in_(entry_ids),
                CharacterKnowledge.knows.is_(True),
            )
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

    def build_query_from_plan(self, chapter_plan: Any) -> str:
        """Extract key terms from chapter plan for embedding query.

        Combines title, scene descriptions, target beats, and plot thread
        info into a single query string for embedding.
        """
        parts: list[str] = []

        # Title
        title = getattr(chapter_plan, "title", None)
        if title:
            parts.append(title)

        # Scene outline descriptions
        scene_outline = getattr(chapter_plan, "scene_outline", None)
        if scene_outline:
            for scene in scene_outline:
                if isinstance(scene, dict):
                    desc = scene.get("description", "")
                    if desc:
                        parts.append(desc)
                elif isinstance(scene, str):
                    parts.append(scene)

        # Target beats
        target_beats = getattr(chapter_plan, "target_beats", None)
        if target_beats:
            for beat in target_beats:
                if isinstance(beat, str):
                    parts.append(beat)

        # Plot threads to advance
        threads = getattr(chapter_plan, "plot_threads_advance", None)
        if threads:
            for thread in threads:
                if isinstance(thread, str):
                    parts.append(thread)
                elif isinstance(thread, dict):
                    name = thread.get("name", "")
                    if name:
                        parts.append(name)

        return " ".join(parts) if parts else "general context"

    def _compute_composite_score(
        self,
        semantic_similarity: float,
        chapters_since: int,
        importance: int,
        narrative_pressure: float,
    ) -> float:
        """Calculate composite relevance score.

        Formula:
            0.40 * semantic_similarity
          + 0.25 * recency_boost           (1.0 / (1 + chapters_since))
          + 0.20 * importance_weight        (importance / 5.0)
          + 0.15 * narrative_pressure
        """
        recency_boost = 1.0 / (1.0 + chapters_since)
        importance_weight = importance / 5.0

        return (
            0.40 * semantic_similarity
            + 0.25 * recency_boost
            + 0.20 * importance_weight
            + 0.15 * narrative_pressure
        )

    async def _get_pressure_map(
        self, session: AsyncSession, novel_id: int
    ) -> dict[int, float]:
        """Load Chekhov gun pressure scores keyed by bible_entry_id."""
        stmt = select(
            ChekhovGun.bible_entry_id, ChekhovGun.pressure_score
        ).where(
            and_(
                ChekhovGun.novel_id == novel_id,
                ChekhovGun.bible_entry_id.is_not(None),
                ChekhovGun.status.in_(["loaded", "cocked", "active", "reinforced"]),
            )
        )
        result = await session.execute(stmt)
        return {
            row[0]: min(row[1] / 10.0, 1.0)  # Normalize to 0-1
            for row in result.all()
            if row[0] is not None
        }

    def _format_context_block(
        self, entries: list[SemanticContextEntry]
    ) -> str:
        """Format selected entries into a context block for prompt injection."""
        if not entries:
            return ""

        lines: list[str] = ["=== STORY BIBLE CONTEXT ==="]
        for entry in entries:
            lines.append(f"[{entry.entry_type}] {entry.content}")
        lines.append("=== END STORY BIBLE ===")

        return "\n".join(lines)
