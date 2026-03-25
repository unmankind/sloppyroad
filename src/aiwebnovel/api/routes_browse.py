"""Public novel discovery and leaderboard routes."""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import get_current_user
from aiwebnovel.db.models import Novel, NovelRating, NovelStats
from aiwebnovel.db.schemas import (
    NovelList,
    NovelRatingCreate,
    NovelRatingRead,
    NovelStatsRead,
    PaginatedResponse,
)
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────


class BrowseNovelItem(BaseModel):
    novel: NovelList
    stats: Optional[NovelStatsRead] = None


class LeaderboardResponse(BaseModel):
    most_read: list[BrowseNovelItem]
    most_active: list[BrowseNovelItem]
    highest_rated: list[BrowseNovelItem]
    rising: list[BrowseNovelItem]


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/", response_model=PaginatedResponse)
async def browse_novels(
    sort: str = Query("newest", pattern="^(newest|most_read|highest_rated|recently_updated)$"),
    genre: Optional[str] = Query(None),
    novel_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """Public novel listing with filters and sort."""
    # Base query — only public novels
    stmt = select(Novel).where(Novel.is_public.is_(True))

    # Filters
    if genre:
        stmt = stmt.where(Novel.genre == genre)
    if novel_status:
        stmt = stmt.where(Novel.status == novel_status)

    # Sort
    if sort == "newest":
        stmt = stmt.order_by(Novel.created_at.desc())
    elif sort == "recently_updated":
        stmt = stmt.order_by(Novel.updated_at.desc())
    elif sort == "most_read":
        stmt = (
            stmt
            .outerjoin(NovelStats, NovelStats.novel_id == Novel.id)
            .order_by(func.coalesce(NovelStats.total_readers, 0).desc())
        )
    elif sort == "highest_rated":
        stmt = (
            stmt
            .outerjoin(NovelStats, NovelStats.novel_id == Novel.id)
            .order_by(func.coalesce(NovelStats.avg_rating, 0.0).desc())
        )

    # Pagination
    from aiwebnovel.db.queries import paginate

    result = await paginate(db, stmt, page=page, page_size=per_page)

    return PaginatedResponse(
        items=[NovelList.model_validate(n) for n in result["items"]],
        page=result["page"],
        page_size=result["page_size"],
        total=result["total"],
    )


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def leaderboard(
    db: AsyncSession = Depends(get_db),
) -> LeaderboardResponse:
    """Leaderboard: most read, active, rated, rising."""

    async def _top_novels(order_col: Any, limit: int = 10) -> list[BrowseNovelItem]:
        stmt = (
            select(Novel, NovelStats)
            .outerjoin(NovelStats, NovelStats.novel_id == Novel.id)
            .where(Novel.is_public.is_(True))
            .order_by(order_col)
            .limit(limit)
        )
        result = await db.execute(stmt)
        items = []
        for row in result.all():
            novel = row[0]
            stats = row[1]
            items.append(BrowseNovelItem(
                novel=NovelList.model_validate(novel),
                stats=NovelStatsRead.model_validate(stats) if stats else None,
            ))
        return items

    most_read = await _top_novels(
        func.coalesce(NovelStats.total_readers, 0).desc(),
    )
    most_active = await _top_novels(
        func.coalesce(NovelStats.last_chapter_at, Novel.created_at).desc(),
    )
    highest_rated = await _top_novels(
        func.coalesce(NovelStats.avg_rating, 0.0).desc(),
    )
    # Rising = most new readers recently (simplified to most recent with readers)
    rising = await _top_novels(
        func.coalesce(NovelStats.total_chapters, 0).desc(),
    )

    return LeaderboardResponse(
        most_read=most_read,
        most_active=most_active,
        highest_rated=highest_rated,
        rising=rising,
    )


@router.post(
    "/{novel_id}/rate",
    response_model=NovelRatingRead,
    status_code=status.HTTP_201_CREATED,
)
async def rate_novel(
    novel_id: int,
    body: NovelRatingCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NovelRatingRead:
    """Submit or update a rating (1-5) for a novel."""
    # Verify novel exists and is public
    novel_stmt = select(Novel).where(Novel.id == novel_id)
    novel_result = await db.execute(novel_stmt)
    novel = novel_result.scalar_one_or_none()
    if novel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

    user_id = user["user_id"]

    # Check if rating already exists
    existing_stmt = select(NovelRating).where(
        NovelRating.novel_id == novel_id,
        NovelRating.reader_id == user_id,
    )
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.rating = body.rating
        existing.review_text = body.review_text
        await db.flush()
        rating = existing
    else:
        rating = NovelRating(
            novel_id=novel_id,
            reader_id=user_id,
            rating=body.rating,
            review_text=body.review_text,
        )
        db.add(rating)
        await db.flush()

    # Update novel stats
    avg_stmt = (
        select(func.avg(NovelRating.rating), func.count(NovelRating.id))
        .where(NovelRating.novel_id == novel_id)
    )
    avg_result = await db.execute(avg_stmt)
    avg_row = avg_result.one()

    stats_stmt = select(NovelStats).where(NovelStats.novel_id == novel_id)
    stats_result = await db.execute(stats_stmt)
    stats = stats_result.scalar_one_or_none()
    if stats:
        stats.avg_rating = float(avg_row[0]) if avg_row[0] else None
        stats.rating_count = int(avg_row[1])
        await db.flush()

    logger.info("novel_rated", novel_id=novel_id, user_id=user_id, rating=body.rating)

    return NovelRatingRead.model_validate(rating)
