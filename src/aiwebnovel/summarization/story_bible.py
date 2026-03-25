"""Story Bible entry extraction and supersession detection.

Takes the bible_entries_to_extract from the narrative analysis and creates
StoryBibleEntry ORM objects. Detects when new entries supersede existing ones
(same entity_ids + same entry_type + newer chapter = supersedes).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import StoryBibleEntry
from aiwebnovel.llm.parsers import BibleEntryExtract

if TYPE_CHECKING:
    from aiwebnovel.llm.provider import LLMProvider

logger = structlog.get_logger(__name__)

# Entry types that are inherently supersedable (facts that change over time)
_SUPERSEDABLE_TYPES = {
    "character_fact",
    "relationship",
    "power_interaction",
    "location_detail",
}


class StoryBibleExtractor:
    """Extracts bible entries from chapter analysis and manages supersession."""

    def __init__(self, llm: LLMProvider | None, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    async def extract_entries(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        chapter_text: str,
        analysis_entries: list[BibleEntryExtract],
    ) -> list[StoryBibleEntry]:
        """Create StoryBibleEntry ORM objects from analysis bible_entries_to_extract.

        Each entry is self-contained (1-3 sentences), tagged with entry_type,
        entity_ids, and importance. Entries are persisted to the DB.

        Args:
            session: Active async database session.
            novel_id: The novel these entries belong to.
            chapter_number: The chapter these entries were extracted from.
            chapter_text: The full chapter text (for reference, not stored).
            analysis_entries: BibleEntryExtract list from NarrativeAnalysisResult.

        Returns:
            List of persisted StoryBibleEntry objects.
        """
        if not analysis_entries:
            return []

        entries: list[StoryBibleEntry] = []

        for extract in analysis_entries:
            entry = StoryBibleEntry(
                novel_id=novel_id,
                entry_type=extract.entry_type,
                content=extract.content,
                source_chapter=chapter_number,
                entity_ids=_resolve_entity_ids(extract),
                tags=extract.entity_types,
                importance=_estimate_importance(extract),
                is_public_knowledge=extract.is_public_knowledge,
                last_relevant_chapter=chapter_number,
                confidence=1.0,
                scope_tier=1,
            )
            session.add(entry)
            entries.append(entry)

        await session.flush()

        logger.info(
            "bible_entries_extracted",
            novel_id=novel_id,
            chapter=chapter_number,
            count=len(entries),
        )
        return entries

    async def detect_supersessions(
        self,
        session: AsyncSession,
        novel_id: int,
        new_entries: list[StoryBibleEntry],
    ) -> list[tuple[StoryBibleEntry, int]]:
        """Detect and mark entries that are superseded by new ones.

        Uses heuristic approach for MVP: same entry_type + overlapping entity_ids
        + newer chapter = supersedes. Old entry gets is_superseded=True and
        superseded_by_id set to the new entry.

        Args:
            session: Active async database session.
            novel_id: The novel to check within.
            new_entries: Newly created StoryBibleEntry objects.

        Returns:
            List of (new_entry, superseded_entry_id) tuples.
        """
        supersession_pairs: list[tuple[StoryBibleEntry, int]] = []

        for new_entry in new_entries:
            # Only check supersedable types
            if new_entry.entry_type not in _SUPERSEDABLE_TYPES:
                continue

            # Need entity_ids to match against
            new_entity_ids = new_entry.entity_ids
            if not new_entity_ids:
                continue

            # Query existing entries with same type and novel, not superseded, not this entry
            stmt = select(StoryBibleEntry).where(
                and_(
                    StoryBibleEntry.novel_id == novel_id,
                    StoryBibleEntry.entry_type == new_entry.entry_type,
                    StoryBibleEntry.is_superseded.is_(False),
                    StoryBibleEntry.id != new_entry.id,
                    StoryBibleEntry.source_chapter < new_entry.source_chapter,
                )
            )
            result = await session.execute(stmt)
            candidates = result.scalars().all()

            for candidate in candidates:
                old_entity_ids = candidate.entity_ids or []
                if not old_entity_ids:
                    continue

                # Check if entity_ids overlap (sets share at least one element)
                new_set = set(new_entity_ids) if isinstance(new_entity_ids, list) else set()
                old_set = set(old_entity_ids) if isinstance(old_entity_ids, list) else set()

                if new_set & old_set:
                    # Mark old entry as superseded
                    candidate.is_superseded = True
                    candidate.superseded_by_id = new_entry.id
                    supersession_pairs.append((new_entry, candidate.id))

                    logger.info(
                        "bible_entry_superseded",
                        novel_id=novel_id,
                        old_entry_id=candidate.id,
                        new_entry_id=new_entry.id,
                        entry_type=new_entry.entry_type,
                    )

        if supersession_pairs:
            await session.flush()

        return supersession_pairs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_entity_ids(extract: BibleEntryExtract) -> list[Any]:
    """Convert entity names to a storable list.

    In the MVP, we store entity_names as-is (strings) in the entity_ids
    JSON column. A future enhancement could resolve names to DB IDs via
    character/location lookup.
    """
    return list(extract.entity_names) if extract.entity_names else []


def _estimate_importance(extract: BibleEntryExtract) -> int:
    """Estimate importance score (1-5) based on entry type.

    Higher importance for types that typically carry more narrative weight.
    """
    type_importance = {
        "character_fact": 3,
        "relationship": 4,
        "world_rule": 4,
        "historical_event": 3,
        "power_interaction": 3,
        "location_detail": 2,
        "foreshadowing": 5,
        "promise": 5,
        "mystery": 5,
        "theme": 3,
    }
    return type_importance.get(extract.entry_type, 3)
