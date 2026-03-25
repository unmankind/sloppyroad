"""Novel page routes: detail, create, delete, settings, share link, completion."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from aiwebnovel.auth.dependencies import get_optional_user
from aiwebnovel.db.models import (
    ArtAsset,
    ArtGenerationQueue,
    AuthorProfile,
    Chapter,
    ChapterDraft,
    Character,
    GenerationJob,
    Novel,
    NovelRating,
    NovelSeed,
    NovelSettings,
    NovelStats,
    NovelTag,
    PowerSystem,
    WorldBuildingStage,
)
from aiwebnovel.db.session import get_db

from .helpers import (
    _author_sidebar_context,
    _base_context,
    _get_novel_cover_url,
    _novel_view,
    _redirect_to_login,
    _templates,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

ALLOWED_GENRES = {
    "progression_fantasy",
    "cultivation",
    "litrpg",
    "isekai",
    "epic_fantasy",
    "dark_fantasy",
    "urban_fantasy",
}


# ---------------------------------------------------------------------------
# Create Novel
# ---------------------------------------------------------------------------


@router.get("/novels/new", response_class=HTMLResponse)
async def novel_new_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    error: Optional[str] = Query(None),
):
    """Render the 'create novel' form."""
    from aiwebnovel.story.tags import TAG_CATEGORIES

    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)
    ctx["error"] = error
    ctx["tag_categories"] = TAG_CATEGORIES

    # Check if free tier user is at world limit
    if ctx.get("plan_type") == "free":
        from aiwebnovel.auth.tier import check_world_limit

        user_id = ctx["current_author"]["user_id"]
        settings = request.app.state.settings
        allowed, reason = await check_world_limit(db, user_id, settings)
        if not allowed:
            ctx["limit_hit"] = True
            ctx["limit_message"] = reason

    return _templates(request).TemplateResponse("pages/novel_new.html", ctx)


@router.post("/novels/new")
async def novel_new_form(
    request: Request,
    title: str = Form("", max_length=200),
    genre: str = Form("progression_fantasy"),
    auto_title: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle novel creation form. Creates novel and redirects to it."""
    from aiwebnovel.story.seeds import select_seeds
    from aiwebnovel.story.tags import ALL_TAGS

    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return _redirect_to_login(request)

    # Write boundary: require a valid AuthorProfile before creating a novel
    if not ctx["current_author"].get("has_profile"):
        logger.warning(
            "novel_create_no_profile",
            user_id=ctx["current_author"]["user_id"],
        )
        return RedirectResponse(
            "/dashboard/settings?error=Please+complete+your+author+profile+first",
            status_code=303,
        )

    # Free tier limit checks
    from aiwebnovel.auth.tier import check_lifetime_budget, check_world_limit

    user_id = ctx["current_author"]["user_id"]
    settings = request.app.state.settings

    allowed, reason = await check_world_limit(db, user_id, settings)
    if not allowed:
        return RedirectResponse(
            f"/novels/new?error={reason.replace(' ', '+')}", status_code=303,
        )

    allowed, reason = await check_lifetime_budget(db, user_id, settings)
    if not allowed:
        return RedirectResponse(
            f"/novels/new?error={reason.replace(' ', '+')}", status_code=303,
        )

    if genre not in ALLOWED_GENRES:
        genre = "progression_fantasy"

    # Parse multi-value tags from form
    form_data = await request.form()
    raw_tags = form_data.getlist("tags")
    # Validate and cap at 10
    tag_slugs = [s for s in raw_tags if s in ALL_TAGS][:10]

    # "Figure it Out" — use placeholder title, will be renamed after world gen
    if auto_title:
        title = "Untitled World"
    elif not title.strip():
        return RedirectResponse(
            "/novels/new?error=Please+enter+a+title+or+check+Figure+it+Out",
            status_code=303,
        )

    novel = Novel(
        author_id=user_id,
        title=title.strip(),
        genre=genre,
        status="skeleton_pending",
        is_public=True,
        share_token=secrets.token_urlsafe(16),
    )
    db.add(novel)
    await db.flush()

    # Create NovelTag rows from selected tags
    for slug in tag_slugs:
        td = ALL_TAGS[slug]
        db.add(NovelTag(
            novel_id=novel.id,
            tag_name=td.slug,
            tag_category=td.category,
        ))
    await db.flush()

    # Create empty stats row
    stats = NovelStats(novel_id=novel.id)
    db.add(stats)
    await db.flush()

    # Generate diversity seeds weighted by author's selected tags
    seeds = select_seeds(author_tags=tag_slugs)
    for seed in seeds:
        novel_seed = NovelSeed(
            novel_id=novel.id,
            seed_id=seed.id,
            seed_category=seed.category,
            seed_text=seed.text,
            status="proposed",
        )
        db.add(novel_seed)
    await db.flush()

    logger.info(
        "novel_created_form",
        novel_id=novel.id,
        user_id=user_id,
        auto_title=bool(auto_title),
        tag_count=len(tag_slugs),
    )
    # Redirect to seed review page
    return RedirectResponse(f"/novels/{novel.id}/world/seeds", status_code=303)


