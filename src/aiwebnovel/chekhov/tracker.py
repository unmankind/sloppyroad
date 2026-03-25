"""Chekhov gun pressure tracking.

Maintains pressure scores for narrative promises: guns that haven't been
touched recently accumulate pressure, signaling they need attention.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.queries import get_active_chekhov_guns

logger = structlog.get_logger(__name__)


class ChekhovTracker:
    """Tracks pressure on Chekhov guns."""

    async def update_pressure(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
    ) -> None:
        """Increase pressure on untouched guns.

        Score: min(1.0, chapters_since_touch / expected_payoff_window).
        Default expected_payoff_window = 10 chapters.
        """
        guns = await get_active_chekhov_guns(session, novel_id)

        for gun in guns:
            if gun.last_touched_chapter is not None:
                chapters_since = chapter_number - gun.last_touched_chapter
            else:
                chapters_since = chapter_number - gun.introduced_at_chapter

            gun.chapters_since_touch = chapters_since

            # Expected payoff window
            expected_window = 10
            if gun.expected_resolution_chapter:
                expected_window = max(
                    1, gun.expected_resolution_chapter - gun.introduced_at_chapter,
                )

            gun.pressure_score = min(1.0, chapters_since / expected_window)

        await session.flush()

        logger.info(
            "chekhov_pressure_updated",
            novel_id=novel_id,
            chapter_number=chapter_number,
            guns_updated=len(guns),
        )

    async def process_interactions(
        self,
        session: AsyncSession,
        novel_id: int,
        interactions: list[dict[str, Any]],
    ) -> None:
        """Update gun statuses from analysis interactions.

        Each interaction dict has: gun_description, interaction_type, details.
        """
        guns = await get_active_chekhov_guns(session, novel_id)
        gun_map = {g.description[:50].lower(): g for g in guns}

        for interaction in interactions:
            desc = interaction.get("gun_description", "")[:50].lower()
            itype = interaction.get("interaction_type", "")

            # Find matching gun by prefix
            matched_gun = None
            for key, gun in gun_map.items():
                if key.startswith(desc[:30]) or desc.startswith(key[:30]):
                    matched_gun = gun
                    break

            if matched_gun is None:
                continue

            if itype == "touched":
                matched_gun.chapters_since_touch = 0
                matched_gun.pressure_score = max(0.0, matched_gun.pressure_score - 0.1)
            elif itype == "advanced":
                matched_gun.status = "cocked"
                matched_gun.chapters_since_touch = 0
                matched_gun.pressure_score = max(0.0, matched_gun.pressure_score - 0.2)
            elif itype == "resolved":
                matched_gun.status = "resolved"
                matched_gun.resolution_description = interaction.get("details", "")
            elif itype == "subverted":
                matched_gun.status = "subverted"
                matched_gun.subversion_description = interaction.get("details", "")

        await session.flush()

        logger.info(
            "chekhov_interactions_processed",
            novel_id=novel_id,
            interaction_count=len(interactions),
        )
