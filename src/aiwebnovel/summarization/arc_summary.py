"""Arc summarization: meta-summary of completed story arcs."""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import ArcPlan, Chapter, ChapterSummary
from aiwebnovel.llm.parsers import ArcSummaryResult
from aiwebnovel.llm.prompts import ARC_SUMMARY
from aiwebnovel.llm.provider import LLMProvider

logger = structlog.get_logger(__name__)


class ArcSummarizer:
    """Generates meta-summaries of completed story arcs."""

    def __init__(self, llm: LLMProvider, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    async def generate_arc_summary(
        self,
        session: AsyncSession,
        arc_id: int,
        user_id: int,
    ) -> str:
        """Generate arc-level summary from chapter summaries."""
        # Load arc
        arc_stmt = select(ArcPlan).where(ArcPlan.id == arc_id)
        arc_result = await session.execute(arc_stmt)
        arc = arc_result.scalar_one()

        # Load chapters in this arc
        ch_stmt = (
            select(Chapter)
            .where(Chapter.arc_plan_id == arc_id)
            .order_by(Chapter.chapter_number.asc())
        )
        ch_result = await session.execute(ch_stmt)
        chapters = ch_result.scalars().all()

        # Get summaries for each chapter
        summary_parts: list[str] = []
        for ch in chapters:
            sum_stmt = (
                select(ChapterSummary)
                .where(
                    ChapterSummary.chapter_id == ch.id,
                    ChapterSummary.summary_type == "standard",
                )
            )
            sum_result = await session.execute(sum_stmt)
            summary = sum_result.scalar_one_or_none()
            if summary:
                summary_parts.append(
                    f"Chapter {ch.chapter_number}: {summary.content}"
                )

        arc_plan_text = f"Title: {arc.title}\nDescription: {arc.description}"

        system, user = ARC_SUMMARY.render(
            arc_title=arc.title,
            arc_plan=arc_plan_text,
            chapter_summaries="\n\n".join(summary_parts) or "No summaries available",
        )

        response = await self.llm.generate(
            system=system,
            user=user,
            temperature=ARC_SUMMARY.temperature,
            max_tokens=ARC_SUMMARY.max_tokens,
            response_format=ArcSummaryResult,
            novel_id=arc.novel_id,
            user_id=user_id,
            purpose="arc_summary",
        )

        parsed = ArcSummaryResult.model_validate_json(response.content)

        logger.info(
            "arc_summary_generated",
            arc_id=arc_id,
            themes=len(parsed.key_themes),
        )

        return parsed.arc_summary
