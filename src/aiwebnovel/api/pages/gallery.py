"""Gallery and arc plan page routes."""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    ArcPlan,
    ArtAsset,
    ArtGenerationQueue,
    Chapter,
    ChapterDraft,
    ChapterPlan,
    ChekhovGun,
    Novel,
    NovelStats,
)
from aiwebnovel.db.session import get_db

from .helpers import (
    _author_sidebar_context,
    _base_context,
    _novel_view,
    _templates,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Arc Plans
# ---------------------------------------------------------------------------


@router.get("/novels/{novel_id}/arcs", response_class=HTMLResponse)
async def arcs_page(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Arc planning page showing all arcs for a novel."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Novel not found"},
            status_code=404,
        )
    if novel.author_id != user_id:
        return RedirectResponse("/dashboard", status_code=303)

    # Fetch arcs with their chapter plans eagerly loaded
    from sqlalchemy.orm import selectinload

    stmt = (
        select(ArcPlan)
        .where(ArcPlan.novel_id == novel_id)
        .options(selectinload(ArcPlan.chapter_plans))
        .order_by(ArcPlan.arc_number.asc())
    )
    arcs = (await db.execute(stmt)).scalars().all()

    # Sidebar context
    await _author_sidebar_context(ctx, db, user_id)
    ctx["selected_novel"] = next(
        (nv for nv in ctx["novels"] if nv["id"] == novel_id),
        _novel_view(novel),
    )
    ctx["active_page"] = "arcs"
    ctx["arcs"] = arcs
    ctx["novel_id"] = novel_id

    # Chapter count for empty-state messaging
    ch_count = (
        await db.execute(
            select(func.count(Chapter.id)).where(Chapter.novel_id == novel_id)
        )
    ).scalar_one()
    if ch_count == 0:
        ch_count = (
            await db.execute(
                select(func.count(func.distinct(ChapterDraft.chapter_number))).where(
                    ChapterDraft.novel_id == novel_id
                )
            )
        ).scalar_one()
    ctx["novel_chapter_count"] = ch_count

    return _templates(request).TemplateResponse("pages/arcs.html", ctx)