# ---------------------------------------------------------------------------
# Novel Detail
# ---------------------------------------------------------------------------


@router.get("/novels/{novel_id}", response_class=HTMLResponse)
async def novel_detail_page(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Novel overview page with world, characters, chapters, stats."""
    ctx = await _base_context(request, db)

    # Load novel + stats in a single query
    stmt = (
        select(Novel, NovelStats)
        .outerjoin(NovelStats, NovelStats.novel_id == Novel.id)
        .where(Novel.id == novel_id)
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Novel not found"},
            status_code=404,
        )
    novel, stats = row
    ctx["novel"] = _novel_view(novel, stats)

    # Is current user the author?
    user = await get_optional_user(request)
    ctx["is_author"] = (
        user is not None
        and user.get("user_id") == novel.author_id
    )

    # World overview — check WorldBuildingStage for completed stages
    world_stages_stmt = (
        select(WorldBuildingStage)
        .where(
            WorldBuildingStage.novel_id == novel_id,
            WorldBuildingStage.status == "complete",
        )
        .order_by(WorldBuildingStage.stage_order.asc())
    )
    world_stages = (await db.execute(world_stages_stmt)).scalars().all()
    if world_stages:
        # Build world overview from multiple stages for a richer summary.
        summary_parts: list[str] = []
        stage_map = {s.stage_name: s for s in world_stages}

        cosmo = stage_map.get("cosmology")
        if cosmo and cosmo.parsed_data:
            forces = cosmo.parsed_data.get("fundamental_forces", [])
            if forces and isinstance(forces[0], dict):
                summary_parts.append(forces[0].get("description", "")[:150])

        power = stage_map.get("power_system")
        if power and power.parsed_data:
            ps_name = power.parsed_data.get("system_name", "")
            mechanic = power.parsed_data.get("core_mechanic", "")
            if ps_name:
                line = f"Power flows through {ps_name}."
                if mechanic:
                    line += f" {mechanic[:100]}"
                summary_parts.append(line)

        protag = stage_map.get("protagonist")
        if protag and protag.parsed_data:
            p_name = protag.parsed_data.get("name", "")
            p_bg = protag.parsed_data.get("background", "")[:120]
            if p_name and p_bg:
                summary_parts.append(f"{p_name} — {p_bg}")

        summary = " ".join(summary_parts) if summary_parts else "A world in the making..."
        ctx["world"] = {"summary": summary}
    else:
        ctx["world"] = None

    # Power system with ranks (single query via joinedload)
    ps_stmt = (
        select(PowerSystem)
        .options(joinedload(PowerSystem.ranks))
        .where(PowerSystem.novel_id == novel_id)
    )
    power_system = (await db.execute(ps_stmt)).unique().scalar_one_or_none()
    if power_system:
        ranks = sorted(power_system.ranks, key=lambda r: r.rank_order)[:5]
        ctx["power_system"] = {
            "name": power_system.system_name,
            "ranks": [{"name": r.rank_name, "is_current": False} for r in ranks],
        }
    else:
        ctx["power_system"] = None

    # Characters (top 4) — enrich with portrait URLs
    chars_stmt = (
        select(Character)
        .where(Character.novel_id == novel_id, Character.is_alive.is_(True))
        .order_by(Character.introduced_at_chapter.asc().nulls_first())
        .limit(4)
    )
    raw_chars = (await db.execute(chars_stmt)).scalars().all()
    char_views = []
    for c in raw_chars:
        portrait_stmt = (
            select(ArtAsset.file_path)
            .where(
                ArtAsset.entity_id == c.id,
                ArtAsset.entity_type == "character",
                ArtAsset.asset_type == "portrait",
            )
            .order_by(ArtAsset.created_at.desc())
            .limit(1)
        )
        portrait_path = (await db.execute(portrait_stmt)).scalar_one_or_none()
        char_views.append({
            "id": c.id,
            "name": c.name,
            "role": c.role,
            "portrait_url": f"/assets/images/{portrait_path}" if portrait_path else None,
        })
    ctx["characters"] = char_views

    # Chapters (first page loaded inline, rest via HTMX)
    # Merge Chapter records with ChapterDraft fallbacks (pipeline writes drafts first)
    ch_stmt = (
        select(Chapter)
        .where(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_number.asc())
    )
    all_ch = (await db.execute(ch_stmt)).scalars().all()

    seen: set[int] = set()
    by_number: dict[int, object] = {}
    for ch in all_ch:
        if ch.chapter_number not in seen:
            seen.add(ch.chapter_number)
            by_number[ch.chapter_number] = ch

    # Fill gaps from ChapterDraft — only fetch drafts for chapter numbers not
    # already in the chapters table (NOT IN subquery pushed to DB)
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
            by_number[d.chapter_number] = d

    chapters = sorted(by_number.values(), key=lambda c: c.chapter_number)[:20]

    ctx["chapters"] = chapters

    # Check for active chapter generation job (for "generating..." banner)
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
    active_gen_job = (await db.execute(gen_job_stmt)).scalar_one_or_none()

    # Heartbeat staleness check — ignore zombie/stale jobs
    # Threshold is configurable via settings.generation_stale_display_seconds.
    stale_threshold = request.app.state.settings.generation_stale_display_seconds
    if active_gen_job is not None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if active_gen_job.status == "running":
            last_beat = (
                active_gen_job.heartbeat_at
                or active_gen_job.started_at
                or active_gen_job.created_at
            )
            if last_beat and (now - last_beat).total_seconds() > stale_threshold:
                active_gen_job = None
        elif active_gen_job.status == "queued":
            if (now - active_gen_job.created_at).total_seconds() > stale_threshold:
                active_gen_job = None

    ctx["active_gen_job"] = active_gen_job
    ctx["chapter_count"] = len(chapters)

    # Override stats from actual chapter/draft data when NovelStats is missing/stale
    novel_view = ctx["novel"]
    if not novel_view["chapter_count"] and chapters:
        novel_view["chapter_count"] = len(chapters)
        novel_view["word_count"] = sum(
            getattr(ch, "word_count", 0) or 0 for ch in chapters
        )

    # Also check chapter_drafts for accurate counts (pipeline writes drafts first)
    latest_draft_sub = (
        select(
            ChapterDraft.chapter_number,
            func.max(ChapterDraft.draft_number).label("max_draft"),
        )
        .where(ChapterDraft.novel_id == novel_id)
        .group_by(ChapterDraft.chapter_number)
        .subquery()
    )
    draft_stats_stmt = (
        select(
            func.count(ChapterDraft.id),
            func.coalesce(func.sum(ChapterDraft.word_count), 0),
        )
        .where(ChapterDraft.novel_id == novel_id)
        .join(
            latest_draft_sub,
            and_(
                ChapterDraft.chapter_number == latest_draft_sub.c.chapter_number,
                ChapterDraft.draft_number == latest_draft_sub.c.max_draft,
            ),
        )
    )
    draft_row = (await db.execute(draft_stats_stmt)).one()
    draft_ch_count, draft_wc = int(draft_row[0]), int(draft_row[1])
    if draft_ch_count > novel_view["chapter_count"]:
        novel_view["chapter_count"] = draft_ch_count
        novel_view["word_count"] = draft_wc

    # Cover art — inject into novel dict so template accesses novel.cover_url
    cover_url, cover_generating = await _get_novel_cover_url(db, novel_id)
    novel_view["cover_url"] = cover_url
    novel_view["cover_generating"] = cover_generating

    # Cover asset object for regeneration button
    cover_asset_stmt = (
        select(ArtAsset)
        .where(
            ArtAsset.novel_id == novel_id,
            ArtAsset.asset_type == "cover",
            ArtAsset.is_current.is_(True),
        )
        .order_by(ArtAsset.created_at.desc())
        .limit(1)
    )
    ctx["cover_asset"] = (await db.execute(cover_asset_stmt)).scalar_one_or_none()

    # Retroactive cover generation: only for the author viewing their own novel
    # (prevents bots/crawlers from triggering cover generation on every page view)
    if ctx["world"] and ctx["is_author"]:
        existing_cover = (await db.execute(
            select(ArtAsset.id).where(
                ArtAsset.novel_id == novel_id,
                ArtAsset.asset_type == "cover",
            ).limit(1)
        )).scalar_one_or_none()
        pending_cover = (await db.execute(
            select(ArtGenerationQueue.id).where(
                ArtGenerationQueue.novel_id == novel_id,
                ArtGenerationQueue.asset_type == "cover",
                ArtGenerationQueue.status.in_(["pending", "generating"]),
            ).limit(1)
        )).scalar_one_or_none()
        if existing_cover is None and pending_cover is None:
            db.add(ArtGenerationQueue(
                novel_id=novel_id,
                asset_type="cover",
                entity_id=novel_id,
                entity_type="novel",
                priority=0,
                trigger_event="retroactive_cover",
            ))
            await db.commit()
            novel_view["cover_generating"] = True
            logger.info("retroactive_cover_enqueued", novel_id=novel_id)

    # Load user's existing rating for the interactive widget
    rating_value = 0
    user = await get_optional_user(request)
    if user:
        rating_stmt = (
            select(NovelRating.rating)
            .where(
                NovelRating.novel_id == novel_id,
                NovelRating.reader_id == user["user_id"],
            )
        )
        existing_rating = (await db.execute(rating_stmt)).scalar_one_or_none()
        if existing_rating:
            rating_value = existing_rating

    # Variables for star_rating.html partial
    novel_view = ctx["novel"]
    ctx["rating_value"] = rating_value
    ctx["novel_id"] = novel_id
    ctx["avg_rating"] = novel_view.get("avg_rating") or 0.0
    ctx["rating_count"] = novel_view.get("rating_count", 0)

    return _templates(request).TemplateResponse("pages/novel_detail.html", ctx)


# ---------------------------------------------------------------------------
# Novel Deletion
# ---------------------------------------------------------------------------


@router.post("/novels/{novel_id}/delete")
async def delete_novel(
    request: Request,
    novel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a novel and all associated data. Author ownership required.

    Cascade deletes handle all related tables (WorldBuildingStage, ChapterDraft,
    Chapter, GenerationJob, etc.) via SQLAlchemy relationship cascades.
    """
    user = await get_optional_user(request)
    if not user or user.get("role") != "author":
        if request.headers.get("HX-Request"):
            return HTMLResponse("", status_code=403)
        return RedirectResponse("/auth/login", status_code=303)

    user_id = user["user_id"]

    # Verify ownership
    stmt = select(Novel).where(Novel.id == novel_id, Novel.author_id == user_id)
    novel = (await db.execute(stmt)).scalar_one_or_none()

    if novel is None:
        logger.warning("delete_novel_not_found_or_unauthorized", novel_id=novel_id, user_id=user_id)
        if request.headers.get("HX-Request"):
            return HTMLResponse("", status_code=404)
        return RedirectResponse("/dashboard", status_code=303)

    title = novel.title
    await db.delete(novel)
    await db.commit()
    logger.info("novel_deleted", novel_id=novel_id, title=title, user_id=user_id)

    # HTMX: return empty string so the card is removed from DOM
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return RedirectResponse("/dashboard", status_code=303)


# ---------------------------------------------------------------------------
# THE END page
# ---------------------------------------------------------------------------


@router.get("/novels/{novel_id}/the-end", response_class=HTMLResponse)
async def the_end_page(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Completion celebration page."""
    ctx = await _base_context(request, db)

    # Novel with stats
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Novel not found"},
            status_code=404,
        )

    stats = (
        await db.execute(
            select(NovelStats).where(NovelStats.novel_id == novel_id)
        )
    ).scalar_one_or_none()

    ctx["novel"] = _novel_view(novel, stats)
    ctx["completion_summary"] = novel.completion_summary

    # User's rating if authenticated
    ctx["user_rating"] = None
    user = await get_optional_user(request)
    if user:
        rating = (
            await db.execute(
                select(NovelRating).where(
                    NovelRating.novel_id == novel_id,
                    NovelRating.reader_id == user["user_id"],
                )
            )
        ).scalar_one_or_none()
        if rating:
            ctx["user_rating"] = rating.rating

    return _templates(request).TemplateResponse("pages/the_end.html", ctx)


# ---------------------------------------------------------------------------
# Share Link
# ---------------------------------------------------------------------------


@router.get("/s/{share_token}", response_class=HTMLResponse)
async def shared_novel_page(
    share_token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Access a novel via share token — redirects to novel detail page."""
    stmt = select(Novel).where(Novel.share_token == share_token)
    novel = (await db.execute(stmt)).scalar_one_or_none()
    if novel is None:
        ctx = await _base_context(request, db)
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Novel not found"},
            status_code=404,
        )
    return RedirectResponse(f"/novels/{novel.id}", status_code=303)


# ---------------------------------------------------------------------------
# Novel Settings
# ---------------------------------------------------------------------------


@router.get("/novels/{novel_id}/settings", response_class=HTMLResponse)
async def novel_settings_page(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Novel settings page (author only) — planning mode, POV, autonomous, visibility."""
    ctx = await _base_context(request, db)

    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != user_id:
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Novel not found"},
            status_code=404,
        )

    # Load settings (auto-create if missing)
    settings = (
        await db.execute(
            select(NovelSettings).where(NovelSettings.novel_id == novel_id)
        )
    ).scalar_one_or_none()
    if settings is None:
        profile = (await db.execute(
            select(AuthorProfile).where(AuthorProfile.user_id == user_id)
        )).scalar_one_or_none()
        settings = NovelSettings(
            novel_id=novel_id,
            image_generation_enabled=(
                profile.default_image_generation_enabled
                if profile else False
            ),
        )
        db.add(settings)
        await db.flush()

    # Sidebar context: all author novels + stats
    await _author_sidebar_context(ctx, db, user_id)

    ctx["novel"] = next(
        (nv for nv in ctx["novels"] if nv["id"] == novel_id),
        _novel_view(novel),
    )
    ctx["settings"] = settings
    ctx["selected_novel"] = novel
    ctx["active_page"] = "novel_settings"

    # Model selection: resolve allowed models for the author's tier
    try:
        from aiwebnovel.auth.tier import get_allowed_models, resolve_tier

        app_settings = request.app.state.settings
        tier_info = await resolve_tier(db, user_id, app_settings)
        ctx["allowed_models"] = get_allowed_models(tier_info)
    except Exception:
        ctx["allowed_models"] = []

    return _templates(request).TemplateResponse("pages/novel_settings.html", ctx)


@router.put("/novels/{novel_id}/settings/visibility", response_class=HTMLResponse)
async def toggle_novel_visibility(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Toggle novel visibility (HTMX). Cycles: private -> public -> private."""
    user = await get_optional_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != user["user_id"]:
        return HTMLResponse("Not found", status_code=404)

    body = await request.form()
    # Intentional strict comparison: HTMX toggle sends exactly "true" or omits the field
    is_public = body.get("is_public") == "true"
    novel.is_public = is_public
    await db.flush()

    return _templates(request).TemplateResponse(
        "partials/visibility_badge.html",
        {"request": request, "is_public": is_public},
    )


@router.post(
    "/novels/{novel_id}/settings/regenerate-share-token",
    response_class=HTMLResponse,
)
async def regenerate_share_token(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate share token (HTMX)."""
    user = await get_optional_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != user["user_id"]:
        return HTMLResponse("Not found", status_code=404)

    novel.share_token = secrets.token_urlsafe(32)
    await db.flush()

    # Force https in production (app is behind Caddy/Cloudflare)
    base = str(request.base_url).replace("http://", "https://", 1)
    share_url = f"{base}novels/s/{novel.share_token}"
    return _templates(request).TemplateResponse(
        "partials/share_link.html",
        {
            "request": request,
            "novel_id": novel_id,
            "share_url": share_url,
        },
    )
