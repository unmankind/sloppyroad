"""Chapter page routes: reading, generation, analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from aiwebnovel.auth.dependencies import get_optional_user
from aiwebnovel.auth.tier import check_chapter_limit, check_lifetime_budget
from aiwebnovel.db.models import (
    AdvancementEvent,
    ButterflyChoice,
    Chapter,
    ChapterDraft,
    ChekhovGun,
    ForeshadowingSeed,
    GenerationJob,
    Novel,
    OracleQuestion,
    StoryBibleEntry,
    TensionTracker,
)
from aiwebnovel.db.session import get_db

from .helpers import _base_context, _format_chapter_text, _templates

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Chapter Generation State (polling, survives page exit)
# ---------------------------------------------------------------------------


async def _chapter_generating_state(
    db: AsyncSession, novel_id: int, stale_display_seconds: int = 300,
) -> dict:
    """Query current chapter generation state for the generating page."""
    # Get latest chapter generation job for this novel
    job = (
        await db.execute(
            select(GenerationJob)
            .where(
                GenerationJob.novel_id == novel_id,
                GenerationJob.job_type == "chapter_generation",
            )
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if job is None:
        return {
            "job_status": "none",
            "chapter_number": None,
            "stage_name": None,
            "error_message": None,
            "started_at": None,
            "job_id": None,
        }

    # Auto-mark stale: if job heartbeat exceeds the configured threshold, mark stale
    if job.status in ("queued", "running"):
        from datetime import datetime, timezone

        heartbeat = job.heartbeat_at or job.started_at or job.created_at
        if heartbeat:
            age = (datetime.now(timezone.utc).replace(tzinfo=None) - heartbeat).total_seconds()
            if age > stale_display_seconds:
                job.status = "stale"
                await db.commit()

    # Check if chapter record exists (generation complete + saved)
    chapter_exists = False
    if job.chapter_number:
        ch = (
            await db.execute(
                select(Chapter.id).where(
                    Chapter.novel_id == novel_id,
                    Chapter.chapter_number == job.chapter_number,
                )
            )
        ).scalar_one_or_none()
        chapter_exists = ch is not None

    # If job says completed, verify chapter actually exists
    status = job.status
    if status == "completed" and not chapter_exists:
        # Draft may exist but Chapter record wasn't created (pipeline partial failure)
        draft = (
            await db.execute(
                select(ChapterDraft.id).where(
                    ChapterDraft.novel_id == novel_id,
                    ChapterDraft.chapter_number == job.chapter_number,
                )
            )
        ).scalar_one_or_none()
        if draft is not None:
            # Draft exists, treat as completed (chapter readable from draft)
            chapter_exists = True

    return {
        "job_status": status,
        "chapter_number": job.chapter_number,
        "stage_name": job.stage_name,
        "error_message": job.error_message,
        "started_at": (job.started_at or job.created_at).isoformat() if job else None,
        "job_id": job.id,
        "chapter_exists": chapter_exists,
    }


@router.get("/novels/{novel_id}/generate/status")
async def chapter_generating_status(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """JSON endpoint for polling chapter generation progress."""
    # Direct browser navigation gets redirected to the HTML generation page
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return RedirectResponse(f"/novels/{novel_id}/generate", status_code=303)

    stale_seconds = request.app.state.settings.generation_stale_display_seconds
    state = await _chapter_generating_state(db, novel_id, stale_seconds)
    return JSONResponse({
        "status": state["job_status"],
        "chapter_number": state["chapter_number"],
        "stage_name": state["stage_name"],
        "error_message": state["error_message"],
        "chapter_exists": state.get("chapter_exists", False),
    })


# ---------------------------------------------------------------------------
# Chapter Reading
# ---------------------------------------------------------------------------


@router.get(
    "/novels/{novel_id}/chapters/{chapter_num}",
    response_class=HTMLResponse,
)
async def chapter_read_page(
    novel_id: int,
    chapter_num: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Immersive chapter reading page."""
    ctx = await _base_context(request, db)

    # Novel
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Novel not found"},
            status_code=404,
        )
    ctx["novel"] = novel

    # Chapter (fall back to latest draft if Chapter record doesn't exist yet)
    from_draft = False
    chapter = (
        await db.execute(
            select(Chapter).where(
                Chapter.novel_id == novel_id,
                Chapter.chapter_number == chapter_num,
            )
        )
    ).scalar_one_or_none()
    if chapter is None:
        # Check for a draft (pipeline writes to chapter_drafts, not chapters)
        draft = (
            await db.execute(
                select(ChapterDraft).where(
                    ChapterDraft.novel_id == novel_id,
                    ChapterDraft.chapter_number == chapter_num,
                ).order_by(ChapterDraft.draft_number.desc()).limit(1)
            )
        ).scalars().first()
        if draft is None:
            return _templates(request).TemplateResponse(
                "pages/404.html",
                {**ctx, "message": "Chapter not found"},
                status_code=404,
            )
        chapter = draft
        from_draft = True
    ctx["chapter"] = chapter

    # Format chapter text into HTML paragraphs
    ctx["chapter_html"] = _format_chapter_text(chapter.chapter_text or "")

    # Ensure a title is available — Chapter has title, ChapterDraft does not
    ctx["chapter_title"] = getattr(chapter, "title", None) or None

    # Total chapters — use max of chapters table and chapter_drafts
    draft_total = (
        await db.execute(
            select(func.count(func.distinct(ChapterDraft.chapter_number))).where(
                ChapterDraft.novel_id == novel_id
            )
        )
    ).scalar_one()
    ch_total = (
        await db.execute(
            select(func.count(Chapter.id)).where(Chapter.novel_id == novel_id)
        )
    ).scalar_one()
    ctx["total_chapters"] = max(draft_total, ch_total)

    # Previous / next chapter — query by < / > to handle gaps in numbering
    prev = (
        await db.execute(
            select(Chapter).where(
                Chapter.novel_id == novel_id,
                Chapter.chapter_number < chapter_num,
            ).order_by(Chapter.chapter_number.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if prev is None:
        prev = (
            await db.execute(
                select(ChapterDraft).where(
                    ChapterDraft.novel_id == novel_id,
                    ChapterDraft.chapter_number < chapter_num,
                ).order_by(
                    ChapterDraft.chapter_number.desc(),
                    ChapterDraft.draft_number.desc(),
                ).limit(1)
            )
        ).scalars().first()
    ctx["prev_chapter"] = prev

    next_ch = (
        await db.execute(
            select(Chapter).where(
                Chapter.novel_id == novel_id,
                Chapter.chapter_number > chapter_num,
            ).order_by(Chapter.chapter_number.asc()).limit(1)
        )
    ).scalar_one_or_none()
    if next_ch is None:
        next_ch = (
            await db.execute(
                select(ChapterDraft).where(
                    ChapterDraft.novel_id == novel_id,
                    ChapterDraft.chapter_number > chapter_num,
                ).order_by(
                    ChapterDraft.chapter_number.asc(),
                    ChapterDraft.draft_number.desc(),
                ).limit(1)
            )
        ).scalars().first()
    ctx["next_chapter"] = next_ch

    # Is novel complete?
    ctx["is_complete"] = novel.status in ("complete", "writing_complete")

    # Is the current user the author? (for regenerate buttons)
    ctx["is_author"] = (
        ctx.get("current_author") is not None
        and ctx["current_author"].get("user_id") == novel.author_id
    )

    # Chapter images (use real chapter_id when reading from a draft)
    from aiwebnovel.db.models import ChapterImage as _ChapterImage

    image_chapter_id = (
        getattr(chapter, "chapter_id", None) if from_draft else chapter.id
    )
    if image_chapter_id:
        from sqlalchemy.orm import selectinload

        chapter_images_stmt = (
            select(_ChapterImage)
            .options(selectinload(_ChapterImage.art_asset))
            .where(_ChapterImage.chapter_id == image_chapter_id)
            .order_by(_ChapterImage.paragraph_index.asc())
        )
        ctx["chapter_images"] = (await db.execute(chapter_images_stmt)).scalars().all()
    else:
        ctx["chapter_images"] = []

    # Aftermath placeholder (from chapter summaries, if available)
    ctx["aftermath"] = None

    # Oracle — check for active question prompt
    oracle_stmt = (
        select(OracleQuestion)
        .where(
            OracleQuestion.novel_id == novel_id,
            OracleQuestion.status == "active",
        )
        .limit(1)
    )
    oracle = (await db.execute(oracle_stmt)).scalar_one_or_none()
    ctx["oracle_active"] = oracle is not None
    ctx["oracle_prompt"] = None

    # Butterfly choice — check for open choice
    butterfly_stmt = (
        select(ButterflyChoice)
        .where(
            ButterflyChoice.novel_id == novel_id,
            ButterflyChoice.status == "open",
        )
        .limit(1)
    )
    ctx["butterfly_choice"] = (
        await db.execute(butterfly_stmt)
    ).scalar_one_or_none()

    # Active generation job (for "Generate Next Chapter" button)
    active_gen_job = None
    if ctx["is_author"]:
        gen_job_stmt = (
            select(GenerationJob)
            .where(
                GenerationJob.novel_id == novel_id,
                GenerationJob.job_type == "chapter_generation",
                GenerationJob.status.in_(["queued", "running"]),
            )
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
        )
        active_gen_job = (
            await db.execute(gen_job_stmt)
        ).scalar_one_or_none()
        stale_threshold = (
            request.app.state.settings.generation_stale_display_seconds
        )
        if active_gen_job is not None:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            last_beat = (
                active_gen_job.heartbeat_at
                or active_gen_job.started_at
                or active_gen_job.created_at
            )
            if last_beat and (
                now - last_beat
            ).total_seconds() > stale_threshold:
                active_gen_job = None
    ctx["active_gen_job"] = active_gen_job

    return _templates(request).TemplateResponse("pages/chapter_read.html", ctx)


@router.get(
    "/novels/{novel_id}/generate",
    response_class=HTMLResponse,
)
async def chapter_generating_page(
    novel_id: int,
    request: Request,
    job_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Chapter generation status page (read-only).

    - With running job: reconnect and show progress
    - With job_id param: reconnect to that specific job
    - No active job: show "ready to generate" state with POST button
    """
    ctx = await _base_context(request, db)

    # Require authenticated author who owns this novel
    if not ctx.get("current_author"):
        return RedirectResponse("/auth/login", status_code=303)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Novel not found"},
            status_code=404,
        )

    if novel.author_id != ctx["current_author"]["user_id"]:
        return RedirectResponse(f"/novels/{novel_id}", status_code=303)

    ctx["novel"] = novel

    # Check for an existing in-progress chapter gen job
    stale_seconds = request.app.state.settings.generation_stale_display_seconds
    state = await _chapter_generating_state(db, novel_id, stale_seconds)

    if state["job_status"] in ("queued", "running"):
        # Reconnect to existing generation in progress
        job_id = state["job_id"] or job_id or 0
        ctx["chapter_number"] = state["chapter_number"] or "?"
        ctx["job_status"] = state["job_status"]
        ctx["started_at"] = state["started_at"] or ""
        ctx["current_stage"] = state["stage_name"] or ""
        ctx["error_message"] = state["error_message"] or ""
    elif state["job_status"] in ("completed",) and state.get("chapter_exists"):
        # Latest job completed — show completed state
        ctx["job_status"] = "completed"
        ctx["chapter_number"] = state["chapter_number"] or "?"
        ctx["started_at"] = state["started_at"] or ""
        ctx["current_stage"] = "saving"
        ctx["error_message"] = ""
        job_id = state["job_id"] or job_id or 0
    elif state["job_status"] == "failed":
        # Latest job failed — show error with retry
        ctx["job_status"] = "failed"
        ctx["chapter_number"] = state["chapter_number"] or "?"
        ctx["started_at"] = state["started_at"] or ""
        ctx["current_stage"] = state["stage_name"] or ""
        ctx["error_message"] = state["error_message"] or ""
        job_id = state["job_id"] or job_id or 0
    else:
        # No active job — show "ready to generate" state
        ctx["ready_to_generate"] = True
        ctx["job_status"] = "none"
        ctx["chapter_number"] = None
        ctx["started_at"] = ""
        ctx["current_stage"] = ""
        ctx["error_message"] = ""
        job_id = 0

    ctx["job_id"] = job_id

    return _templates(request).TemplateResponse(
        "pages/chapter_generating.html", ctx,
    )


@router.post(
    "/novels/{novel_id}/generate",
    response_class=HTMLResponse,
)
async def chapter_generate_start(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Trigger chapter generation (POST only) — creates job and redirects to status page."""
    ctx = await _base_context(request, db)

    # Require authenticated author who owns this novel
    if not ctx.get("current_author"):
        return RedirectResponse("/auth/login", status_code=303)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        return RedirectResponse("/dashboard", status_code=303)

    if novel.author_id != ctx["current_author"]["user_id"]:
        return RedirectResponse(f"/novels/{novel_id}", status_code=303)

    # If there's already a running job, just redirect to the status page
    stale_seconds = request.app.state.settings.generation_stale_display_seconds
    state = await _chapter_generating_state(db, novel_id, stale_seconds)
    if state["job_status"] in ("queued", "running"):
        return RedirectResponse(
            f"/novels/{novel_id}/generate?job_id={state['job_id']}",
            status_code=303,
        )

    # Free tier limit checks
    user = await get_optional_user(request)
    user_id = user.get("user_id") if user else None
    if user_id:
        settings = request.app.state.settings
        allowed, reason = await check_chapter_limit(
            db, novel_id, user_id, settings,
        )
        if not allowed:
            ctx["novel"] = novel
            ctx["limit_hit"] = True
            ctx["limit_message"] = reason
            return _templates(request).TemplateResponse(
                "pages/chapter_generating.html", ctx,
            )
        allowed, reason = await check_lifetime_budget(
            db, user_id, settings,
        )
        if not allowed:
            ctx["novel"] = novel
            ctx["limit_hit"] = True
            ctx["limit_message"] = reason
            return _templates(request).TemplateResponse(
                "pages/chapter_generating.html", ctx,
            )

    # Count chapters from BOTH chapters and chapter_drafts tables
    ch_count = (
        await db.execute(
            select(func.count(Chapter.id)).where(
                Chapter.novel_id == novel_id
            )
        )
    ).scalar_one()
    draft_count = (
        await db.execute(
            select(func.count(func.distinct(ChapterDraft.chapter_number))).where(
                ChapterDraft.novel_id == novel_id
            )
        )
    ).scalar_one()

    chapter_number = max(ch_count, draft_count) + 1

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    job = GenerationJob(
        novel_id=novel_id,
        job_type="chapter_generation",
        chapter_number=chapter_number,
        status="queued",
        started_at=now,
        heartbeat_at=now,
    )
    db.add(job)
    await db.flush()

    # Enqueue the arq task
    user = await get_optional_user(request)
    user_id = user.get("user_id", 0) if user else 0
    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        try:
            from aiwebnovel.worker.queue import enqueue_task

            arq_job_id = await enqueue_task(
                arq_pool,
                "generate_chapter_task",
                novel_id=novel_id,
                chapter_number=chapter_number,
                user_id=user_id,
                job_id=job.id,
            )
            job.arq_job_id = arq_job_id
            job.status = "running"
            await db.flush()
        except Exception as exc:
            logger.warning("enqueue_chapter_failed", error=str(exc), job_id=job.id)
    else:
        logger.warning("arq_pool_unavailable_chapter", job_id=job.id)

    await db.commit()

    logger.info(
        "chapter_generation_queued_page",
        novel_id=novel_id,
        job_id=job.id,
        chapter_number=chapter_number,
    )

    return RedirectResponse(
        f"/novels/{novel_id}/generate?job_id={job.id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Chapter Analysis page (author only)
# ---------------------------------------------------------------------------


@router.get(
    "/novels/{novel_id}/chapters/{chapter_num}/analysis",
    response_class=HTMLResponse,
)
async def chapter_analysis_page(
    novel_id: int,
    chapter_num: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Chapter analysis dashboard — author-only deep dive into post-generation analysis."""
    ctx = await _base_context(request, db)

    # Auth: require logged-in author who owns the novel
    if not ctx.get("current_author"):
        return RedirectResponse(url="/auth/login", status_code=302)

    # Novel
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        return _templates(request).TemplateResponse(
            "pages/404.html", {**ctx, "message": "Novel not found"}, status_code=404,
        )

    if novel.author_id != ctx["current_author"]["user_id"]:
        return RedirectResponse(f"/novels/{novel_id}", status_code=303)

    ctx["novel"] = novel

    # Chapter
    chapter = (
        await db.execute(
            select(Chapter).where(
                Chapter.novel_id == novel_id,
                Chapter.chapter_number == chapter_num,
            )
        )
    ).scalar_one_or_none()
    if chapter is None:
        return _templates(request).TemplateResponse(
            "pages/404.html", {**ctx, "message": "Chapter not found"}, status_code=404,
        )
    ctx["chapter"] = chapter

    # Tension data — presence indicates analysis has been run
    tension = (
        await db.execute(
            select(TensionTracker).where(
                TensionTracker.novel_id == novel_id,
                TensionTracker.chapter_number == chapter_num,
            )
        )
    ).scalar_one_or_none()

    ctx["analysis_available"] = tension is not None

    if tension is not None:
        ctx["tension"] = tension

        # Advancement events with character names
        adv_stmt = (
            select(AdvancementEvent)
            .options(joinedload(AdvancementEvent.character))
            .where(AdvancementEvent.chapter_number == chapter_num)
            .join(AdvancementEvent.character)
        )
        adv_rows = (await db.execute(adv_stmt)).unique().scalars().all()
        ctx["power_events"] = [a for a in adv_rows if a.character.novel_id == novel_id]

        # Foreshadowing seeds planted or fulfilled in this chapter
        foreshadowing_stmt = select(ForeshadowingSeed).where(
            ForeshadowingSeed.novel_id == novel_id,
            (ForeshadowingSeed.planted_at_chapter == chapter_num)
            | (ForeshadowingSeed.fulfilled_at_chapter == chapter_num),
        )
        ctx["foreshadowing"] = (await db.execute(foreshadowing_stmt)).scalars().all()

        # Story bible entries from this chapter
        bible_stmt = select(StoryBibleEntry).where(
            StoryBibleEntry.novel_id == novel_id,
            StoryBibleEntry.source_chapter == chapter_num,
        )
        ctx["bible_entries"] = (await db.execute(bible_stmt)).scalars().all()

        # Chekhov guns introduced/touched/resolved in this chapter
        guns_stmt = select(ChekhovGun).where(
            ChekhovGun.novel_id == novel_id,
            (ChekhovGun.introduced_at_chapter == chapter_num)
            | (ChekhovGun.last_touched_chapter == chapter_num)
            | (ChekhovGun.resolution_chapter == chapter_num),
        )
        ctx["chekhov_guns"] = (await db.execute(guns_stmt)).scalars().all()
    else:
        ctx["power_events"] = []
        ctx["foreshadowing"] = []
        ctx["bible_entries"] = []
        ctx["chekhov_guns"] = []

    return _templates(request).TemplateResponse("pages/chapter_analysis.html", ctx)
