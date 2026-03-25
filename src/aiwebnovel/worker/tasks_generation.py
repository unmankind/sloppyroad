"""Generation task implementations: world, chapter, arc, autonomous tick.

Each task follows the arq pattern: ``async def task_name(ctx, **kwargs)``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArcPlan,
    Chapter,
    GenerationJob,
    Notification,
    Novel,
    NovelSettings,
)
from aiwebnovel.llm.budget import BudgetExceededError
from aiwebnovel.llm.sanitize import friendly_generation_error
from aiwebnovel.story.pipeline import StoryPipeline
from aiwebnovel.story.planner import StoryPlanner
from aiwebnovel.worker.progress import report_progress
from aiwebnovel.worker.tasks_common import _mark_job_failed, _utcnow

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# World Generation
# ---------------------------------------------------------------------------


async def generate_world_task(
    ctx: dict[str, Any],
    novel_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Run 8-stage world generation pipeline.

    Creates GenerationJob entry, reports progress per stage,
    updates novel status on completion. If image generation is
    enabled, generates initial assets (protagonist portrait + world map).
    """
    pipeline: StoryPipeline = ctx["pipeline"]
    settings: Settings = ctx["settings"]

    await report_progress(
        ctx, stage="starting_world_generation", progress=0.0, job_id=f"world-{novel_id}"
    )

    # Resolve BYOK context (model, keys, tier)
    gen_ctx = None
    try:
        from aiwebnovel.story.gen_context import GenerationContext

        session_factory = ctx.get("session_factory")
        if session_factory:
            async with session_factory() as session:
                gen_ctx = await GenerationContext.resolve(
                    session, user_id, novel_id, settings,
                )
    except Exception:
        logger.warning("gen_context_resolve_failed", novel_id=novel_id, user_id=user_id)

    try:
        result = await pipeline.generate_world(
            novel_id, user_id, gen_ctx=gen_ctx,
        )
    except Exception as exc:
        friendly = friendly_generation_error(exc)
        logger.error(
            "generate_world_task_failed",
            novel_id=novel_id,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        # Mark any running jobs as failed and reset novel status
        try:
            session_factory = ctx["session_factory"]
            async with session_factory() as session:
                job_stmt = select(GenerationJob).where(
                    GenerationJob.novel_id == novel_id,
                    GenerationJob.job_type == "world_generation",
                    GenerationJob.status.in_(["queued", "running"]),
                )
                jobs = (await session.execute(job_stmt)).scalars().all()
                for job in jobs:
                    job.status = "failed"
                    job.error_message = friendly
                    job.completed_at = _utcnow()
                novel = await session.get(Novel, novel_id)
                if novel and novel.status == "skeleton_in_progress":
                    novel.status = "seed_review"
                session.add(Notification(
                    user_id=user_id,
                    novel_id=novel_id,
                    notification_type="world_failed",
                    title="World generation failed",
                    message=friendly,
                    action_url=f"/novels/{novel_id}",
                ))
                await session.commit()
        except Exception:
            logger.warning(
                "world_task_cleanup_failed", novel_id=novel_id,
            )
        return {
            "success": False,
            "stages_completed": [],
            "error": friendly,
        }

    # Generate initial visual assets after world pipeline completes
    if result.success and settings.image_enabled:
        from aiwebnovel.worker.tasks_images import _generate_initial_assets

        await _generate_initial_assets(ctx, novel_id, user_id)
    elif result.success and not settings.image_enabled:
        logger.info(
            "image_generation_disabled_skipping_assets",
            novel_id=novel_id,
            hint="Set AIWN_IMAGE_ENABLED=true to enable cover art generation",
        )

    await report_progress(
        ctx, stage="world_generation_complete", progress=1.0, job_id=f"world-{novel_id}"
    )

    # Notify author that world is ready
    if result.success:
        try:
            session_factory = ctx["session_factory"]
            async with session_factory() as session:
                session.add(Notification(
                    user_id=user_id,
                    novel_id=novel_id,
                    notification_type="world_complete",
                    title="Your world is ready",
                    message="The slop machine has hallucinated a world. Time to start writing.",
                    action_url=f"/novels/{novel_id}",
                ))
                await session.commit()
        except Exception:
            logger.warning("world_complete_notification_failed", novel_id=novel_id)

    # Auto-start chapter 1 after successful world generation
    if result.success:
        try:
            from aiwebnovel.worker.queue import enqueue_task

            arq_pool = ctx.get("arq_pool") or ctx.get("redis")
            if arq_pool:
                await enqueue_task(
                    arq_pool,
                    "generate_chapter_task",
                    novel_id=novel_id,
                    chapter_number=1,
                    user_id=user_id,
                )
                logger.info(
                    "auto_chapter1_enqueued",
                    novel_id=novel_id,
                )
        except Exception:
            logger.warning(
                "auto_chapter1_enqueue_failed",
                novel_id=novel_id,
            )

    return {
        "success": result.success,
        "stages_completed": result.stages_completed,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# Arc Planning
# ---------------------------------------------------------------------------


async def generate_arc_task(
    ctx: dict[str, Any],
    novel_id: int,
    arc_id: int,
    user_id: int,
    author_notes: str | None = None,
    author_guidance: str | None = None,
) -> dict[str, Any]:
    """Generate or revise an arc plan via LLM.

    When *author_notes* is ``None``, generates a brand-new arc plan and
    populates the placeholder ArcPlan row created by the route.
    When *author_notes* is provided, revises the existing arc using
    ``StoryPlanner.revise_arc``.

    On success the arc status becomes ``"proposed"`` (new) or ``"revised"``
    and an ``arc_plan_ready`` notification is created for the author.
    On failure the arc status becomes ``"failed"``.
    """
    settings: Settings = ctx["settings"]
    llm = ctx["llm"]
    session_factory = ctx["session_factory"]

    planner = StoryPlanner(llm, settings)

    await report_progress(
        ctx, stage="arc_planning_started", progress=0.0, job_id=f"arc-{arc_id}",
    )

    try:
        async with session_factory() as session:
            if author_notes is not None:
                # ── Revision path ────────────────────────────────────
                arc = await planner.revise_arc(
                    session, arc_id, author_notes, user_id,
                )
                arc.status = "revised"
            else:
                # ── New generation path ──────────────────────────────
                # Gather context and call LLM (mirrors plan_next_arc
                # but updates the existing placeholder instead of
                # creating a new row).
                from aiwebnovel.llm.parsers import ArcPlanResult
                from aiwebnovel.llm.prompts import ARC_PLANNING

                arc_context = await planner._gather_arc_context(session, novel_id)
                if author_guidance:
                    arc_context["author_guidance"] = author_guidance

                # Resolve planning model (analysis_model if set, else Haiku)
                planning_model = await planner._planning_model(session, novel_id)

                system, user_prompt = ARC_PLANNING.render(**arc_context)
                response = await llm.generate(
                    system=system,
                    user=user_prompt,
                    model=planning_model,
                    temperature=ARC_PLANNING.temperature,
                    max_tokens=ARC_PLANNING.max_tokens,
                    response_format=ArcPlanResult,
                    novel_id=novel_id,
                    user_id=user_id,
                    purpose="arc_planning",
                )

                parsed = ArcPlanResult.model_validate_json(response.content)

                # Update the placeholder arc created by the route
                stmt = select(ArcPlan).where(ArcPlan.id == arc_id)
                result = await session.execute(stmt)
                arc = result.scalar_one()

                arc.title = parsed.title
                arc.description = parsed.description
                arc.target_chapter_start = parsed.target_chapter_start
                arc.target_chapter_end = parsed.target_chapter_end
                arc.planned_chapters = (
                    parsed.target_chapter_end - parsed.target_chapter_start + 1
                )
                arc.key_events = [e.model_dump() for e in parsed.key_events]
                arc.character_arcs = [c.model_dump() for c in parsed.character_arcs]
                arc.themes = [t.model_dump() for t in parsed.themes]
                arc.status = "proposed"

            # Create notification for the author
            notification = Notification(
                user_id=user_id,
                novel_id=novel_id,
                notification_type="arc_plan_ready",
                title="Arc plan ready for review",
                message=f'Arc "{arc.title}" is ready for your review.',
                action_url=f"/novels/{novel_id}/arcs/{arc_id}",
            )
            session.add(notification)

            await session.commit()

        await report_progress(
            ctx, stage="arc_planning_complete", progress=1.0, job_id=f"arc-{arc_id}",
        )

        logger.info(
            "arc_task_complete",
            novel_id=novel_id,
            arc_id=arc_id,
            revised=author_notes is not None,
        )

        return {
            "success": True,
            "arc_id": arc_id,
            "title": arc.title,
            "status": arc.status,
        }

    except Exception as exc:
        friendly = friendly_generation_error(exc)
        logger.error(
            "arc_task_failed",
            novel_id=novel_id,
            arc_id=arc_id,
            error=str(exc),
            exc_type=type(exc).__name__,
        )

        # Mark the arc as failed
        try:
            async with session_factory() as session:
                stmt = select(ArcPlan).where(ArcPlan.id == arc_id)
                result = await session.execute(stmt)
                arc = result.scalar_one_or_none()
                if arc is not None:
                    arc.status = "failed"
                session.add(Notification(
                    user_id=user_id,
                    novel_id=novel_id,
                    notification_type="arc_failed",
                    title="Arc planning failed",
                    message=f"Failed to plan arc: {friendly[:200]}",
                    action_url=f"/novels/{novel_id}/arcs",
                ))
                await session.commit()
        except Exception:
            logger.warning("arc_status_update_failed", arc_id=arc_id)

        return {"success": False, "arc_id": arc_id, "error": friendly}


# ---------------------------------------------------------------------------
# Chapter Generation
# ---------------------------------------------------------------------------


async def generate_chapter_task(
    ctx: dict[str, Any],
    novel_id: int,
    chapter_number: int,
    user_id: int,
    job_id: int | str | None = None,
    guidance: str | None = None,
) -> dict[str, Any]:
    """Full chapter generation lifecycle.

    1. Acquire Redis lock (novel:{id}:generating, TTL=600s)
    2. Delegate to StoryPipeline.generate_chapter (handles all sub-stages)
    3. Report progress via Redis pub/sub for SSE
    4. Release Redis lock
    5. Return result dict
    """
    pipeline: StoryPipeline = ctx["pipeline"]
    settings: Settings = ctx["settings"]

    # NOTE: Do NOT acquire Redis lock here — pipeline.generate_chapter()
    # handles locking internally. Double-locking causes immediate failure
    # because the second nx=True set finds the key already held.

    # Normalise job_id to int (route passes int, legacy callers may pass str)
    int_job_id: int | None = None
    if job_id is not None:
        try:
            int_job_id = int(job_id)
        except (ValueError, TypeError):
            int_job_id = None

    # Resolve BYOK context (model, keys, tier)
    gen_ctx = None
    try:
        from aiwebnovel.story.gen_context import GenerationContext

        session_factory = ctx.get("session_factory")
        if session_factory:
            async with session_factory() as session:
                gen_ctx = await GenerationContext.resolve(
                    session, user_id, novel_id, settings,
                )
    except Exception:
        logger.warning("gen_context_resolve_failed", novel_id=novel_id, user_id=user_id)

    await report_progress(ctx, stage="planning", progress=0.1, job_id=job_id)

    # Start background heartbeat to prevent false stale detection during
    # long LLM calls (the pipeline only updates heartbeat at discrete
    # checkpoints, but LLM calls can block for up to 300s per attempt)
    heartbeat_task = None
    health = ctx.get("health")
    if health is not None and int_job_id is not None:
        session_factory = ctx.get("session_factory")
        if session_factory:
            heartbeat_task = await health.start_heartbeat(
                session_factory, int_job_id,
            )

    try:
        result = await pipeline.generate_chapter(
            novel_id, chapter_number, user_id,
            guidance=guidance, job_id=int_job_id,
            gen_ctx=gen_ctx,
        )

        if not result.success and int_job_id is not None:
            # Pipeline returned an error without raising (e.g. lock conflict).
            # Mark the route-created job as failed so the UI reflects it.
            await _mark_job_failed(ctx, int_job_id, result.error or "Generation failed")

        if result.success:
            await report_progress(ctx, stage="complete", progress=1.0, job_id=job_id)

        # Notify author of chapter completion or flagged review
        if result.success:
            try:
                session_factory = ctx["session_factory"]
                async with session_factory() as session:
                    if result.flagged_for_review:
                        session.add(Notification(
                            user_id=user_id,
                            novel_id=novel_id,
                            notification_type="chapter_flagged",
                            title=f"Chapter {chapter_number} flagged for review",
                            message=(
                                f"Chapter {chapter_number} was generated but flagged "
                                f"for review — power validation issue detected."
                            ),
                            action_url=f"/novels/{novel_id}/chapters/{chapter_number}",
                        ))
                    else:
                        session.add(Notification(
                            user_id=user_id,
                            novel_id=novel_id,
                            notification_type="new_chapter",
                            title=f"Chapter {chapter_number} is ready",
                            message=f"Chapter {chapter_number} has been slopped into existence.",
                            action_url=f"/novels/{novel_id}/chapters/{chapter_number}",
                        ))
                    await session.commit()
            except Exception:
                logger.warning(
                    "chapter_notification_failed",
                    novel_id=novel_id,
                    chapter_number=chapter_number,
                )

        # Trigger image generation for power rank-ups (portrait evolution)
        if result.success and settings.image_enabled and result.analysis:
            from aiwebnovel.worker.tasks_images import _trigger_chapter_images

            await _trigger_chapter_images(ctx, novel_id, result.analysis)

        # Trigger scene image generation for inline illustrations
        if result.success and settings.image_enabled and result.scene_markers:
            from aiwebnovel.worker.tasks_images import _trigger_scene_images

            await _trigger_scene_images(ctx, novel_id, result.chapter_id)

        # Generate real LLM chapter summaries (standard + enhanced recap)
        if result.success and result.chapter_id:
            try:
                from aiwebnovel.worker.tasks_maintenance import (
                    generate_chapter_summary_task,
                )

                await generate_chapter_summary_task(
                    ctx,
                    novel_id=novel_id,
                    chapter_id=result.chapter_id,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.warning(
                    "chapter_summary_inline_failed",
                    novel_id=novel_id,
                    chapter_id=result.chapter_id,
                    error=str(exc),
                )

        # Embed new story bible entries (inline — lightweight)
        if result.success and result.bible_entry_ids:
            try:
                from aiwebnovel.worker.tasks_maintenance import embed_bible_entries_task

                embed_result = await embed_bible_entries_task(
                    ctx,
                    novel_id=novel_id,
                    entry_ids=result.bible_entry_ids,
                )
                logger.info(
                    "bible_entries_embedded_inline",
                    novel_id=novel_id,
                    count=embed_result.get("embedded_count", 0),
                )
            except Exception as exc:
                logger.warning(
                    "embed_inline_failed",
                    novel_id=novel_id,
                    error=str(exc),
                )

        return {
            "success": result.success,
            "chapter_id": result.chapter_id,
            "chapter_text_length": len(result.chapter_text) if result.chapter_text else 0,
            "flagged_for_review": result.flagged_for_review,
            "error": result.error,
        }

    except Exception as exc:
        friendly = friendly_generation_error(exc)
        logger.error(
            "chapter_task_failed",
            novel_id=novel_id,
            chapter_number=chapter_number,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        if int_job_id is not None:
            await _mark_job_failed(ctx, int_job_id, friendly)
        # Notify author
        try:
            session_factory = ctx["session_factory"]
            async with session_factory() as session:
                session.add(Notification(
                    user_id=user_id,
                    novel_id=novel_id,
                    notification_type="chapter_failed",
                    title=f"Chapter {chapter_number} generation failed",
                    message=friendly,
                    action_url=f"/novels/{novel_id}",
                ))
                await session.commit()
        except Exception:
            logger.warning(
                "chapter_notification_failed", novel_id=novel_id,
            )
        return {"success": False, "error": friendly}

    finally:
        if heartbeat_task is not None and health is not None:
            await health.stop_heartbeat(heartbeat_task)


# ---------------------------------------------------------------------------
# Cron: Autonomous Generation
# ---------------------------------------------------------------------------


async def autonomous_tick_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron (every hour): Find novels with autonomous generation enabled.

    For each eligible novel:
    - Check cadence (enough time elapsed since last generation)
    - Check daily budget
    - Check for stop conditions
    - Enqueue generate_chapter_task if ready
    """
    session_factory = ctx["session_factory"]
    llm = ctx["llm"]
    checked = 0
    enqueued = 0
    skipped = 0

    async with session_factory() as session:
        # Find novels with autonomous enabled via NovelSettings
        stmt = (
            select(Novel, NovelSettings)
            .join(NovelSettings, NovelSettings.novel_id == Novel.id)
            .where(NovelSettings.autonomous_generation_enabled.is_(True))
            .where(Novel.status.in_(["writing", "skeleton_complete"]))
        )
        result = await session.execute(stmt)
        rows = result.all()

        for novel, ns in rows:
            checked += 1

            # Check cadence
            if ns.last_autonomous_generation_at is not None:
                last_gen = ns.last_autonomous_generation_at
                # Strip timezone for SQLite compatibility
                if last_gen.tzinfo is not None:
                    last_gen = last_gen.replace(tzinfo=None)
                elapsed = _utcnow() - last_gen
                if elapsed < timedelta(hours=ns.autonomous_cadence_hours):
                    skipped += 1
                    continue

            # Check daily budget
            try:
                await llm.budget_checker.check_autonomous_daily_budget(
                    session, novel.id
                )
            except (SQLAlchemyError, RuntimeError, BudgetExceededError, ValueError):
                skipped += 1
                logger.info(
                    "autonomous_skip_budget",
                    novel_id=novel.id,
                )
                continue

            # Check consecutive failures (stop condition)
            if ns.autonomous_consecutive_failures >= 3:
                skipped += 1
                logger.info(
                    "autonomous_skip_failures",
                    novel_id=novel.id,
                    failures=ns.autonomous_consecutive_failures,
                )
                continue

            # Determine next chapter number
            ch_stmt = (
                select(func.max(Chapter.chapter_number))
                .where(Chapter.novel_id == novel.id)
            )
            ch_result = await session.execute(ch_stmt)
            max_chapter = ch_result.scalar_one() or 0
            next_chapter = max_chapter + 1

            # Update last generation time
            ns.last_autonomous_generation_at = _utcnow()
            await session.commit()

            # Enqueue via arq pool (non-blocking)
            arq_pool = ctx.get("arq_pool") or ctx.get("redis")
            if arq_pool is not None:
                try:
                    from aiwebnovel.worker.queue import enqueue_task

                    await enqueue_task(
                        arq_pool,
                        "generate_chapter_task",
                        novel_id=novel.id,
                        chapter_number=next_chapter,
                        user_id=novel.author_id,
                    )
                    # Reset consecutive failures on successful enqueue
                    ns.autonomous_consecutive_failures = 0
                    await session.commit()
                    enqueued += 1
                except (SQLAlchemyError, RuntimeError) as exc:
                    ns.autonomous_consecutive_failures += 1
                    await session.commit()
                    logger.error(
                        "autonomous_generation_failed",
                        novel_id=novel.id,
                        error=str(exc),
                    )
            else:
                logger.warning(
                    "autonomous_no_arq_pool",
                    novel_id=novel.id,
                )

    logger.info(
        "autonomous_tick_complete",
        checked=checked,
        enqueued=enqueued,
        skipped=skipped,
    )

    return {"checked": checked, "enqueued": enqueued, "skipped": skipped}
