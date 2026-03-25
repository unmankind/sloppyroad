"""Chekhov gun detection from story bible entries.

Scans entries tagged as foreshadowing/mystery/promise to identify
emergent narrative promises (Chekhov's guns).
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import ChekhovGun, StoryBibleEntry

logger = structlog.get_logger(__name__)

# Bible entry types that signal potential Chekhov guns
_GUN_ENTRY_TYPES = {"foreshadowing", "mystery", "promise"}


class ChekhovDetector:
    """Scans story bible for emergent Chekhov guns."""

    async def detect_guns(
        self,
        session: AsyncSession,
        novel_id: int,
        bible_entries: list[StoryBibleEntry] | None = None,
    ) -> list[ChekhovGun]:
        """Scan bible entries tagged foreshadowing/mystery/promise for emergent guns.

        If bible_entries is None, queries the database directly.
        """
        if bible_entries is None:
            stmt = (
                select(StoryBibleEntry)
                .where(
                    StoryBibleEntry.novel_id == novel_id,
                    StoryBibleEntry.entry_type.in_(list(_GUN_ENTRY_TYPES)),
                    StoryBibleEntry.is_superseded.is_(False),
                )
            )
            result = await session.execute(stmt)
            bible_entries = list(result.scalars().all())

        # Filter to gun-relevant types
        candidates = [
            e for e in bible_entries
            if e.entry_type in _GUN_ENTRY_TYPES
        ]

        # Check which candidates already have guns
        existing_stmt = (
            select(ChekhovGun.bible_entry_id)
            .where(
                ChekhovGun.novel_id == novel_id,
                ChekhovGun.bible_entry_id.isnot(None),
            )
        )
        existing_result = await session.execute(existing_stmt)
        existing_ids = {row[0] for row in existing_result.fetchall()}

        new_guns: list[ChekhovGun] = []
        for entry in candidates:
            if entry.id in existing_ids:
                continue

            gun = ChekhovGun(
                novel_id=novel_id,
                description=entry.content[:500],
                introduced_at_chapter=entry.source_chapter,
                gun_type=entry.entry_type,
                status="loaded",
                pressure_score=0.0,
                last_touched_chapter=entry.source_chapter,
                bible_entry_id=entry.id,
            )
            session.add(gun)
            new_guns.append(gun)

        if new_guns:
            await session.flush()
            logger.info(
                "chekhov_guns_detected",
                novel_id=novel_id,
                new_guns=len(new_guns),
            )

        return new_guns
