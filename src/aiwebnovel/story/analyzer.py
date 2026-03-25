"""Consolidated post-chapter analysis.

Runs narrative and system analysis concurrently via asyncio.gather().
Two LLM calls instead of four, ~40% cost savings.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings

if TYPE_CHECKING:
    from aiwebnovel.story.gen_context import GenerationContext
from aiwebnovel.db.models import (
    ChapterPlan,
)
from aiwebnovel.db.queries import (
    get_active_chekhov_guns,
    get_active_foreshadowing,
    get_chapter_context,
    get_escalation_state,
)
from aiwebnovel.llm.parsers import NarrativeAnalysisResult, SystemAnalysisResult
from aiwebnovel.llm.prompts import NARRATIVE_ANALYSIS, SYSTEM_ANALYSIS
from aiwebnovel.llm.provider import LLMProvider

logger = structlog.get_logger(__name__)


@dataclass
class AnalysisResult:
    """Bundles narrative and system analysis results."""

    narrative: NarrativeAnalysisResult | None = None
    system: SystemAnalysisResult | None = None
    narrative_success: bool = False
    system_success: bool = False
    narrative_error: str | None = None
    system_error: str | None = None

    @property
    def success(self) -> bool:
        """True if both analyses succeeded."""
        return self.narrative_success and self.system_success

    @property
    def partial(self) -> bool:
        """True if at least one analysis succeeded."""
        return self.narrative_success or self.system_success


class ChapterAnalyzer:
    """Runs consolidated post-chapter analysis."""

    def __init__(self, llm: LLMProvider, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    async def analyze(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        chapter_text: str,
        user_id: int = 0,
        gen_ctx: GenerationContext | None = None,
    ) -> AnalysisResult:
        """Run narrative + system analysis concurrently.

        Fallback: if parsing fails after 1 retry, return partial results
        with error flags.
        """
        result = AnalysisResult()

        # Build context for both analyses
        narrative_ctx = await self._build_narrative_context(
            session, novel_id, chapter_number, chapter_text,
        )
        system_ctx = await self._build_system_context(
            session, novel_id, chapter_number, chapter_text,
        )

        # Run both analyses concurrently
        narrative_task = self._run_narrative_analysis(
            narrative_ctx, novel_id, user_id, gen_ctx=gen_ctx,
        )
        system_task = self._run_system_analysis(
            system_ctx, novel_id, user_id, gen_ctx=gen_ctx,
        )

        narrative_result, system_result = await asyncio.gather(
            narrative_task, system_task, return_exceptions=True,
        )

        # Process narrative result
        if isinstance(narrative_result, Exception):
            result.narrative_error = str(narrative_result)
            logger.warning("narrative_analysis_failed", error=str(narrative_result))
        else:
            result.narrative = narrative_result
            result.narrative_success = True

        # Process system result
        if isinstance(system_result, Exception):
            result.system_error = str(system_result)
            logger.warning("system_analysis_failed", error=str(system_result))
        else:
            result.system = system_result
            result.system_success = True

        logger.info(
            "chapter_analysis_complete",
            novel_id=novel_id,
            chapter_number=chapter_number,
            narrative_ok=result.narrative_success,
            system_ok=result.system_success,
        )

        return result

    async def _build_narrative_context(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        chapter_text: str,
    ) -> dict[str, str]:
        """Build context dict for narrative analysis prompt."""
        escalation = await get_escalation_state(session, novel_id)
        esc_state = escalation.get("state")
        scope_tier = escalation.get("scope_tier")

        # Get planted foreshadowing seeds
        seeds = await get_active_foreshadowing(session, novel_id)
        seed_text = "\n".join(
            f"- [{s.seed_type}] {s.description}" for s in seeds
        ) or "None"

        # Get chapter plan summary
        plan_stmt = (
            select(ChapterPlan)
            .where(
                ChapterPlan.novel_id == novel_id,
                ChapterPlan.chapter_number == chapter_number,
            )
        )
        plan_result = await session.execute(plan_stmt)
        plan = plan_result.scalar_one_or_none()
        plan_summary = ""
        if plan:
            plan_summary = f"Title: {plan.title or 'N/A'}"
            if plan.scene_outline:
                plan_summary += f"\nScenes: {json.dumps(plan.scene_outline)}"

        return {
            "chapter_number": str(chapter_number),
            "novel_title": "Novel",
            "chapter_plan_summary": plan_summary or "No plan",
            "current_tier_name": scope_tier.tier_name if scope_tier else "Unknown",
            "tier_order": str(scope_tier.tier_order if scope_tier else 1),
            "current_phase": esc_state.current_phase if esc_state else "buildup",
            "target_tension_range": str(
                esc_state.tension_level if esc_state else 0.5
            ),
            "planted_seeds": seed_text,
            "chapter_text": chapter_text,
        }

    async def _build_system_context(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        chapter_text: str,
    ) -> dict[str, str]:
        """Build context dict for system analysis prompt."""
        raw = await get_chapter_context(session, novel_id, chapter_number)
        ps = raw.get("power_system")
        guns = await get_active_chekhov_guns(session, novel_id)

        # Character power profile
        chars = raw.get("active_characters", [])
        protagonist = next((c for c in chars if c.role == "protagonist"), None)

        gun_text = "\n".join(
            f"- [{g.status}] {g.description}" for g in guns
        ) or "None"

        # Recent summaries
        recent = raw.get("recent_chapters", [])
        summaries = "\n".join(
            f"Ch {ch.chapter_number}: {ch.title or 'N/A'}"
            for ch in recent[:5]
        ) or "None"

        return {
            "chapter_number": str(chapter_number),
            "novel_title": "Novel",
            "power_system_name": ps.system_name if ps else "Unknown",
            "core_mechanic": ps.core_mechanic[:500] if ps else "Unknown",
            "hard_limits": ", ".join(ps.hard_limits) if ps and ps.hard_limits else "None",
            "protagonist_name": protagonist.name if protagonist else "Unknown",
            "current_rank": "Unknown",
            "rank_order": "1",
            "total_ranks": "10",
            "primary_discipline": "Unknown",
            "advancement_progress": "0%",
            "bottleneck_description": "Unknown",
            "abilities_with_proficiency": "None",
            "recent_summaries": summaries,
            "bible_entries": "See above",
            "active_guns": gun_text,
            "chapter_text": chapter_text,
        }

    async def _run_narrative_analysis(
        self,
        context: dict[str, str],
        novel_id: int,
        user_id: int,
        gen_ctx: GenerationContext | None = None,
    ) -> NarrativeAnalysisResult:
        """Run narrative analysis with 1 retry on parse failure."""
        system, user = NARRATIVE_ANALYSIS.render(**context)

        llm_kwargs: dict[str, Any] = {}
        if gen_ctx is not None:
            llm_kwargs["api_key"] = gen_ctx.api_key
            llm_kwargs["is_platform_key"] = gen_ctx.is_platform_key
            # Always use gen_ctx.model for analysis: ensures free tier
            # uses Haiku, and BYOK uses a model matching their key's provider
            llm_kwargs["model"] = gen_ctx.model

        for attempt in range(2):
            response = await self.llm.generate(
                system=system,
                user=user,
                temperature=NARRATIVE_ANALYSIS.temperature,
                max_tokens=NARRATIVE_ANALYSIS.max_tokens,
                response_format=NarrativeAnalysisResult,
                novel_id=novel_id,
                user_id=user_id,
                purpose="narrative_analysis",
                **llm_kwargs,
            )
            try:
                return NarrativeAnalysisResult.model_validate_json(response.content)
            except Exception as exc:
                if attempt == 0:
                    logger.warning("narrative_parse_retry", error=str(exc))
                    continue
                raise

        # Should not reach here, but satisfy type checker
        msg = "Narrative analysis failed after retries"
        raise RuntimeError(msg)

    async def _run_system_analysis(
        self,
        context: dict[str, str],
        novel_id: int,
        user_id: int,
        gen_ctx: GenerationContext | None = None,
    ) -> SystemAnalysisResult:
        """Run system analysis with 1 retry on parse failure."""
        system, user = SYSTEM_ANALYSIS.render(**context)

        llm_kwargs: dict[str, Any] = {}
        if gen_ctx is not None:
            llm_kwargs["api_key"] = gen_ctx.api_key
            llm_kwargs["is_platform_key"] = gen_ctx.is_platform_key
            llm_kwargs["model"] = gen_ctx.model

        for attempt in range(2):
            response = await self.llm.generate(
                system=system,
                user=user,
                temperature=SYSTEM_ANALYSIS.temperature,
                max_tokens=SYSTEM_ANALYSIS.max_tokens,
                response_format=SystemAnalysisResult,
                novel_id=novel_id,
                user_id=user_id,
                purpose="system_analysis",
                **llm_kwargs,
            )
            try:
                return SystemAnalysisResult.model_validate_json(response.content)
            except Exception as exc:
                if attempt == 0:
                    logger.warning("system_parse_retry", error=str(exc))
                    continue
                raise

        msg = "System analysis failed after retries"
        raise RuntimeError(msg)
