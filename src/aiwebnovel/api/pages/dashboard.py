"""Dashboard page routes: main dashboard and usage/costs page."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    ArtGenerationQueue,
    AuthorProfile,
    ChapterDraft,
    ImageUsageLog,
    LLMUsageLog,
    Notification,
    Novel,
)
from aiwebnovel.db.session import get_db

from .helpers import (
    _author_settings_context,
    _base_context,
    _inject_cover_urls,
    _novel_view,
    _templates,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Author dashboard with novels, spending summary, notifications."""
    ctx = await _base_context(request, db)

    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]

    # Author's novels
    stmt = (
        select(Novel)
        .where(Novel.author_id == user_id)
        .order_by(Novel.updated_at.desc())
    )
    result = await db.execute(stmt)
    novels = result.scalars().all()
    novel_ids = [n.id for n in novels]

    # Compute chapter/word counts from chapter_drafts (latest draft per chapter)
    draft_counts: dict[int, tuple[int, int]] = {}
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
        counts_stmt = (
            select(
                ChapterDraft.novel_id,
                func.count(ChapterDraft.id).label("chapter_count"),
                func.coalesce(func.sum(ChapterDraft.word_count), 0).label("word_count"),
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
        for row in (await db.execute(counts_stmt)).all():
            draft_counts[row[0]] = (row[1], int(row[2]))

    # Failed image counts per novel
    failed_counts: dict[int, int] = {}
    if novel_ids:
        failed_counts_stmt = (
            select(
                ArtGenerationQueue.novel_id,
                func.count(ArtGenerationQueue.id),
            )
            .where(
                ArtGenerationQueue.novel_id.in_(novel_ids),
                ArtGenerationQueue.status == "failed",
            )
            .group_by(ArtGenerationQueue.novel_id)
        )
        failed_counts = {
            row[0]: row[1]
            for row in (await db.execute(failed_counts_stmt)).all()
        }

    novel_views = []
    for novel in novels:
        ch_count, w_count = draft_counts.get(novel.id, (0, 0))
        nv = _novel_view(novel, chapter_count_override=ch_count)
        nv["word_count"] = w_count
        nv["failed_image_count"] = failed_counts.get(novel.id, 0)
        novel_views.append(nv)

    # Inject cover thumbnails for dashboard cards
    await _inject_cover_urls(db, novel_views)

    ctx["novels"] = novel_views

    # Cost summary
    spent_stmt = select(
        func.coalesce(func.sum(LLMUsageLog.cost_cents), 0.0),
        func.count(LLMUsageLog.id),
    ).where(LLMUsageLog.user_id == user_id)
    spent_result = await db.execute(spent_stmt)
    spent_row = spent_result.one()
    total_spent_cents = float(spent_row[0])
    llm_calls = int(spent_row[1])

    profile_stmt = select(AuthorProfile).where(AuthorProfile.user_id == user_id)
    profile = (await db.execute(profile_stmt)).scalar_one_or_none()
    budget_cents = profile.api_budget_cents if profile else 0

    ctx["cost_summary"] = {
        "month_total": total_spent_cents / 100.0,
        "llm_calls": llm_calls,
        "image_gens": 0,
        "budget_remaining": (budget_cents - total_spent_cents) / 100.0,
    }

    # Notifications
    notif_stmt = (
        select(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .order_by(Notification.created_at.desc())
        .limit(5)
    )
    ctx["notifications"] = (await db.execute(notif_stmt)).scalars().all()

    # Author stats for author_base.html
    ctx["author_stats"] = {
        "novel_count": len(ctx["novels"]),
        "chapter_count": sum(n["chapter_count"] for n in ctx["novels"]),
        "word_count": sum(n["word_count"] for n in ctx["novels"]),
        "budget_remaining": ctx["cost_summary"]["budget_remaining"],
    }

    ctx["active_page"] = "dashboard"
    ctx["selected_novel"] = None

    return _templates(request).TemplateResponse("pages/dashboard.html", ctx)


# ---------------------------------------------------------------------------
# Usage & Costs
# ---------------------------------------------------------------------------


@router.get("/dashboard/usage", response_class=HTMLResponse)
async def usage_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Usage & costs dashboard with real LLM usage data."""
    ctx = await _author_settings_context(request, db)

    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]

    # Total aggregates
    totals_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(LLMUsageLog.cost_cents), 0).label("total_cost_cents"),
                func.coalesce(func.sum(LLMUsageLog.total_tokens), 0).label("total_tokens"),
                func.count(LLMUsageLog.id).label("total_calls"),
            ).where(LLMUsageLog.user_id == user_id)
        )
    ).one()

    # Per-novel breakdown
    per_novel_rows = (
        await db.execute(
            select(
                Novel.title,
                func.sum(LLMUsageLog.cost_cents).label("cost_cents"),
                func.sum(LLMUsageLog.total_tokens).label("tokens"),
                func.count(LLMUsageLog.id).label("calls"),
            )
            .join(Novel, LLMUsageLog.novel_id == Novel.id)
            .where(LLMUsageLog.user_id == user_id)
            .group_by(Novel.id, Novel.title)
            .order_by(func.sum(LLMUsageLog.cost_cents).desc())
        )
    ).all()

    # Per-model breakdown
    per_model_rows = (
        await db.execute(
            select(
                LLMUsageLog.model,
                func.sum(LLMUsageLog.cost_cents).label("cost_cents"),
                func.sum(LLMUsageLog.total_tokens).label("tokens"),
                func.count(LLMUsageLog.id).label("calls"),
            )
            .where(LLMUsageLog.user_id == user_id)
            .group_by(LLMUsageLog.model)
            .order_by(func.sum(LLMUsageLog.cost_cents).desc())
        )
    ).all()

    # Recent usage log (last 20)
    recent_rows = (
        await db.execute(
            select(
                LLMUsageLog.created_at,
                Novel.title.label("novel_title"),
                LLMUsageLog.model,
                LLMUsageLog.purpose,
                LLMUsageLog.total_tokens,
                LLMUsageLog.cost_cents,
            )
            .outerjoin(Novel, LLMUsageLog.novel_id == Novel.id)
            .where(LLMUsageLog.user_id == user_id)
            .order_by(LLMUsageLog.created_at.desc())
            .limit(20)
        )
    ).all()

    # ── Image usage (join through Novel to get author's images) ────────
    image_totals_row = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(ImageUsageLog.cost_cents), 0,
                ).label("total_cost_cents"),
                func.count(ImageUsageLog.id).label("total_gens"),
            )
            .join(Novel, ImageUsageLog.novel_id == Novel.id)
            .where(Novel.author_id == user_id)
        )
    ).one()

    image_by_type_rows = (
        await db.execute(
            select(
                ImageUsageLog.purpose,
                func.sum(ImageUsageLog.cost_cents).label("cost_cents"),
                func.count(ImageUsageLog.id).label("count"),
            )
            .join(Novel, ImageUsageLog.novel_id == Novel.id)
            .where(Novel.author_id == user_id)
            .group_by(ImageUsageLog.purpose)
            .order_by(func.sum(ImageUsageLog.cost_cents).desc())
        )
    ).all()

    ctx["active_page"] = "usage"
    ctx["totals"] = {
        "cost_cents": totals_row.total_cost_cents,
        "tokens": totals_row.total_tokens,
        "calls": totals_row.total_calls,
    }
    ctx["image_totals"] = {
        "cost_cents": image_totals_row.total_cost_cents,
        "gens": image_totals_row.total_gens,
    }
    ctx["image_by_type"] = image_by_type_rows
    ctx["per_novel"] = per_novel_rows
    ctx["per_model"] = per_model_rows
    ctx["recent"] = recent_rows

    return _templates(request).TemplateResponse(
        "pages/usage.html", ctx,
    )
