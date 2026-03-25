"""Browse page routes: novel listing with filters and pagination."""

from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    ChapterDraft,
    Novel,
    NovelStats,
    User,
)
from aiwebnovel.db.session import get_db

from .helpers import (
    _base_context,
    _inject_cover_urls,
    _novel_view,
    _templates,
)

router = APIRouter()


@router.get("/browse", response_class=HTMLResponse)
async def browse_page(
    request: Request,
    sort: str = Query("newest"),
    genre: Optional[list[str]] = Query(None),
    novel_status: Optional[str] = Query(None, alias="status"),
    rating: Optional[str] = Query(None),
    tab: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Browse novels page with filters, sort, and pagination."""
    ctx = await _base_context(request, db)

    # Base query — only public novels, exclude abandoned/incomplete/placeholder
    base_filter = and_(
        Novel.is_public.is_(True),
        Novel.status != "skeleton_pending",
        Novel.title != "Untitled World",
    )
    stmt = (
        select(Novel, NovelStats, User.display_name, User.username)
        .outerjoin(NovelStats, NovelStats.novel_id == Novel.id)
        .join(User, User.id == Novel.author_id)
        .where(base_filter)
    )

    if genre:
        # Filter out empty strings from checkbox submissions
        genre = [g for g in genre if g]
    if genre:
        stmt = stmt.where(Novel.genre.in_(genre))
    if novel_status:
        stmt = stmt.where(Novel.status == novel_status)

    # Parse rating filter (comes as string from form, may be empty)
    rating_int: int | None = None
    if rating and rating.strip():
        try:
            rating_int = int(rating)
        except ValueError:
            rating_int = None
    if rating_int and rating_int >= 1:
        stmt = stmt.where(
            func.coalesce(NovelStats.avg_rating, 0.0) >= rating_int
        )

    # Sort — tab presets override the default sort
    tab_sort_map = {
        "most_read": "most_read",
        "highest_rated": "highest_rated",
        "most_sloppy": "most_sloppy",
        "rising": "recently_updated",
    }
    effective_sort = sort
    if tab and tab in tab_sort_map and sort == "newest":
        effective_sort = tab_sort_map[tab]

    sort_map = {
        "newest": Novel.created_at.desc(),
        "recently_updated": Novel.updated_at.desc(),
        "most_read": func.coalesce(NovelStats.total_readers, 0).desc(),
        "highest_rated": func.coalesce(NovelStats.avg_rating, 0.0).desc(),
        "most_sloppy": func.coalesce(NovelStats.avg_rating, 0.0).asc(),
        "most_chapters": func.coalesce(NovelStats.total_chapters, 0).desc(),
    }
    stmt = stmt.order_by(sort_map.get(effective_sort, Novel.created_at.desc()))

    # Count total (for pagination)
    count_stmt = select(func.count()).select_from(
        select(Novel.id).where(base_filter).subquery()
    )
    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = math.ceil(total / per_page) if per_page > 0 else 0

    # Paginate
    offset = (page - 1) * per_page
    result = await db.execute(stmt.offset(offset).limit(per_page))
    rows = result.all()

    # Build novel view dicts with author names
    novels = []
    novel_ids = []
    for row in rows:
        novel_obj, stats_obj, display_name, username = row
        author_name = display_name or username or "Anonymous"
        nv = _novel_view(novel_obj, stats_obj, author_name=author_name)
        novels.append(nv)
        novel_ids.append(nv["id"])

    # Fix chapter counts: NovelStats.total_chapters is often stale because the
    # pipeline writes to chapter_drafts, not chapters. Always use draft count
    # as authoritative source and take the max of stats vs drafts.
    if novel_ids:
        latest_draft = (
            select(
                ChapterDraft.novel_id,
                ChapterDraft.chapter_number,
                func.max(ChapterDraft.draft_number).label("max_draft"),
            )
            .where(ChapterDraft.novel_id.in_(novel_ids))
            .group_by(ChapterDraft.novel_id, ChapterDraft.chapter_number)
            .subquery()
        )
        draft_counts_stmt = (
            select(
                ChapterDraft.novel_id,
                func.count(ChapterDraft.id).label("chapter_count"),
                func.sum(ChapterDraft.word_count).label("total_words"),
            )
            .join(
                latest_draft,
                and_(
                    ChapterDraft.novel_id == latest_draft.c.novel_id,
                    ChapterDraft.chapter_number == latest_draft.c.chapter_number,
                    ChapterDraft.draft_number == latest_draft.c.max_draft,
                ),
            )
            .group_by(ChapterDraft.novel_id)
        )
        draft_data = {
            row[0]: (row[1], row[2] or 0)
            for row in (await db.execute(draft_counts_stmt)).all()
        }
        for nv in novels:
            draft_ct, draft_words = draft_data.get(nv["id"], (0, 0))
            if draft_ct > nv["chapter_count"]:
                nv["chapter_count"] = draft_ct
                # Also fix effective status if it was stale
                if nv["status"] in (
                    "skeleton_pending", "skeleton_in_progress",
                    "skeleton_complete",
                ):
                    nv["status"] = "writing"
            if draft_words > nv["word_count"]:
                nv["word_count"] = draft_words

    # Filter out novels with no content (no chapters, no description,
    # still building) — these are abandoned creations
    novels = [
        nv for nv in novels
        if nv["chapter_count"] > 0
        or nv["description"]
        or nv["status"] not in ("skeleton_in_progress",)
    ]

    # Load cover images with full fallback chain (cover → pending → portrait → map)
    await _inject_cover_urls(db, novels)

    ctx.update({
        "novels": novels,
        "sort": sort,
        "selected_genres": genre or [],
        "selected_status": novel_status,
        "selected_rating": rating_int,
        "leaderboard_tab": tab,
        "current_page": page,
        "total_pages": total_pages,
    })

    # HTMX partial: return just the novel grid
    if request.headers.get("hx-request"):
        return _templates(request).TemplateResponse(
            "partials/novel_grid.html", ctx,
        )

    return _templates(request).TemplateResponse("pages/browse.html", ctx)
