"""Database extraction from post-chapter analysis results.

Writes analysis results to the database: character states, abilities,
regions, foreshadowing seeds, tension entries, story bible entries,
Chekhov gun updates, and advancement events.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    AdvancementEvent,
    Character,
    ChekhovGun,
    ForeshadowingSeed,
    StoryBibleEntry,
    TensionTracker,
)
from aiwebnovel.story.analyzer import AnalysisResult

logger = structlog.get_logger(__name__)


class DataExtractor:
    """Writes analysis results to the database."""

    async def extract_from_analysis(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        analysis: AnalysisResult,
    ) -> list[int]:
        """Write all analysis results to DB.

        Returns list of new StoryBibleEntry IDs for embedding.
        """
        bible_entry_ids: list[int] = []

        if analysis.narrative_success and analysis.narrative:
            ids = await self._extract_narrative(
                session, novel_id, chapter_number, analysis.narrative,
            )
            bible_entry_ids.extend(ids)

        if analysis.system_success and analysis.system:
            await self._extract_system(
                session, novel_id, chapter_number, analysis.system,
            )

        await session.flush()

        logger.info(
            "data_extraction_complete",
            novel_id=novel_id,
            chapter_number=chapter_number,
            bible_entries=len(bible_entry_ids),
        )

        return bible_entry_ids

    async def _extract_narrative(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        narrative: object,
    ) -> list[int]:
        """Extract narrative analysis data to DB.

        Returns list of new StoryBibleEntry IDs.
        """
        from aiwebnovel.llm.parsers import NarrativeAnalysisResult

        if not isinstance(narrative, NarrativeAnalysisResult):
            return []

        # Tension tracker entry
        tension = TensionTracker(
            novel_id=novel_id,
            chapter_number=chapter_number,
            tension_level=narrative.tension_level,
            tension_phase=narrative.tension_phase,
            key_tension_drivers=[
                e.description for e in narrative.key_events
                if e.narrative_importance in ("major", "pivotal")
            ],
        )
        session.add(tension)

        # New foreshadowing seeds
        for seed in narrative.new_foreshadowing_seeds:
            fs = ForeshadowingSeed(
                novel_id=novel_id,
                description=seed.description,
                planted_at_chapter=chapter_number,
                seed_type=seed.seed_type,
                status="planted",
                scope_tier=seed.target_scope_tier,
            )
            session.add(fs)

        # Update existing foreshadowing seeds based on references
        for ref in narrative.foreshadowing_references:
            stmt = (
                select(ForeshadowingSeed)
                .where(
                    ForeshadowingSeed.novel_id == novel_id,
                    ForeshadowingSeed.description.ilike(
                        f"%{ref.existing_seed_description[:50]}%"
                    ),
                )
                .limit(1)
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                if ref.reference_type == "fully_paid_off":
                    existing.status = "fulfilled"
                    existing.fulfilled_at_chapter = chapter_number
                elif ref.reference_type == "reinforced":
                    existing.status = "reinforced"
                elif ref.reference_type == "partially_paid_off":
                    existing.status = "reinforced"

        # Story bible entries
        bible_entries: list[StoryBibleEntry] = []
        for entry in narrative.bible_entries_to_extract:
            bible = StoryBibleEntry(
                novel_id=novel_id,
                entry_type=entry.entry_type,
                content=entry.content,
                source_chapter=chapter_number,
                tags=entry.entity_types,
                is_public_knowledge=entry.is_public_knowledge,
            )
            session.add(bible)
            bible_entries.append(bible)

        # Flush to assign IDs before returning
        await session.flush()
        return [b.id for b in bible_entries]

    async def _extract_system(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        system: object,
    ) -> None:
        """Extract system analysis data to DB."""
        from aiwebnovel.llm.parsers import SystemAnalysisResult

        if not isinstance(system, SystemAnalysisResult):
            return

        # Advancement events
        for pe in system.power_events:
            if pe.event_type in ("rank_up", "new_ability"):
                # Find character
                char_stmt = (
                    select(Character)
                    .where(
                        Character.novel_id == novel_id,
                        Character.name == pe.character_name,
                    )
                    .limit(1)
                )
                char_result = await session.execute(char_stmt)
                character = char_result.scalar_one_or_none()

                if character:
                    # Find earned power score from evaluations
                    ep_score = None
                    for ep in system.earned_power_evaluations:
                        if ep.character_name == pe.character_name:
                            ep_score = ep.total_score
                            break

                    event = AdvancementEvent(
                        character_id=character.id,
                        chapter_number=chapter_number,
                        event_type=pe.event_type,
                        description=pe.description,
                        struggle_context=pe.struggle_context,
                        sacrifice_or_cost=pe.sacrifice_or_cost,
                        foundation=pe.foundation,
                        narrative_buildup_chapters=pe.narrative_buildup_chapters,
                        earned_power_score=ep_score,
                    )
                    session.add(event)

        # Chekhov gun interactions
        for interaction in system.chekhov_interactions:
            if interaction.interaction_type == "new_gun":
                gun = ChekhovGun(
                    novel_id=novel_id,
                    description=interaction.gun_description,
                    introduced_at_chapter=chapter_number,
                    gun_type="emergent",
                    status="loaded",
                    pressure_score=0.0,
                    last_touched_chapter=chapter_number,
                )
                session.add(gun)
            else:
                # Find existing gun
                gun_stmt = (
                    select(ChekhovGun)
                    .where(
                        ChekhovGun.novel_id == novel_id,
                        ChekhovGun.description.ilike(
                            f"%{interaction.gun_description[:50]}%"
                        ),
                    )
                    .limit(1)
                )
                gun_result = await session.execute(gun_stmt)
                gun = gun_result.scalar_one_or_none()

                if gun:
                    gun.last_touched_chapter = chapter_number
                    gun.chapters_since_touch = 0

                    if interaction.interaction_type == "resolved":
                        gun.status = "resolved"
                        gun.resolution_chapter = chapter_number
                        gun.resolution_description = interaction.resolution_description
                    elif interaction.interaction_type == "subverted":
                        gun.status = "subverted"
                        gun.resolution_chapter = chapter_number
                        gun.subversion_description = interaction.subversion_description
                    elif interaction.interaction_type == "advanced":
                        gun.status = "cocked"
                    elif interaction.interaction_type == "touched":
                        gun.pressure_score = max(0.0, gun.pressure_score - 0.1)
