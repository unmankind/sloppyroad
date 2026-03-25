"""Chapter generation and reading routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from aiwebnovel.auth.dependencies import get_current_user, require_novel_owner
from aiwebnovel.auth.tier import check_chapter_limit, check_lifetime_budget
from aiwebnovel.db.models import (
    AdvancementEvent,
    ArtGenerationQueue,
    Chapter,
    ChapterImage,
    ChekhovGun,
    ForeshadowingSeed,
    GenerationJob,
    Novel,
    StoryBibleEntry,
    TensionTracker,
)
from aiwebnovel.db.queries import get_chapters_paginated
from aiwebnovel.db.schemas import ChapterList, ChapterRead, PaginatedResponse
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────


class GenerateChapterResponse(BaseModel):
    job_id: int
    message: str


class RegenerateRequest(BaseModel):
    guidance: str = Field(..., min_length=1, max_length=5000)


class TensionData(BaseModel):
    level: float
    phase: Optional[str] = None
    key_drivers: list[str] = Field(default_factory=list)


class EarnedPowerData(BaseModel):
    character: str
    event_type: str
    description: str
    score: Optional[float] = None
    struggle_context: Optional[str] = None
    sacrifice_or_cost: Optional[str] = None
    foundation: Optional[str] = None


class ForeshadowingData(BaseModel):
    description: str
    seed_type: str
    status: str
    planted_at: int
    fulfilled_at: Optional[int] = None


class ChekhovGunData(BaseModel):
    description: str
    gun_type: str
    status: str
    pressure_score: float
    introduced_at: int
    last_touched: Optional[int] = None
    resolution_chapter: Optional[int] = None


class BibleEntryData(BaseModel):
    entry_type: str
    content: str
    tags: list[Any] = Field(default_factory=list)
    is_public_knowledge: bool = True


class ChapterAnalysisData(BaseModel):
    tension: Optional[TensionData] = None
    earned_power: list[EarnedPowerData] = Field(default_factory=list)
    foreshadowing: list[ForeshadowingData] = Field(default_factory=list)
    chekhov_guns: list[ChekhovGunData] = Field(default_factory=list)
    story_bible_entries: list[BibleEntryData] = Field(default_factory=list)


class ChapterAnalysisResponse(BaseModel):
    chapter_number: int
    analysis_available: bool
    analysis: Optional[ChapterAnalysisData] = None


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/{novel_id}/generate", response_model=GenerateChapterResponse)
async def generate_chapter(
    novel_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenerateChapterResponse:
    """Generate next chapter. Returns job_id for SSE tracking.

    Authors can always generate. Readers can only generate within an active arc.
    """
    from aiwebnovel.db.models import User as UserModel

    # Write boundary: verify user still exists in DB (guards against stale JWT)
    user_id = user.get("user_id")
    db_user = (
        await db.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
    ).scalar_one_or_none()
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found — please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify novel ownership
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        raise HTTPException(status_code=404, detail="Novel not found")
    if novel.author_id != user_id:
        raise HTTPException(status_code=403, detail="You do not own this novel")

    # Free tier limit checks
    settings = request.app.state.settings

    allowed, reason = await check_chapter_limit(
        db, novel_id, user_id, settings,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason,
            headers={"HX-Trigger": "show-upgrade-modal"},
        )

    allowed, reason = await check_lifetime_budget(
        db, user_id, settings,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason,
            headers={"HX-Trigger": "show-upgrade-modal"},
        )

    # Create generation job
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    job = GenerationJob(
        novel_id=novel_id,
        job_type="chapter_generation",
        status="queued",
        heartbeat_at=now,
    )
    db.add(job)
    await db.flush()

    # Determine next chapter number
    from sqlalchemy import func as sa_func

    ch_stmt = (
        select(sa_func.max(Chapter.chapter_number))
        .where(Chapter.novel_id == novel_id)
    )
    ch_result = await db.execute(ch_stmt)
    max_chapter = ch_result.scalar_one() or 0
    next_chapter = max_chapter + 1

    # Enqueue chapter generation task via arq
    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        try:
            from aiwebnovel.worker.queue import enqueue_task

            await enqueue_task(
                arq_pool,
                "generate_chapter_task",
                novel_id=novel_id,
                chapter_number=next_chapter,
                user_id=user.get("user_id", 0),
                job_id=str(job.id),
            )
            job.status = "running"
            await db.flush()
        except (SQLAlchemyError, RuntimeError) as exc:
            logger.warning("enqueue_chapter_failed", error=str(exc), job_id=job.id)
    else:
        logger.warning("arq_pool_unavailable", job_id=job.id)

    logger.info(
        "chapter_generation_queued",
        novel_id=novel_id,
        job_id=job.id,
        user_id=user.get("user_id"),
    )

    return GenerateChapterResponse(
        job_id=job.id,
        message="Chapter generation queued",
    )


@router.get("/{novel_id}/chapters", response_model=PaginatedResponse)
async def list_chapters(
    novel_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """List chapters for a novel (paginated)."""
    result = await get_chapters_paginated(db, novel_id, page=page, page_size=per_page)
    return PaginatedResponse(
        items=[ChapterList.model_validate(c) for c in result["items"]],
        page=result["page"],
        page_size=result["page_size"],
        total=result["total"],
    )


@router.get("/{novel_id}/chapters/{num}", response_model=ChapterRead)
async def read_chapter(
    novel_id: int,
    num: int,
    db: AsyncSession = Depends(get_db),
) -> ChapterRead:
    """Read a single chapter with inline images."""
    stmt = (
        select(Chapter)
        .options(selectinload(Chapter.images).selectinload(ChapterImage.art_asset))
        .where(
            Chapter.novel_id == novel_id,
            Chapter.chapter_number == num,
        )
    )
    result = await db.execute(stmt)
    chapter = result.scalar_one_or_none()

    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found",
        )

    # Build response with computed image_url
    chapter_data = ChapterRead.model_validate(chapter)
    for img_schema, img_model in zip(chapter_data.images, chapter.images):
        if img_model.art_asset and img_model.art_asset.file_path:
            img_schema.image_url = img_model.art_asset.file_path.replace(
                "./assets/images", "/assets/images"
            )
    return chapter_data


@router.get("/{novel_id}/chapters/{num}/analysis", response_model=ChapterAnalysisResponse)
async def chapter_analysis(
    novel_id: int,
    num: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> ChapterAnalysisResponse:
    """Get chapter analysis data (author only)."""
    stmt = select(Chapter).where(
        Chapter.novel_id == novel_id,
        Chapter.chapter_number == num,
    )
    result = await db.execute(stmt)
    chapter = result.scalar_one_or_none()

    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found",
        )

    # Tension data
    tension = (
        await db.execute(
            select(TensionTracker).where(
                TensionTracker.novel_id == novel_id,
                TensionTracker.chapter_number == num,
            )
        )
    ).scalar_one_or_none()

    # Advancement events (power progression) with character names
    adv_stmt = (
        select(AdvancementEvent)
        .options(joinedload(AdvancementEvent.character))
        .where(AdvancementEvent.chapter_number == num)
        .join(AdvancementEvent.character)
    )
    adv_rows = (await db.execute(adv_stmt)).unique().scalars().all()
    # Filter to this novel via the character relationship
    adv_events = [a for a in adv_rows if a.character.novel_id == novel_id]

    # Foreshadowing seeds planted or fulfilled in this chapter
    foreshadowing_stmt = select(ForeshadowingSeed).where(
        ForeshadowingSeed.novel_id == novel_id,
        (ForeshadowingSeed.planted_at_chapter == num)
        | (ForeshadowingSeed.fulfilled_at_chapter == num),
    )
    foreshadowing = (await db.execute(foreshadowing_stmt)).scalars().all()

    # Story bible entries extracted from this chapter
    bible_stmt = select(StoryBibleEntry).where(
        StoryBibleEntry.novel_id == novel_id,
        StoryBibleEntry.source_chapter == num,
    )
    bible_entries = (await db.execute(bible_stmt)).scalars().all()

    # Chekhov guns introduced or last touched in this chapter
    guns_stmt = select(ChekhovGun).where(
        ChekhovGun.novel_id == novel_id,
        (ChekhovGun.introduced_at_chapter == num)
        | (ChekhovGun.last_touched_chapter == num)
        | (ChekhovGun.resolution_chapter == num),
    )
    guns = (await db.execute(guns_stmt)).scalars().all()

    # If no tension data exists, analysis hasn't been run yet
    has_analysis = tension is not None

    if not has_analysis:
        return ChapterAnalysisResponse(
            chapter_number=num,
            analysis_available=False,
            analysis=None,
        )

    # Build structured analysis response
    analysis_data = ChapterAnalysisData(
        tension=TensionData(
            level=tension.tension_level,
            phase=tension.tension_phase,
            key_drivers=tension.key_tension_drivers or [],
        ),
        earned_power=[
            EarnedPowerData(
                character=a.character.name,
                event_type=a.event_type,
                description=a.description,
                score=a.earned_power_score,
                struggle_context=a.struggle_context,
                sacrifice_or_cost=a.sacrifice_or_cost,
                foundation=a.foundation,
            )
            for a in adv_events
        ],
        foreshadowing=[
            ForeshadowingData(
                description=f.description,
                seed_type=f.seed_type,
                status=f.status,
                planted_at=f.planted_at_chapter,
                fulfilled_at=f.fulfilled_at_chapter,
            )
            for f in foreshadowing
        ],
        story_bible_entries=[
            BibleEntryData(
                entry_type=b.entry_type,
                content=b.content,
                tags=b.tags or [],
                is_public_knowledge=b.is_public_knowledge,
            )
            for b in bible_entries
        ],
        chekhov_guns=[
            ChekhovGunData(
                description=g.description,
                gun_type=g.gun_type,
                status=g.status,
                pressure_score=g.pressure_score,
                introduced_at=g.introduced_at_chapter,
                last_touched=g.last_touched_chapter,
                resolution_chapter=g.resolution_chapter,
            )
            for g in guns
        ],
    )

    return ChapterAnalysisResponse(
        chapter_number=num,
        analysis_available=True,
        analysis=analysis_data,
    )


@router.post("/{novel_id}/chapters/{num}/regenerate", response_model=GenerateChapterResponse)
async def regenerate_chapter(
    novel_id: int,
    num: int,
    body: RegenerateRequest,
    request: Request,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> GenerateChapterResponse:
    """Regenerate chapter with author guidance (author only)."""
    # Verify chapter exists
    stmt = select(Chapter).where(
        Chapter.novel_id == novel_id,
        Chapter.chapter_number == num,
    )
    result = await db.execute(stmt)
    chapter = result.scalar_one_or_none()

    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found",
        )

    # Create regeneration job
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    job = GenerationJob(
        novel_id=novel_id,
        job_type="chapter_regeneration",
        chapter_number=num,
        status="queued",
        heartbeat_at=now,
    )
    db.add(job)
    await db.flush()

    # Enqueue regeneration task via arq (reuses generate_chapter_task with guidance)
    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        try:
            from aiwebnovel.worker.queue import enqueue_task

            await enqueue_task(
                arq_pool,
                "generate_chapter_task",
                novel_id=novel_id,
                chapter_number=num,
                user_id=user["user_id"],
                job_id=str(job.id),
                guidance=body.guidance,
            )
            job.status = "running"
            await db.flush()
        except (SQLAlchemyError, RuntimeError) as exc:
            logger.warning("enqueue_regeneration_failed", error=str(exc), job_id=job.id)
    else:
        logger.warning("arq_pool_unavailable", job_id=job.id)

    logger.info(
        "chapter_regeneration_queued",
        novel_id=novel_id,
        chapter_number=num,
        job_id=job.id,
    )

    return GenerateChapterResponse(
        job_id=job.id,
        message=f"Chapter {num} regeneration queued",
    )


@router.post("/{novel_id}/images/{image_id}/retry")
async def retry_chapter_image(
    novel_id: int,
    image_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Retry a failed chapter image by resetting it and its queue entry to pending.

    Returns an HTMX-friendly partial showing "Retrying..." status.
    """
    # Verify the ChapterImage belongs to this novel
    stmt = (
        select(ChapterImage)
        .join(Chapter, Chapter.id == ChapterImage.chapter_id)
        .where(
            ChapterImage.id == image_id,
            Chapter.novel_id == novel_id,
            ChapterImage.status == "failed",
        )
    )
    chapter_image = (await db.execute(stmt)).scalar_one_or_none()
    if chapter_image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Failed chapter image not found",
        )

    # Reset ChapterImage
    chapter_image.status = "pending"
    chapter_image.error_message = None

    # Reset or create corresponding ArtGenerationQueue entry
    queue_stmt = select(ArtGenerationQueue).where(
        ArtGenerationQueue.novel_id == novel_id,
        ArtGenerationQueue.asset_type == "scene",
        ArtGenerationQueue.entity_type == "chapter_image",
        ArtGenerationQueue.entity_id == image_id,
    )
    queue_item = (await db.execute(queue_stmt)).scalar_one_or_none()
    if queue_item:
        queue_item.status = "pending"
        queue_item.error_message = None
    else:
        # Create a new queue entry for retry
        queue_item = ArtGenerationQueue(
            novel_id=novel_id,
            asset_type="scene",
            entity_id=image_id,
            entity_type="chapter_image",
            priority=3,
            status="pending",
            trigger_event="manual_retry",
            trigger_chapter=chapter_image.paragraph_index,
        )
        db.add(queue_item)

    await db.commit()

    logger.info(
        "chapter_image_retry_requested",
        image_id=image_id,
        novel_id=novel_id,
    )

    import html as html_mod

    from fastapi.responses import HTMLResponse

    safe_desc = html_mod.escape(chapter_image.scene_description[:120])
    return HTMLResponse(
        f'<div class="chapter-image-failed mb-lg" id="chapter-img-{image_id}"'
        f' style="text-align: center; padding: var(--space-lg); background: var(--ink-900);'
        f' border: 1px dashed var(--arcane-600); border-radius: var(--radius-lg);">'
        f'<span style="font-size: 2rem; display: block; margin-bottom: var(--space-sm);'
        f' opacity: 0.5;">&#128247;</span>'
        f'<p class="text-sm" style="color: var(--arcane-400);">Retrying&hellip;</p>'
        f'<p class="text-xs text-muted mt-xs font-serif" style="font-style: italic;">'
        f'{safe_desc}</p>'
        f'</div>'
    )
