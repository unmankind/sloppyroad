"""HTMX partial endpoints: notification bell, chapter list, rate widget."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import get_optional_user
from aiwebnovel.db.models import (
    Chapter,
    ChapterDraft,
    Notification,
    NovelRating,
    NovelStats,
)
from aiwebnovel.db.session import get_db

from .helpers import _templates

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/novels/{novel_id}/chapters-list", response_class=HTMLResponse)
async def chapter_list_partial(
    novel_id: int,
    request: Request,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial: chapter card list for a novel."""
    per_page = 20
    offset = (page - 1) * per_page

    # Merge Chapter records with ChapterDraft fallbacks (pipeline writes drafts first)
    stmt = (
        select(Chapter)
        .where(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_number.asc())
    )
    all_chapters = (await db.execute(stmt)).scalars().all()

    seen: set[int] = set()
    deduped: list = []
    for ch in all_chapters:
        if ch.chapter_number not in seen:
            seen.add(ch.chapter_number)
            deduped.append(ch)

    # Only fetch drafts for chapter numbers not already in the chapters table
    existing_ch_nums = select(Chapter.chapter_number).where(
        Chapter.novel_id == novel_id,
    )
    draft_stmt = (
        select(ChapterDraft)
        .where(
            ChapterDraft.novel_id == novel_id,
            ~ChapterDraft.chapter_number.in_(existing_ch_nums),
        )
        .order_by(ChapterDraft.chapter_number.asc(), ChapterDraft.draft_number.desc())
    )
    drafts = (await db.execute(draft_stmt)).scalars().all()
    for d in drafts:
        if d.chapter_number not in seen:
            seen.add(d.chapter_number)
            deduped.append(d)

    deduped.sort(key=lambda c: c.chapter_number)

    total = len(deduped)
    chapters = deduped[offset : offset + per_page]

    has_more = (page * per_page) < total

    ctx = {
        "request": request,
        "chapters": chapters,
        "novel_id": novel_id,
        "page": page,
        "has_more": has_more,
    }
    return _templates(request).TemplateResponse(
        "partials/chapter_list.html", ctx,
    )


@router.get("/partials/notifications", response_class=HTMLResponse)
async def notifications_partial(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial: notification bell dropdown content."""
    user = await get_optional_user(request)
    notifications = []
    unread_count = 0

    if user:
        stmt = (
            select(Notification)
            .where(
                Notification.user_id == user["user_id"],
                Notification.is_read.is_(False),
            )
            .order_by(Notification.created_at.desc())
            .limit(20)
        )
        result = await db.execute(stmt)
        notifications = result.scalars().all()
        unread_count = len(notifications)

    ctx = {
        "request": request,
        "notifications": notifications,
        "unread_count": unread_count,
    }
    return _templates(request).TemplateResponse(
        "partials/notification_list.html", ctx,
    )


# ---------------------------------------------------------------------------
# Novel Rating (POST — used by the_end.html star rating widget)
# ---------------------------------------------------------------------------


@router.post("/novels/{novel_id}/rate", response_class=HTMLResponse)
async def rate_novel(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Submit or update a novel rating. Returns updated star widget HTML."""
    user = await get_optional_user(request)
    if not user:
        return HTMLResponse("<p class='text-muted text-sm'>Log in to rate.</p>")

    # Parse rating from form or JSON
    body = await request.form()
    try:
        rating_value = int(body.get("rating", 0))
    except (ValueError, TypeError):
        return HTMLResponse("<p class='text-muted text-sm'>Invalid rating.</p>")
    if rating_value < -5 or rating_value > 5 or rating_value == 0:
        return HTMLResponse("<p class='text-muted text-sm'>Invalid rating.</p>")

    user_id = user["user_id"]

    # Upsert rating
    existing = (
        await db.execute(
            select(NovelRating).where(
                NovelRating.novel_id == novel_id,
                NovelRating.reader_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.rating = rating_value
    else:
        db.add(NovelRating(
            novel_id=novel_id,
            reader_id=user_id,
            rating=rating_value,
        ))

    await db.flush()

    # Update stats
    avg_result = (
        await db.execute(
            select(func.avg(NovelRating.rating), func.count(NovelRating.id))
            .where(NovelRating.novel_id == novel_id)
        )
    ).one()

    stats = (
        await db.execute(
            select(NovelStats).where(NovelStats.novel_id == novel_id)
        )
    ).scalar_one_or_none()
    if stats:
        stats.avg_rating = float(avg_result[0]) if avg_result[0] else None
        stats.rating_count = int(avg_result[1])
        await db.flush()

    # Return updated star widget via template
    avg_rating = float(avg_result[0]) if avg_result[0] else 0
    rating_count = int(avg_result[1])
    return _templates(request).TemplateResponse(
        "partials/star_rating.html",
        {
            "request": request,
            "novel_id": novel_id,
            "rating_value": rating_value,
            "avg_rating": avg_rating,
            "rating_count": rating_count,
        },
    )