@router.post("/novels/{novel_id}/arcs/generate")
async def arcs_generate(
    novel_id: int,
    request: Request,
    author_guidance: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new arc plan (page route — form POST + redirect)."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != user_id:
        return RedirectResponse("/dashboard", status_code=303)

    from sqlalchemy import func as sa_func

    arc_count = (
        await db.execute(
            select(sa_func.count(ArcPlan.id)).where(ArcPlan.novel_id == novel_id)
        )
    ).scalar_one() or 0

    arc = ArcPlan(
        novel_id=novel_id,
        arc_number=arc_count + 1,
        title=f"Arc {arc_count + 1} (generating...)",
        description="Arc plan generation in progress",
        status="generating",
    )
    db.add(arc)
    await db.flush()

    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        from aiwebnovel.worker.queue import enqueue_task

        await enqueue_task(
            arq_pool,
            "generate_arc_task",
            novel_id=novel_id,
            arc_id=arc.id,
            user_id=user_id,
            author_guidance=author_guidance.strip() or None,
        )

    logger.info(
        "arc_generation_queued",
        novel_id=novel_id,
        arc_id=arc.id,
        has_guidance=bool(author_guidance.strip()),
    )
    await db.commit()
    return RedirectResponse(f"/novels/{novel_id}/arcs", status_code=303)


@router.post("/novels/{novel_id}/arcs/{arc_id}/approve")
async def arcs_approve(
    novel_id: int,
    arc_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Approve an arc plan and create chapter plans (page route)."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != user_id:
        return RedirectResponse("/dashboard", status_code=303)

    arc = (
        await db.execute(
            select(ArcPlan).where(
                ArcPlan.id == arc_id, ArcPlan.novel_id == novel_id,
            )
        )
    ).scalar_one_or_none()
    if arc is None or arc.status not in ("proposed", "revised"):
        return RedirectResponse(f"/novels/{novel_id}/arcs", status_code=303)

    from aiwebnovel.story.planner import approve_arc_plans

    plans = await approve_arc_plans(db, arc_id)
    await db.commit()

    logger.info(
        "arc_approved_page",
        arc_id=arc_id,
        novel_id=novel_id,
        chapter_plans_created=len(plans),
    )
    return RedirectResponse(f"/novels/{novel_id}/arcs", status_code=303)


@router.post("/novels/{novel_id}/arcs/{arc_id}/revise")
async def arcs_revise(
    novel_id: int,
    arc_id: int,
    request: Request,
    author_notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Submit revision notes for an arc (page route)."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != user_id:
        return RedirectResponse("/dashboard", status_code=303)

    arc = (
        await db.execute(
            select(ArcPlan).where(
                ArcPlan.id == arc_id, ArcPlan.novel_id == novel_id,
            )
        )
    ).scalar_one_or_none()
    if arc is None:
        return RedirectResponse(f"/novels/{novel_id}/arcs", status_code=303)

    arc.author_notes = author_notes.strip()
    arc.status = "revision_requested"

    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        from aiwebnovel.worker.queue import enqueue_task

        await enqueue_task(
            arq_pool,
            "generate_arc_task",
            novel_id=novel_id,
            arc_id=arc.id,
            user_id=user_id,
            author_notes=author_notes.strip(),
        )

    await db.commit()
    logger.info("arc_revision_requested_page", arc_id=arc_id, novel_id=novel_id)
    return RedirectResponse(f"/novels/{novel_id}/arcs", status_code=303)


@router.post("/novels/{novel_id}/arcs/{arc_id}/regenerate")
async def arcs_regenerate(
    novel_id: int,
    arc_id: int,
    request: Request,
    author_guidance: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate an arc plan from scratch (page route)."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != user_id:
        return RedirectResponse("/dashboard", status_code=303)

    arc = (
        await db.execute(
            select(ArcPlan).where(
                ArcPlan.id == arc_id, ArcPlan.novel_id == novel_id,
            )
        )
    ).scalar_one_or_none()
    if arc is None or arc.status in ("in_progress", "completed"):
        return RedirectResponse(f"/novels/{novel_id}/arcs", status_code=303)

    # Delete existing chapter plans for this arc
    await db.execute(
        delete(ChapterPlan).where(ChapterPlan.arc_plan_id == arc_id)
    )

    # Reset arc to generating state
    arc.title = f"Arc {arc.arc_number} (regenerating...)"
    arc.description = "Arc plan regeneration in progress"
    arc.status = "generating"

    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        from aiwebnovel.worker.queue import enqueue_task

        await enqueue_task(
            arq_pool,
            "generate_arc_task",
            novel_id=novel_id,
            arc_id=arc.id,
            user_id=user_id,
            author_guidance=author_guidance.strip() or None,
        )

    await db.commit()
    logger.info("arc_regeneration_queued", arc_id=arc_id, novel_id=novel_id)
    return RedirectResponse(f"/novels/{novel_id}/arcs", status_code=303)


# ---------------------------------------------------------------------------
# Chekhov Guns
# ---------------------------------------------------------------------------


@router.get("/novels/{novel_id}/chekhov", response_class=HTMLResponse)
async def chekhov_guns_page(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Chekhov's Gun dashboard — planted elements, pressure scores, lifecycle."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Novel not found"},
            status_code=404,
        )
    if novel.author_id != user_id:
        return RedirectResponse("/dashboard", status_code=303)

    stats = (
        await db.execute(select(NovelStats).where(NovelStats.novel_id == novel_id))
    ).scalar_one_or_none()

    await _author_sidebar_context(ctx, db, user_id)
    ctx["novel"] = next(
        (nv for nv in ctx["novels"] if nv["id"] == novel_id),
        _novel_view(novel, stats),
    )
    ctx["selected_novel"] = novel
    ctx["active_page"] = "chekhov"

    # Load all guns sorted by pressure
    guns_stmt = (
        select(ChekhovGun)
        .where(ChekhovGun.novel_id == novel_id)
        .order_by(ChekhovGun.pressure_score.desc())
    )
    ctx["guns"] = (await db.execute(guns_stmt)).scalars().all()

    return _templates(request).TemplateResponse("pages/chekhov_guns.html", ctx)


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------


@router.get("/novels/{novel_id}/gallery", response_class=HTMLResponse)
async def gallery_page(
    novel_id: int,
    request: Request,
    asset_type: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Gallery page showing all art assets for a novel with evolution chains."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]

    # Load novel + verify ownership
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Novel not found"},
            status_code=404,
        )
    if novel.author_id != user_id:
        return RedirectResponse("/dashboard", status_code=303)

    # Query art assets
    stmt = (
        select(ArtAsset)
        .where(ArtAsset.novel_id == novel_id)
        .order_by(ArtAsset.asset_type.asc(), ArtAsset.created_at.desc())
    )
    if asset_type:
        stmt = stmt.where(ArtAsset.asset_type == asset_type)
    if entity_type:
        stmt = stmt.where(ArtAsset.entity_type == entity_type)

    assets = (await db.execute(stmt)).scalars().all()

    # Group assets by type for the template
    assets_by_type: dict[str, list] = {}
    for asset in assets:
        assets_by_type.setdefault(asset.asset_type, []).append(asset)

    # Build evolution chains: map parent_asset_id → children
    evolution_chains: dict[int, list] = {}
    for asset in assets:
        if asset.parent_asset_id is not None:
            evolution_chains.setdefault(asset.parent_asset_id, []).append(asset)

    # Distinct filter values for the UI
    all_types_stmt = (
        select(ArtAsset.asset_type)
        .where(ArtAsset.novel_id == novel_id)
        .distinct()
    )
    all_entity_types_stmt = (
        select(ArtAsset.entity_type)
        .where(
            ArtAsset.novel_id == novel_id,
            ArtAsset.entity_type.isnot(None),
        )
        .distinct()
    )
    available_types = [
        row[0]
        for row in (await db.execute(all_types_stmt)).all()
    ]
    available_entity_types = [
        row[0]
        for row in (await db.execute(all_entity_types_stmt)).all()
    ]

    # Author stats + sidebar context
    await _author_sidebar_context(ctx, db, user_id)
    ctx["selected_novel"] = next(
        (nv for nv in ctx["novels"] if nv["id"] == novel_id),
        _novel_view(novel),
    )
    ctx["active_page"] = "gallery"

    # Failed image queue items
    failed_stmt = (
        select(ArtGenerationQueue)
        .where(
            ArtGenerationQueue.novel_id == novel_id,
            ArtGenerationQueue.status == "failed",
        )
        .order_by(ArtGenerationQueue.created_at.desc())
    )
    if asset_type:
        failed_stmt = failed_stmt.where(ArtGenerationQueue.asset_type == asset_type)
    failed_images = (await db.execute(failed_stmt)).scalars().all()

    # Check if an image provider is actually configured and usable
    from aiwebnovel.config import Settings as _Settings
    from aiwebnovel.images.provider import is_image_provider_configured

    app_settings = (
        request.app.state.settings
        if hasattr(request.app.state, "settings")
        else _Settings()
    )
    image_configured = is_image_provider_configured(app_settings)

    ctx["assets"] = assets
    ctx["assets_by_type"] = assets_by_type
    ctx["evolution_chains"] = evolution_chains
    ctx["failed_images"] = failed_images
    ctx["failed_image_count"] = len(failed_images)
    ctx["novel_id"] = novel_id
    ctx["filter_asset_type"] = asset_type
    ctx["filter_entity_type"] = entity_type
    ctx["available_types"] = available_types
    ctx["available_entity_types"] = available_entity_types
    ctx["image_provider_configured"] = image_configured
    ctx["image_provider_name"] = getattr(app_settings, "image_provider", "comfyui")

    return _templates(request).TemplateResponse("pages/gallery.html", ctx)
