"""Chekhov gun directive injection into chapter prompts.

When guns reach high pressure, generates directives for the chapter
generation prompt to address them.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.queries import get_active_chekhov_guns

logger = structlog.get_logger(__name__)

# Pressure threshold for generating directives
_HIGH_PRESSURE_THRESHOLD = 0.7
_CRITICAL_PRESSURE_THRESHOLD = 0.9


class ChekhovInjector:
    """Generates directives for high-pressure Chekhov guns."""

    async def get_directives(
        self,
        session: AsyncSession,
        novel_id: int,
    ) -> list[str]:
        """Generate directives for high-pressure guns to inject into chapter prompt."""
        guns = await get_active_chekhov_guns(session, novel_id)

        directives: list[str] = []
        for gun in guns:
            if gun.pressure_score >= _CRITICAL_PRESSURE_THRESHOLD:
                directives.append(
                    f"CRITICAL: The narrative promise '{gun.description[:100]}' "
                    f"has been building for {gun.chapters_since_touch} chapters. "
                    f"It MUST begin its resolution in this chapter."
                )
            elif gun.pressure_score >= _HIGH_PRESSURE_THRESHOLD:
                directives.append(
                    f"HIGH PRESSURE: The narrative promise '{gun.description[:100]}' "
                    f"(introduced {gun.chapters_since_touch} chapters ago) needs "
                    f"attention. At minimum, touch or advance it in this chapter."
                )

        if directives:
            logger.info(
                "chekhov_directives_generated",
                novel_id=novel_id,
                directive_count=len(directives),
            )

        return directives
