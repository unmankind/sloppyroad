"""Character knowledge tracking for the perspective system.

Tracks what each character knows about the world: which bible entries
they are aware of, how they learned them, and any misconceptions they hold.
"""

from __future__ import annotations

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import CharacterKnowledge, StoryBibleEntry

logger = structlog.get_logger(__name__)


class KnowledgeTracker:
    """Manages character knowledge state against the story bible."""

    async def record_knowledge(
        self,
        session: AsyncSession,
        character_id: int,
        bible_entry_id: int,
        chapter_number: int,
        source: str = "witnessed",
        misconception: str | None = None,
    ) -> CharacterKnowledge:
        """Record that a character learned a fact.

        If the character already has a knowledge record for this entry,
        it is updated rather than duplicated (unique constraint on
        character_id + bible_entry_id).

        Args:
            session: Active async database session.
            character_id: The character who learned the fact.
            bible_entry_id: The bible entry they learned about.
            chapter_number: Chapter in which they learned it.
            source: How they learned it (witnessed/told/deduced/assumed).
            misconception: If they have a wrong understanding, describe it.

        Returns:
            The created or updated CharacterKnowledge record.
        """
        # Check for existing record (unique constraint: character_id + bible_entry_id)
        stmt = select(CharacterKnowledge).where(
            and_(
                CharacterKnowledge.character_id == character_id,
                CharacterKnowledge.bible_entry_id == bible_entry_id,
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            # Update existing record
            existing.learned_at_chapter = chapter_number
            existing.source = source
            existing.misconception = misconception
            existing.knows = True
            await session.flush()

            logger.debug(
                "character_knowledge_updated",
                character_id=character_id,
                bible_entry_id=bible_entry_id,
                chapter=chapter_number,
                source=source,
            )
            return existing

        # Create new record
        knowledge = CharacterKnowledge(
            character_id=character_id,
            bible_entry_id=bible_entry_id,
            knows=True,
            knowledge_level="full",
            misconception=misconception,
            learned_at_chapter=chapter_number,
            source=source,
        )
        session.add(knowledge)
        await session.flush()

        logger.debug(
            "character_knowledge_recorded",
            character_id=character_id,
            bible_entry_id=bible_entry_id,
            chapter=chapter_number,
            source=source,
        )
        return knowledge

    async def get_character_knowledge(
        self,
        session: AsyncSession,
        character_id: int,
        entry_type: str | None = None,
    ) -> list[CharacterKnowledge]:
        """Get all knowledge entries for a character, optionally filtered by entry type.

        Args:
            session: Active async database session.
            character_id: The character to query.
            entry_type: Optional bible entry type filter (e.g. "character_fact").

        Returns:
            List of CharacterKnowledge records.
        """
        stmt = select(CharacterKnowledge).where(
            CharacterKnowledge.character_id == character_id,
        )

        if entry_type is not None:
            # Join with StoryBibleEntry to filter by entry_type
            stmt = (
                select(CharacterKnowledge)
                .join(
                    StoryBibleEntry,
                    CharacterKnowledge.bible_entry_id == StoryBibleEntry.id,
                )
                .where(
                    and_(
                        CharacterKnowledge.character_id == character_id,
                        StoryBibleEntry.entry_type == entry_type,
                    )
                )
            )

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def character_knows(
        self,
        session: AsyncSession,
        character_id: int,
        bible_entry_id: int,
    ) -> bool:
        """Check if a character knows a specific fact.

        Args:
            session: Active async database session.
            character_id: The character to check.
            bible_entry_id: The bible entry to check against.

        Returns:
            True if the character has a knowledge record with knows=True.
        """
        stmt = select(CharacterKnowledge.id).where(
            and_(
                CharacterKnowledge.character_id == character_id,
                CharacterKnowledge.bible_entry_id == bible_entry_id,
                CharacterKnowledge.knows.is_(True),
            )
        ).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None
