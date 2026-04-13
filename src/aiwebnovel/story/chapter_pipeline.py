"""Chapter generation pipeline: planning, context, generation, analysis, saving.

Extracted from pipeline.py to reduce module size. Named chapter_pipeline.py
to avoid conflict with the existing generator.py (which contains ChapterGenerator).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import litellm.exceptions
import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArcPlan,
    Chapter,
    ChapterDraft,
    ChapterImage,
    ChapterPlan,
    ChapterSummary,
    GenerationJob,
    Novel,
    NovelSettings,
)
from aiwebnovel.llm.provider import BudgetExceededError, LLMProvider
from aiwebnovel.story.analyzer import ChapterAnalyzer
from aiwebnovel.story.context import ContextAssembler
from aiwebnovel.story.extractor import DataExtractor
from aiwebnovel.story.generator import ChapterGenerator
from aiwebnovel.story.genre_config import get_genre_config
from aiwebnovel.story.pipeline_jobs import PipelineJobManager
from aiwebnovel.story.scene_markers import extract_scene_markers
from aiwebnovel.story.validator import ChapterValidator

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime for DB compatibility."""
    return datetime.now(UTC).replace(tzinfo=None)


class ChapterPipelineRunner:
    """Handles chapter generation lifecycle: plan, context, generate, analyze, save."""

    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        context_assembler: ContextAssembler,
        generator: ChapterGenerator,
        analyzer: ChapterAnalyzer,
        validator: ChapterValidator,
        extractor: DataExtractor,
        job_manager: PipelineJobManager,
    ) -> None:
        self.llm = llm
        self.session_factory = session_factory
        self.settings = settings
        self.context_assembler = context_assembler
        self.generator = generator
        self.analyzer = analyzer
        self.validator = validator
        self.extractor = extractor
        self.job_manager = job_manager

    # ------------------------------------------------------------------
    # Auto-planning helpers
    # ------------------------------------------------------------------

    async def _ensure_arc_plan(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        user_id: int,
    ) -> ArcPlan | None:
        """Ensure an active arc plan covers the given chapter number.

        Creates and auto-approves a new arc if none exists or the current
        arc is exhausted. Inserts a bridge chapter at arc boundaries
        to give the story breathing room between arcs.

        Returns the active arc, or None if planning fails or is deferred
        to the author (supervised/collaborative mode).
        """
        from aiwebnovel.story.planner import StoryPlanner

        # Find active arc
        arc_stmt = (
            select(ArcPlan)
            .where(
                ArcPlan.novel_id == novel_id,
                ArcPlan.status.in_(["in_progress", "approved"]),
            )
            .order_by(ArcPlan.created_at.desc())
            .limit(1)
        )
        arc = (await session.execute(arc_stmt)).scalar_one_or_none()

        # Check if existing arc covers this chapter
        if arc is not None:
            if arc.target_chapter_end is None or chapter_number <= arc.target_chapter_end:
                # Arc covers this chapter — ensure it's in_progress
                if arc.status == "approved":
                    arc.status = "in_progress"
                    await session.flush()
                return arc

            # Arc exhausted — mark completed
            arc.status = "completed"
            await session.flush()

            logger.info(
                "arc_exhausted",
                novel_id=novel_id,
                arc_id=arc.id,
                title=arc.title,
                chapter_number=chapter_number,
            )

            # Notify author of arc completion
            try:
                from aiwebnovel.db.models import Notification

                session.add(Notification(
                    user_id=user_id,
                    novel_id=novel_id,
                    notification_type="arc_completed",
                    title=f"Arc complete: {arc.title}",
                    message=f"'{arc.title}' has wrapped up. The next arc awaits.",
                    action_url=f"/novels/{novel_id}/arcs",
                ))
                await session.flush()
            except Exception as exc:
                logger.warning(
                    "arc_completed_notification_failed",
                    arc_id=arc.id,
                    error=str(exc),
                )

            # Generate arc summary inline (fire-and-forget)
            try:
                from aiwebnovel.summarization.arc_summary import ArcSummarizer

                arc_summarizer = ArcSummarizer(self.llm, self.settings)
                arc_summary_text = await arc_summarizer.generate_arc_summary(
                    session, arc.id, user_id,
                )
                arc.arc_summary = arc_summary_text
                await session.flush()
                logger.info(
                    "arc_summary_generated_inline",
                    arc_id=arc.id,
                    novel_id=novel_id,
                )
            except Exception as exc:
                logger.warning(
                    "arc_summary_inline_failed",
                    arc_id=arc.id,
                    error=str(exc),
                )

            # Insert bridge chapter if this chapter isn't already a bridge
            planner = StoryPlanner(self.llm, self.settings)
            existing_plan = (await session.execute(
                select(ChapterPlan).where(
                    ChapterPlan.novel_id == novel_id,
                    ChapterPlan.chapter_number == chapter_number,
                )
            )).scalar_one_or_none()

            if existing_plan is None or not existing_plan.is_bridge:
                try:
                    await planner.create_bridge_chapter(
                        session, novel_id, chapter_number,
                        completed_arc=arc,
                    )
                    logger.info(
                        "auto_bridge_inserted",
                        novel_id=novel_id,
                        chapter_number=chapter_number,
                    )
                    # Bridge chapter will be generated this cycle;
                    # the NEXT chapter triggers new arc planning.
                    return None
                except (ValueError, Exception) as exc:
                    logger.warning(
                        "bridge_chapter_skipped",
                        novel_id=novel_id,
                        error=str(exc),
                    )
                    # Fall through to plan the next arc instead

        # Need a new arc — check planning mode
        has_completed_arcs = (await session.execute(
            select(func.count(ArcPlan.id)).where(
                ArcPlan.novel_id == novel_id,
                ArcPlan.status == "completed",
            )
        )).scalar_one() > 0

        if has_completed_arcs:
            # Subsequent arc — respect planning_mode
            ns = (await session.execute(
                select(NovelSettings).where(NovelSettings.novel_id == novel_id)
            )).scalar_one_or_none()
            planning_mode = ns.planning_mode if ns else "autonomous"

            if planning_mode != "autonomous":
                logger.info(
                    "arc_deferred_to_author",
                    novel_id=novel_id,
                    planning_mode=planning_mode,
                )
                return None

        # Auto-plan the arc
        planner = StoryPlanner(self.llm, self.settings)
        try:
            new_arc = await planner.plan_next_arc(session, novel_id, user_id)
            await planner.approve_arc(session, new_arc.id)
            new_arc.status = "in_progress"
            await session.flush()

            logger.info(
                "auto_arc_planned",
                novel_id=novel_id,
                arc_id=new_arc.id,
                title=new_arc.title,
                chapter_start=new_arc.target_chapter_start,
                chapter_end=new_arc.target_chapter_end,
            )
            return new_arc
        except Exception as exc:
            logger.warning(
                "auto_arc_planning_failed",
                novel_id=novel_id,
                chapter_number=chapter_number,
                error=str(exc),
            )
            return None

    async def _ensure_chapter_plan(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        user_id: int,
    ) -> ChapterPlan | None:
        """Ensure a detailed chapter plan exists for the given chapter.

        If a stub plan exists (from arc approval) but has no scene_outline,
        calls StoryPlanner.plan_chapter() to fill it in.

        Returns the chapter plan, or None if planning fails.
        """
        from aiwebnovel.story.planner import StoryPlanner

        plan_stmt = (
            select(ChapterPlan)
            .where(
                ChapterPlan.novel_id == novel_id,
                ChapterPlan.chapter_number == chapter_number,
            )
        )
        plan_result = await session.execute(plan_stmt)
        chapter_plan = plan_result.scalar_one_or_none()

        # If plan exists and is already detailed, return it
        if chapter_plan is not None and chapter_plan.scene_outline:
            return chapter_plan

        # Need to fill in details via LLM
        planner = StoryPlanner(self.llm, self.settings)
        try:
            chapter_plan = await planner.plan_chapter(
                session, novel_id, chapter_number, user_id,
            )
            logger.info(
                "auto_chapter_planned",
                novel_id=novel_id,
                chapter_number=chapter_number,
                title=chapter_plan.title,
            )
            return chapter_plan
        except Exception as exc:
            logger.warning(
                "auto_chapter_planning_failed",
                novel_id=novel_id,
                chapter_number=chapter_number,
                error=str(exc),
            )
            # Return the stub if it exists, or None
            return chapter_plan

    async def _save_draft(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        chapter_text: str,
        draft_number: int,
    ) -> ChapterDraft:
        """Save a chapter draft to the database."""
        # If the requested draft_number already exists, use the next available
        max_draft = (
            await session.execute(
                select(func.max(ChapterDraft.draft_number)).where(
                    ChapterDraft.novel_id == novel_id,
                    ChapterDraft.chapter_number == chapter_number,
                )
            )
        ).scalar_one_or_none()
        if max_draft is not None and draft_number <= max_draft:
            draft_number = max_draft + 1

        draft = ChapterDraft(
            novel_id=novel_id,
            chapter_number=chapter_number,
            draft_number=draft_number,
            chapter_text=chapter_text,
            word_count=len(chapter_text.split()),
            model_used=self.settings.litellm_default_model,
            status="draft",
        )
        session.add(draft)
        await session.flush()
        return draft

    # ------------------------------------------------------------------
    # Main chapter generation
    # ------------------------------------------------------------------

    async def generate_chapter(
        self,
        novel_id: int,
        chapter_number: int,
        user_id: int,
        guidance: str | None = None,
        job_id: int | None = None,
        gen_ctx: Any | None = None,
    ) -> dict[str, Any]:
        """Full chapter lifecycle: budget -> plan -> context -> generate ->
        analyze -> validate -> retry? -> extract -> store -> summarize.

        Returns a dict with result data (the caller wraps into ChapterResult).
        """
        result: dict[str, Any] = {
            "chapter_text": "",
            "chapter_id": None,
            "draft_number": 1,
            "analysis": None,
            "validation": None,
            "scene_markers": [],
            "bible_entry_ids": [],
            "success": False,
            "error": None,
            "flagged_for_review": False,
        }

        async with self.session_factory() as session:
            # Use existing job from route, or create a new one
            if job_id is not None:
                job = await session.get(GenerationJob, job_id)
                if job is None:
                    job = await self.job_manager.create_job(
                        session, novel_id, "chapter_generation", chapter_number,
                    )
                else:
                    job.status = "running"
                    job.started_at = job.started_at or _utcnow()
                    job.heartbeat_at = _utcnow()
            else:
                job = await self.job_manager.create_job(
                    session, novel_id, "chapter_generation", chapter_number,
                )
            await session.commit()

            try:
                # 2. Check budget
                await self.llm.budget_checker.check_llm_budget(session, novel_id)

                # 2b. Load genre config
                novel_obj_for_genre = await session.get(Novel, novel_id)
                novel_genre = (
                    novel_obj_for_genre.genre
                    if novel_obj_for_genre else "progression_fantasy"
                )
                genre_config = get_genre_config(novel_genre)

                # 3. Ensure arc + chapter plan exist
                await self.job_manager.update_stage(session, job, "planning")
                await session.commit()

                await self._ensure_arc_plan(
                    session, novel_id, chapter_number, user_id,
                )
                await self.job_manager.update_heartbeat(session, job)
                await session.commit()

                chapter_plan = await self._ensure_chapter_plan(
                    session, novel_id, chapter_number, user_id,
                )
                await session.commit()

                # 4. Assemble context
                await self.job_manager.update_stage(session, job, "assembling_context")
                await session.commit()

                context = await self.context_assembler.build_chapter_context(
                    session, novel_id, chapter_number, chapter_plan,
                )

                await self.job_manager.update_heartbeat(session, job)
                await session.commit()

                # 5. Load novel settings for generation params
                await self.job_manager.update_stage(session, job, "generating")
                await session.commit()

                ns_stmt = select(NovelSettings).where(
                    NovelSettings.novel_id == novel_id,
                )
                novel_settings = (
                    await session.execute(ns_stmt)
                ).scalar_one_or_none()

                raw_chapter_text = await self.generator.generate(
                    context, chapter_plan, novel_id, user_id, chapter_number,
                    retry_guidance=guidance,
                    gen_ctx=gen_ctx,
                    novel_settings=novel_settings,
                    genre_label=genre_config.genre_label,
                )

                # 5b. Extract scene markers, use clean text downstream
                chapter_text, scene_markers = extract_scene_markers(raw_chapter_text)
                result["scene_markers"] = scene_markers

                # Save draft 1
                draft = await self._save_draft(
                    session, novel_id, chapter_number, chapter_text, 1,
                )
                await session.commit()

                await self.job_manager.update_heartbeat(session, job)

                # 6. Analyze
                await self.job_manager.update_stage(session, job, "analyzing")
                await session.commit()

                analysis = await self.analyzer.analyze(
                    session, novel_id, chapter_number, chapter_text, user_id,
                    gen_ctx=gen_ctx,
                    genre_label=genre_config.genre_label,
                    genre_validation_addendum=genre_config.system_analysis_addendum,
                )
                result["analysis"] = analysis

                # 7. Validate
                validation = await self.validator.validate(
                    analysis, genre=novel_genre,
                )
                result["validation"] = validation

                # 8. Revision loop
                if not validation.passed:
                    logger.info(
                        "chapter_rejected_retrying",
                        novel_id=novel_id,
                        chapter_number=chapter_number,
                        issues=len(validation.issues),
                    )

                    # Update draft 1 as rejected
                    draft.status = "rejected"
                    draft.rejection_reason = validation.retry_guidance
                    await session.flush()

                    # Retry with guidance
                    raw_chapter_text = await self.generator.generate(
                        context,
                        chapter_plan,
                        novel_id,
                        user_id,
                        chapter_number,
                        retry_guidance=validation.retry_guidance,
                        gen_ctx=gen_ctx,
                        novel_settings=novel_settings,
                        genre_label=genre_config.genre_label,
                    )

                    # Re-extract scene markers from retry
                    chapter_text, scene_markers = extract_scene_markers(raw_chapter_text)
                    result["scene_markers"] = scene_markers

                    # Save draft 2
                    draft2 = await self._save_draft(
                        session, novel_id, chapter_number, chapter_text, 2,
                    )
                    result["draft_number"] = 2
                    await session.commit()

                    # Re-analyze
                    analysis = await self.analyzer.analyze(
                        session, novel_id, chapter_number, chapter_text, user_id,
                        gen_ctx=gen_ctx,
                        genre_label=genre_config.genre_label,
                        genre_validation_addendum=genre_config.system_analysis_addendum,
                    )
                    result["analysis"] = analysis

                    # Re-validate
                    validation = await self.validator.validate(
                        analysis, genre=novel_genre,
                    )
                    result["validation"] = validation

                    if not validation.passed:
                        # Flag for author review
                        result["flagged_for_review"] = True
                        draft2.status = "flagged"
                        draft2.rejection_reason = validation.retry_guidance
                        await session.flush()
                        logger.warning(
                            "chapter_flagged_for_review",
                            novel_id=novel_id,
                            chapter_number=chapter_number,
                        )

                # 9. Extract to DB and store
                await self.job_manager.update_stage(session, job, "saving")
                await session.commit()

                bible_entry_ids = await self.extractor.extract_from_analysis(
                    session, novel_id, chapter_number, analysis,
                )
                result["bible_entry_ids"] = bible_entry_ids

                # 10. Store final chapter
                chapter = Chapter(
                    novel_id=novel_id,
                    chapter_number=chapter_number,
                    title=(
                        chapter_plan.title
                        if chapter_plan and chapter_plan.title
                        else f"Chapter {chapter_number}"
                    ),
                    chapter_text=chapter_text,
                    word_count=len(chapter_text.split()),
                    status="published" if not result["flagged_for_review"] else "review",
                    arc_plan_id=chapter_plan.arc_plan_id if chapter_plan else None,
                )
                session.add(chapter)
                await session.flush()

                # 10b. Create ChapterImage records for scene markers
                for marker in result["scene_markers"]:
                    chapter_image = ChapterImage(
                        chapter_id=chapter.id,
                        paragraph_index=marker.paragraph_index,
                        scene_description=marker.description,
                        status="pending",
                    )
                    session.add(chapter_image)
                if result["scene_markers"]:
                    await session.flush()

                result["chapter_text"] = chapter_text
                result["chapter_id"] = chapter.id
                result["success"] = True

                # Update novel status to "writing" if not already
                novel = await session.get(Novel, novel_id)
                if novel is not None and novel.status not in (
                    "writing", "complete", "writing_complete",
                ):
                    novel.status = "writing"

                # Create stub summary (replaced by LLM task in generate_chapter_task)
                summary = ChapterSummary(
                    chapter_id=chapter.id,
                    summary_type="standard",
                    content=f"Chapter {chapter_number} generated. Summary pending.",
                )
                session.add(summary)

                await self.job_manager.complete_job(session, job)
                await session.commit()

                logger.info(
                    "chapter_generation_complete",
                    novel_id=novel_id,
                    chapter_number=chapter_number,
                    draft=result["draft_number"],
                    flagged=result["flagged_for_review"],
                )

            except BudgetExceededError as exc:
                result["error"] = str(exc)
                await self.job_manager.complete_job(session, job, "failed", str(exc))
                await session.commit()

            except (
                SQLAlchemyError,
                RuntimeError,
                litellm.exceptions.APIError,
                litellm.exceptions.Timeout,
                litellm.exceptions.APIConnectionError,
            ) as exc:
                result["error"] = str(exc)
                await self.job_manager.complete_job(session, job, "failed", str(exc))
                await session.commit()
                logger.error(
                    "chapter_generation_failed",
                    novel_id=novel_id,
                    chapter_number=chapter_number,
                    error=str(exc),
                )
                raise

        return result

    async def regenerate_chapter(
        self,
        novel_id: int,
        chapter_number: int,
        guidance: str,
        user_id: int,
    ) -> dict[str, Any]:
        """Re-generate chapter with author guidance, creates new draft.

        Returns a dict with result data (the caller wraps into ChapterResult).
        """
        result: dict[str, Any] = {
            "chapter_text": "",
            "chapter_id": None,
            "draft_number": 1,
            "analysis": None,
            "validation": None,
            "scene_markers": [],
            "bible_entry_ids": [],
            "success": False,
            "error": None,
            "flagged_for_review": False,
        }

        async with self.session_factory() as session:
            job = await self.job_manager.create_job(
                session, novel_id, "chapter_regeneration", chapter_number,
            )
            await session.commit()

            try:
                # Get current draft count
                draft_count_stmt = (
                    select(func.max(ChapterDraft.draft_number))
                    .where(
                        ChapterDraft.novel_id == novel_id,
                        ChapterDraft.chapter_number == chapter_number,
                    )
                )
                count_result = await session.execute(draft_count_stmt)
                max_draft = count_result.scalar_one() or 0
                next_draft = max_draft + 1

                # Load genre config
                novel_for_genre = await session.get(Novel, novel_id)
                regen_genre = (
                    novel_for_genre.genre
                    if novel_for_genre else "progression_fantasy"
                )
                regen_genre_config = get_genre_config(regen_genre)

                # Load chapter plan
                plan_stmt = (
                    select(ChapterPlan)
                    .where(
                        ChapterPlan.novel_id == novel_id,
                        ChapterPlan.chapter_number == chapter_number,
                    )
                )
                plan_result = await session.execute(plan_stmt)
                chapter_plan = plan_result.scalar_one_or_none()

                # Build context
                context = await self.context_assembler.build_chapter_context(
                    session, novel_id, chapter_number, chapter_plan,
                )

                # Generate with guidance
                # Load novel settings
                ns_stmt = select(NovelSettings).where(
                    NovelSettings.novel_id == novel_id,
                )
                novel_settings = (
                    await session.execute(ns_stmt)
                ).scalar_one_or_none()

                chapter_text = await self.generator.generate(
                    context,
                    chapter_plan,
                    novel_id,
                    user_id,
                    chapter_number,
                    retry_guidance=guidance,
                    novel_settings=novel_settings,
                    genre_label=regen_genre_config.genre_label,
                )

                # Save draft
                await self._save_draft(
                    session, novel_id, chapter_number, chapter_text, next_draft,
                )

                result["chapter_text"] = chapter_text
                result["draft_number"] = next_draft
                result["success"] = True

                # Update novel status to "writing" if not already
                novel_obj = await session.get(Novel, novel_id)
                if novel_obj is not None and novel_obj.status not in (
                    "writing", "complete", "writing_complete",
                ):
                    novel_obj.status = "writing"

                await self.job_manager.complete_job(session, job)
                await session.commit()

            except (
                SQLAlchemyError,
                RuntimeError,
                litellm.exceptions.APIError,
                litellm.exceptions.Timeout,
                litellm.exceptions.APIConnectionError,
            ) as exc:
                result["error"] = str(exc)
                await self.job_manager.complete_job(session, job, "failed", str(exc))
                await session.commit()
                raise

        return result
