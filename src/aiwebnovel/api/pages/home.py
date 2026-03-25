"""Homepage route."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    Chapter,
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


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request, db: AsyncSession = Depends(get_db)):
    """Landing page with featured novels and recent chapters."""
    ctx = await _base_context(request, db)

    # Featured novels: public, non-default title, has description or chapters
    stmt = (
        select(Novel, NovelStats, User.display_name, User.username)
        .outerjoin(NovelStats, NovelStats.novel_id == Novel.id)
        .join(User, User.id == Novel.author_id)
        .where(
            Novel.is_public.is_(True),
            Novel.title != "Untitled World",
        )
        .order_by(Novel.updated_at.desc())
        .limit(12)  # fetch extra, we'll filter further below
    )
    result = await db.execute(stmt)
    raw_rows = result.all()

    # Live chapter counts for novels where stats show 0
    novel_ids_need_count = [
        row[0].id for row in raw_rows
        if not row[1] or row[1].total_chapters == 0
    ]
    draft_counts: dict[int, int] = {}
    if novel_ids_need_count:
        latest_draft = (
            select(
                ChapterDraft.novel_id,
                ChapterDraft.chapter_number,
                func.max(ChapterDraft.draft_number).label("max_draft"),
            )
            .where(ChapterDraft.novel_id.in_(novel_ids_need_count))
            .group_by(ChapterDraft.novel_id, ChapterDraft.chapter_number)
            .subquery()
        )
        draft_counts_stmt = (
            select(
                ChapterDraft.novel_id,
                func.count(ChapterDraft.id).label("chapter_count"),
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
        draft_counts = {
            row[0]: row[1]
            for row in (await db.execute(draft_counts_stmt)).all()
        }

    featured = []
    for row in raw_rows:
        novel, stats, display_name, username = row
        ch_count = (
            stats.total_chapters if stats and stats.total_chapters
            else draft_counts.get(novel.id, 0)
        )
        # Filter: must have at least 1 chapter OR a non-empty description
        if ch_count == 0 and not novel.description:
            continue
        author_name = display_name or username or "Anonymous"
        featured.append(
            _novel_view(
                novel, stats,
                chapter_count_override=ch_count,
                author_name=author_name,
            )
        )
        if len(featured) >= 6:
            break
    await _inject_cover_urls(db, featured)
    ctx["featured_novels"] = featured

    # Recent chapters — include drafts (the pipeline writes to chapter_drafts)
    published_stmt = (
        select(Chapter, Novel)
        .join(Novel, Chapter.novel_id == Novel.id)
        .where(Novel.is_public.is_(True), Chapter.status == "published")
        .order_by(Chapter.created_at.desc())
        .limit(4)
    )
    pub_result = await db.execute(published_stmt)
    recent: list[dict] = []
    for row in pub_result.all():
        recent.append({
            "chapter_number": row[0].chapter_number,
            "title": row[0].title,
            "word_count": row[0].word_count,
            "novel_id": row[1].id,
            "novel_title": row[1].title,
            "created_at": row[0].created_at,
        })

    # Fill remaining slots from drafts if we don't have 4 published chapters
    if len(recent) < 4:
        seen_novel_ch = {(r["novel_id"], r["chapter_number"]) for r in recent}
        draft_stmt = (
            select(ChapterDraft, Novel)
            .join(Novel, ChapterDraft.novel_id == Novel.id)
            .where(Novel.is_public.is_(True))
            .order_by(ChapterDraft.created_at.desc())
            .limit(8)
        )
        draft_result = await db.execute(draft_stmt)
        for draft, novel in draft_result.all():
            if (novel.id, draft.chapter_number) in seen_novel_ch:
                continue
            recent.append({
                "chapter_number": draft.chapter_number,
                "title": f"Chapter {draft.chapter_number}",
                "word_count": draft.word_count,
                "novel_id": novel.id,
                "novel_title": novel.title,
                "created_at": draft.created_at,
            })
            seen_novel_ch.add((novel.id, draft.chapter_number))
            if len(recent) >= 4:
                break
        recent.sort(key=lambda r: r.get("created_at") or datetime.min, reverse=True)

    ctx["recent_chapters"] = recent[:4]

    return _templates(request).TemplateResponse("pages/home.html", ctx)


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Terms of Service page."""
    ctx = await _base_context(request, db)
    return _templates(request).TemplateResponse("pages/terms.html", ctx)


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Privacy Policy page."""
    ctx = await _base_context(request, db)
    return _templates(request).TemplateResponse("pages/privacy.html", ctx)
