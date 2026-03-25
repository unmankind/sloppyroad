"""Chapter summarization: standard and enhanced recap.

Produces compressed chapter representations for context assembly.
Enhanced recap (~1200 tokens) replaces full chapter text in context window.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import ChapterSummary
from aiwebnovel.llm.parsers import ChapterSummaryResult, EnhancedRecapResult
from aiwebnovel.llm.prompts import ENHANCED_RECAP, STANDARD_SUMMARY
from aiwebnovel.llm.provider import LLMProvider

logger = structlog.get_logger(__name__)


class ChapterSummarizer:
    """Generates chapter summaries of various types."""

    def __init__(self, llm: LLMProvider, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    async def generate_standard_summary(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_id: int,
        chapter_text: str,
        user_id: int,
        chapter_number: int = 1,
    ) -> ChapterSummary:
        """Generate a ~300 token standard summary."""
        system, user = STANDARD_SUMMARY.render(
            chapter_number=str(chapter_number),
            chapter_text=chapter_text,
        )

        response = await self.llm.generate(
            system=system,
            user=user,
            temperature=STANDARD_SUMMARY.temperature,
            max_tokens=STANDARD_SUMMARY.max_tokens,
            response_format=ChapterSummaryResult,
            novel_id=novel_id,
            user_id=user_id,
            purpose="standard_summary",
        )

        parsed = ChapterSummaryResult.model_validate_json(response.content)

        summary = ChapterSummary(
            chapter_id=chapter_id,
            summary_type="standard",
            content=parsed.summary,
            key_events=parsed.key_events,
            emotional_arc=parsed.emotional_arc,
            cliffhangers=parsed.cliffhangers,
            model_used=response.model,
        )
        session.add(summary)
        await session.flush()

        logger.info(
            "standard_summary_generated",
            chapter_id=chapter_id,
            tokens=self.llm.estimate_tokens(parsed.summary),
        )

        return summary

    async def generate_enhanced_recap(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_id: int,
        chapter_text: str,
        user_id: int,
        chapter_number: int = 1,
        pov_character_name: str = "Protagonist",
        scene_character_names: str = "",
    ) -> ChapterSummary:
        """Generate ~1200 token enhanced recap for next-chapter context.

        Contains: final scene snapshot, emotional states, dialogue threads,
        cliffhanger, pending actions, arc beat.
        """
        system, user = ENHANCED_RECAP.render(
            chapter_number=str(chapter_number),
            chapter_text=chapter_text,
            pov_character_name=pov_character_name,
            scene_character_names=scene_character_names,
        )

        response = await self.llm.generate(
            system=system,
            user=user,
            temperature=ENHANCED_RECAP.temperature,
            max_tokens=ENHANCED_RECAP.max_tokens,
            response_format=EnhancedRecapResult,
            novel_id=novel_id,
            user_id=user_id,
            purpose="enhanced_recap",
        )

        parsed = EnhancedRecapResult.model_validate_json(response.content)

        # Build a text representation
        content_parts = [
            f"Final Scene: {parsed.final_scene_snapshot}",
        ]
        for es in parsed.emotional_state:
            content_parts.append(f"Emotional: {es.character} - {es.state}")
        if parsed.active_dialogue_threads.last_exchange:
            content_parts.append(
                f"Dialogue: {parsed.active_dialogue_threads.last_exchange}"
            )
        if parsed.cliffhanger:
            content_parts.append(f"Cliffhanger: {parsed.cliffhanger.description}")
        for pa in parsed.immediate_pending_actions:
            content_parts.append(f"Pending: {pa.character} - {pa.action}")
        content_parts.append(
            f"Arc Beat: {parsed.chapter_arc_beat.what_was_accomplished}"
        )

        content = "\n".join(content_parts)

        summary = ChapterSummary(
            chapter_id=chapter_id,
            summary_type="enhanced_recap",
            content=content,
            model_used=response.model,
        )
        session.add(summary)
        await session.flush()

        logger.info(
            "enhanced_recap_generated",
            chapter_id=chapter_id,
            tokens=self.llm.estimate_tokens(content),
        )

        return summary
