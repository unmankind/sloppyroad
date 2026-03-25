"""World page routes: seeds, world generation, forging, overview, power system."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    AuthorProfile,
    GenerationJob,
    Novel,
    NovelSeed,
    NovelSettings,
    NovelStats,
    NovelTag,
    PowerSystem,
    WorldBuildingStage,
)
from aiwebnovel.db.session import get_db

from .helpers import (
    _base_context,
    _novel_view,
    _redirect_to_login,
    _templates,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Seed Review
# ---------------------------------------------------------------------------


@router.get("/novels/{novel_id}/world/seeds", response_class=HTMLResponse)
async def seed_review_page(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Seed review page — authors review/reroll/remove diversity seeds before world generation."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
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

    # Only the author should access this
    if novel.author_id != ctx["current_author"]["user_id"]:
        return RedirectResponse(f"/novels/{novel_id}", status_code=303)

    # If world is already built, redirect to world overview
    world_stage = (
        await db.execute(
            select(WorldBuildingStage.id).where(
                WorldBuildingStage.novel_id == novel_id,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if world_stage is not None:
        return RedirectResponse(f"/novels/{novel_id}/world", status_code=303)

    # Get proposed seeds
    stmt = (
        select(NovelSeed)
        .where(
            NovelSeed.novel_id == novel_id,
            NovelSeed.status == "proposed",
        )
        .order_by(NovelSeed.seed_category.asc(), NovelSeed.id.asc())
    )
    result = await db.execute(stmt)
    seeds = result.scalars().all()

    # Load existing custom direction if any
    settings_row = (await db.execute(
        select(NovelSettings.custom_genre_conventions)
        .where(NovelSettings.novel_id == novel_id)
    )).scalar_one_or_none()

    ctx["novel"] = novel
    ctx["seeds"] = seeds
    ctx["novel_id"] = novel_id
    ctx["custom_direction"] = settings_row or ""

    return _templates(request).TemplateResponse("pages/seed_review.html", ctx)


@router.post(
    "/novels/{novel_id}/world/seeds/reroll/{seed_id}",
    response_class=HTMLResponse,
)
async def seed_reroll_htmx(
    novel_id: int,
    seed_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HTMX: reroll a single seed and return the new seed card HTML."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return HTMLResponse("", status_code=401)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != ctx["current_author"]["user_id"]:
        return HTMLResponse("", status_code=404)

    old_seed = (
        await db.execute(
            select(NovelSeed).where(
                NovelSeed.id == seed_id,
                NovelSeed.novel_id == novel_id,
            )
        )
    ).scalar_one_or_none()
    if old_seed is None:
        return HTMLResponse("", status_code=404)

    from aiwebnovel.story.seeds import SEED_BANK, select_seeds

    # Get novel tags for weighted selection
    tag_result = await db.execute(
        select(NovelTag.tag_name).where(NovelTag.novel_id == novel_id)
    )
    author_tags = [row[0] for row in tag_result.all()]

    # Select replacement from same category
    category = old_seed.seed_category
    new_seeds = select_seeds(
        author_tags=author_tags,
        num_seeds=1,
        exclude_seeds={old_seed.seed_id},
    )
    new_seed_data = next((s for s in new_seeds if s.category == category), None)

    # Fallback: pick directly from category bank
    if new_seed_data is None:
        import random

        tag_set = set(author_tags)
        candidates = [
            s
            for s in SEED_BANK.get(category, [])
            if s.id != old_seed.seed_id and not (tag_set & s.incompatible_tags)
        ]
        if candidates:
            new_seed_data = random.choice(candidates)

    if new_seed_data is None:
        # No alternatives — return the existing card unchanged
        return _templates(request).TemplateResponse(
            "partials/seed_card.html",
            {"request": request, "seed": old_seed},
        )

    # Delete old, insert new
    await db.delete(old_seed)
    await db.flush()

    novel_seed = NovelSeed(
        novel_id=novel_id,
        seed_id=new_seed_data.id,
        seed_category=new_seed_data.category,
        seed_text=new_seed_data.text,
        status="proposed",
    )
    db.add(novel_seed)
    await db.flush()

    logger.info("seed_rerolled_page", novel_id=novel_id, old=old_seed.seed_id, new=new_seed_data.id)
    return _templates(request).TemplateResponse(
        "partials/seed_card.html",
        {"request": request, "seed": novel_seed},
    )


@router.delete(
    "/novels/{novel_id}/world/seeds/{seed_id}",
    response_class=HTMLResponse,
)
async def seed_remove_htmx(
    novel_id: int,
    seed_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HTMX: reject a seed and return empty response (card is removed from DOM)."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return HTMLResponse("", status_code=401)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != ctx["current_author"]["user_id"]:
        return HTMLResponse("", status_code=404)

    seed = (
        await db.execute(
            select(NovelSeed).where(
                NovelSeed.id == seed_id,
                NovelSeed.novel_id == novel_id,
            )
        )
    ).scalar_one_or_none()
    if seed is None:
        return HTMLResponse("")

    seed.status = "rejected"
    await db.flush()
    logger.info("seed_rejected_page", novel_id=novel_id, seed_id=seed.seed_id)

    # Empty response — HTMX outerHTML swap removes the card
    return HTMLResponse("")


@router.post(
    "/novels/{novel_id}/world/seeds/add",
    response_class=HTMLResponse,
)
async def seed_add_htmx(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HTMX: generate one additional seed and return its card HTML (appended to grid)."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return HTMLResponse("", status_code=401)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != ctx["current_author"]["user_id"]:
        return HTMLResponse("", status_code=404)

    # Enforce max 7 seeds
    proposed_count = (
        await db.execute(
            select(func.count(NovelSeed.id)).where(
                NovelSeed.novel_id == novel_id,
                NovelSeed.status == "proposed",
            )
        )
    ).scalar_one()
    if proposed_count >= 7:
        return HTMLResponse("", status_code=422)

    from aiwebnovel.story.seeds import select_seeds

    # Exclude all existing seeds to avoid duplicates
    existing_result = await db.execute(
        select(NovelSeed.seed_id).where(NovelSeed.novel_id == novel_id)
    )
    exclude = {row[0] for row in existing_result.all()}

    # Get novel tags for weighted selection
    tag_result = await db.execute(
        select(NovelTag.tag_name).where(NovelTag.novel_id == novel_id)
    )
    author_tags = [row[0] for row in tag_result.all()]

    new_seeds = select_seeds(
        author_tags=author_tags,
        num_seeds=1,
        exclude_seeds=exclude,
    )
    if not new_seeds:
        return HTMLResponse("", status_code=422)

    seed_data = new_seeds[0]
    novel_seed = NovelSeed(
        novel_id=novel_id,
        seed_id=seed_data.id,
        seed_category=seed_data.category,
        seed_text=seed_data.text,
        status="proposed",
    )
    db.add(novel_seed)
    await db.flush()

    logger.info("seed_added_page", novel_id=novel_id, seed_id=seed_data.id)
    return _templates(request).TemplateResponse(
        "partials/seed_card.html",
        {"request": request, "seed": novel_seed},
    )


@router.post(
    "/novels/{novel_id}/world/seeds/reroll-all",
    response_class=HTMLResponse,
)
async def seed_reroll_all_htmx(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HTMX: reroll all unlocked seeds, return full seed grid HTML."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return HTMLResponse("", status_code=401)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != ctx["current_author"]["user_id"]:
        return HTMLResponse("", status_code=404)

    # Parse locked IDs from HTMX hx-vals form data
    form = await request.form()
    locked_str = form.get("locked_seed_ids", "")
    locked_ids: set[int] = set()
    if locked_str:
        locked_ids = {int(x) for x in locked_str.split(",") if x.strip().isdigit()}

    # Get all proposed seeds
    proposed = (
        await db.execute(
            select(NovelSeed).where(
                NovelSeed.novel_id == novel_id,
                NovelSeed.status == "proposed",
            )
        )
    ).scalars().all()

    to_replace = [s for s in proposed if s.id not in locked_ids]

    if to_replace:
        from aiwebnovel.story.seeds import select_seeds

        # Exclude set: all current seed_ids minus the ones being replaced
        all_result = await db.execute(
            select(NovelSeed.seed_id).where(NovelSeed.novel_id == novel_id)
        )
        all_existing = {row[0] for row in all_result.all()}
        replace_ids = {s.seed_id for s in to_replace}
        exclude = all_existing - replace_ids

        # Get novel tags
        tag_result = await db.execute(
            select(NovelTag.tag_name).where(NovelTag.novel_id == novel_id)
        )
        author_tags = [row[0] for row in tag_result.all()]

        # Delete seeds being replaced
        for s in to_replace:
            await db.delete(s)
        await db.flush()

        # Select replacements
        new_seeds = select_seeds(
            author_tags=author_tags,
            num_seeds=len(to_replace),
            exclude_seeds=exclude,
        )
        for seed_data in new_seeds:
            db.add(
                NovelSeed(
                    novel_id=novel_id,
                    seed_id=seed_data.id,
                    seed_category=seed_data.category,
                    seed_text=seed_data.text,
                    status="proposed",
                )
            )
        await db.flush()

        logger.info(
            "seeds_rerolled_all_page",
            novel_id=novel_id,
            replaced=len(to_replace),
            locked=len(locked_ids),
        )

    # Fetch final proposed seeds and render all cards
    final = (
        await db.execute(
            select(NovelSeed)
            .where(
                NovelSeed.novel_id == novel_id,
                NovelSeed.status == "proposed",
            )
            .order_by(NovelSeed.seed_category.asc(), NovelSeed.id.asc())
        )
    ).scalars().all()

    # Render each card and concatenate (innerHTML swap replaces grid contents)
    parts = []
    for seed in final:
        resp = _templates(request).TemplateResponse(
            "partials/seed_card.html",
            {"request": request, "seed": seed},
        )
        parts.append(resp.body.decode())
    return HTMLResponse("".join(parts))


@router.post("/novels/{novel_id}/world/seeds/confirm")
async def seed_confirm_and_forge(
    novel_id: int,
    request: Request,
    custom_direction: str = Form("", max_length=2000),
    db: AsyncSession = Depends(get_db),
):
    """Confirm all proposed seeds and redirect to world generation."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return _redirect_to_login(request)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None or novel.author_id != ctx["current_author"]["user_id"]:
        return RedirectResponse("/dashboard", status_code=303)

    # Confirm all proposed seeds
    result = await db.execute(
        select(NovelSeed).where(
            NovelSeed.novel_id == novel_id,
            NovelSeed.status == "proposed",
        )
    )
    seeds = result.scalars().all()
    for seed in seeds:
        seed.status = "confirmed"
    await db.flush()

    # Save custom direction to NovelSettings
    custom_text = custom_direction.strip()
    if custom_text:
        settings = (await db.execute(
            select(NovelSettings).where(NovelSettings.novel_id == novel_id)
        )).scalar_one_or_none()
        if settings is None:
            user_id = ctx["current_author"]["user_id"]
            profile = (await db.execute(
                select(AuthorProfile).where(AuthorProfile.user_id == user_id)
            )).scalar_one_or_none()
            settings = NovelSettings(
                novel_id=novel_id,
                custom_genre_conventions=custom_text,
                image_generation_enabled=(
                    profile.default_image_generation_enabled
                    if profile else False
                ),
            )
            db.add(settings)
        else:
            settings.custom_genre_conventions = custom_text
        await db.flush()

    logger.info("seeds_confirmed_page", novel_id=novel_id, count=len(seeds),
                has_custom_direction=bool(custom_text))
    return RedirectResponse(
        f"/novels/{novel_id}/world/generate",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# World Generation
# ---------------------------------------------------------------------------


@router.get("/novels/{novel_id}/world/generate", response_class=HTMLResponse)
async def world_generate_page(
    novel_id: int,
    request: Request,
    job_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """World generation page — redirects to forging page if generation active."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    # If a job is running (or was started), redirect to the forging page
    if job_id is not None:
        return RedirectResponse(
            f"/novels/{novel_id}/world/forging", status_code=303,
        )

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

    # If there are unconfirmed seeds, redirect to seed review first
    proposed_count = (
        await db.execute(
            select(func.count(NovelSeed.id)).where(
                NovelSeed.novel_id == novel_id,
                NovelSeed.status == "proposed",
            )
        )
    ).scalar_one()
    if proposed_count > 0:
        return RedirectResponse(
            f"/novels/{novel_id}/world/seeds", status_code=303,
        )

    # Check if there's already an active world generation job
    active_job = (
        await db.execute(
            select(GenerationJob.id)
            .where(
                GenerationJob.novel_id == novel_id,
                GenerationJob.job_type == "world_generation",
                GenerationJob.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_job is not None:
        return RedirectResponse(
            f"/novels/{novel_id}/world/forging", status_code=303,
        )

    ctx["novel"] = novel
    ctx["job_id"] = job_id
    return _templates(request).TemplateResponse("pages/world_generating.html", ctx)


@router.post("/novels/{novel_id}/world/generate")
async def world_generate_start(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Kick off world generation and redirect to the streaming page."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
        return _redirect_to_login(request)

    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()
    if novel is None:
        return RedirectResponse("/dashboard", status_code=303)

    if novel.author_id != ctx["current_author"]["user_id"]:
        return RedirectResponse(f"/novels/{novel_id}", status_code=303)

    # Create generation job with heartbeat so stale detector doesn't kill it
    job = GenerationJob(
        novel_id=novel_id,
        job_type="world_generation",
        status="queued",
        heartbeat_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(job)
    await db.flush()

    # Enqueue world generation task via arq
    user_id = ctx["current_author"]["user_id"]
    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        try:
            from aiwebnovel.worker.queue import enqueue_task

            await enqueue_task(
                arq_pool,
                "generate_world_task",
                novel_id=novel_id,
                user_id=user_id,
            )
            job.status = "running"
            await db.flush()
        except (SQLAlchemyError, RuntimeError, ValueError) as exc:
            logger.warning("enqueue_world_failed", error=str(exc), job_id=job.id)
    else:
        logger.warning("arq_pool_unavailable", job_id=job.id)

    # Update novel status
    novel.status = "skeleton_in_progress"
    await db.flush()

    logger.info(
        "world_generation_started_page",
        novel_id=novel_id,
        job_id=job.id,
    )
    return RedirectResponse(
        f"/novels/{novel_id}/world/forging",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# World Forging (progress page)
# ---------------------------------------------------------------------------


async def _world_forging_state(
    db: AsyncSession, novel_id: int,
) -> dict:
    """Query current world generation state for the forging page."""
    # Get completed stages from WorldBuildingStage table
    completed_rows = (
        await db.execute(
            select(WorldBuildingStage.stage_name)
            .where(
                WorldBuildingStage.novel_id == novel_id,
                WorldBuildingStage.status == "complete",
            )
            .order_by(WorldBuildingStage.stage_order)
        )
    ).scalars().all()

    # Get latest generation job for this novel
    job = (
        await db.execute(
            select(GenerationJob)
            .where(
                GenerationJob.novel_id == novel_id,
                GenerationJob.job_type == "world_generation",
            )
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # Determine overall status
    if len(completed_rows) == 8:
        status = "completed"
    elif job is not None and job.status == "failed":
        status = "failed"
    elif job is not None:
        status = job.status
    else:
        status = "queued"

    return {
        "completed_stages": list(completed_rows),
        "job_status": status,
        "error_message": job.error_message if job else None,
        "started_at": job.created_at.isoformat() if job and job.created_at else None,
    }


@router.get("/novels/{novel_id}/world/forging/status")
async def world_forging_status(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """JSON endpoint for polling world generation progress."""
    state = await _world_forging_state(db, novel_id)
    return JSONResponse({
        "status": state["job_status"],
        "completed_stages": state["completed_stages"],
        "error_message": state["error_message"],
    })


@router.get("/novels/{novel_id}/world/forging", response_class=HTMLResponse)
async def world_forging_page(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Immersive loading page that shows world generation progress."""
    ctx = await _base_context(request, db)
    if not ctx["current_author"]:
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

    state = await _world_forging_state(db, novel_id)

    # If world is already complete, redirect to world overview
    if state["job_status"] == "completed" and len(state["completed_stages"]) == 8:
        return RedirectResponse(f"/novels/{novel_id}/world", status_code=303)

    ctx.update({
        "novel": novel,
        "completed_stages": state["completed_stages"],
        "job_status": state["job_status"],
        "error_message": state["error_message"] or "",
        "started_at": state["started_at"] or "",
    })
    return _templates(request).TemplateResponse("pages/world_forging.html", ctx)


# ---------------------------------------------------------------------------
# World Overview & Power System
# ---------------------------------------------------------------------------


@router.get("/novels/{novel_id}/world", response_class=HTMLResponse)
async def world_overview_page(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """World overview page — cosmology, regions, factions, history, power system."""
    ctx = await _base_context(request, db)

    # Author-only access
    if not ctx["current_author"]:
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

    stats = (
        await db.execute(select(NovelStats).where(NovelStats.novel_id == novel_id))
    ).scalar_one_or_none()
    ctx["novel"] = _novel_view(novel, stats)
    ctx["is_author"] = True

    # Load world data from WorldBuildingStage.parsed_data (the single source
    # of truth — the individual ORM tables like Cosmology/Region are unused).
    stages = (
        await db.execute(
            select(WorldBuildingStage)
            .where(
                WorldBuildingStage.novel_id == novel_id,
                WorldBuildingStage.status == "complete",
            )
            .order_by(WorldBuildingStage.stage_order.asc())
        )
    ).scalars().all()

    stage_map: dict[str, dict] = {s.stage_name: (s.parsed_data or {}) for s in stages}

    ctx["cosmology"] = stage_map.get("cosmology")
    ctx["power_system"] = stage_map.get("power_system")
    ctx["regions"] = stage_map.get("geography", {}).get("regions", [])
    ctx["factions"] = stage_map.get("geography", {}).get("factions", [])
    ctx["political_entities"] = stage_map.get("geography", {}).get("political_entities", [])
    ctx["history_events"] = stage_map.get("history", {}).get("events", [])
    ctx["history_eras"] = stage_map.get("history", {}).get("eras", [])
    ctx["history_figures"] = stage_map.get("history", {}).get("key_figures", [])
    ctx["current_state"] = stage_map.get("current_state")
    ctx["protagonist"] = stage_map.get("protagonist")
    ctx["antagonists"] = stage_map.get("antagonists")
    ctx["supporting_cast"] = stage_map.get("supporting_cast")

    ctx["has_world"] = len(stages) > 0

    return _templates(request).TemplateResponse("pages/world_overview.html", ctx)


@router.get(
    "/novels/{novel_id}/world/power-system",
    response_class=HTMLResponse,
)
async def power_system_page(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Power system visualization page — ranks, mechanics, disciplines."""
    ctx = await _base_context(request, db)

    # Author-only access
    if not ctx["current_author"]:
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

    stats = (
        await db.execute(select(NovelStats).where(NovelStats.novel_id == novel_id))
    ).scalar_one_or_none()
    ctx["novel"] = _novel_view(novel, stats)
    ctx["is_author"] = True

    # Power system — try WorldBuildingStage.parsed_data first (populated
    # during world generation), fall back to PowerSystem ORM table (populated
    # by chapter extraction).
    from sqlalchemy.orm import selectinload

    ps = None
    stage = (
        await db.execute(
            select(WorldBuildingStage).where(
                WorldBuildingStage.novel_id == novel_id,
                WorldBuildingStage.stage_name == "power_system",
                WorldBuildingStage.status == "complete",
            )
        )
    ).scalar_one_or_none()

    if stage and stage.parsed_data:
        ctx["power_system"] = stage.parsed_data
        raw_ranks = stage.parsed_data.get("ranks", [])
        ctx["ranks"] = sorted(raw_ranks, key=lambda r: r.get("rank_order", 0))
    else:
        # Fall back to relational table
        ps = (
            await db.execute(
                select(PowerSystem)
                .where(PowerSystem.novel_id == novel_id)
                .options(selectinload(PowerSystem.ranks))
            )
        ).scalar_one_or_none()

        if ps is None:
            ctx["power_system"] = None
            ctx["ranks"] = []
        else:
            # Normalize ORM object to dict so template always gets dicts
            ctx["power_system"] = {
                "system_name": ps.system_name,
                "core_mechanic": ps.core_mechanic,
                "energy_source": ps.energy_source,
                "hard_limits": ps.hard_limits or [],
                "soft_limits": ps.soft_limits or [],
                "power_ceiling": ps.power_ceiling or "",
                "advancement_mechanics": ps.advancement_mechanics or {},
                "disciplines": [],
            }
            ctx["ranks"] = [
                {
                    "rank_order": r.rank_order,
                    "rank_name": r.rank_name,
                    "description": r.description,
                    "typical_capabilities": r.typical_capabilities,
                    "qualitative_shift": r.qualitative_shift,
                    "advancement_requirements": r.advancement_requirements,
                    "advancement_bottleneck": r.advancement_bottleneck,
                    "population_ratio": r.population_ratio,
                }
                for r in sorted(ps.ranks, key=lambda r: r.rank_order)
            ]

    ctx["powered_characters"] = []

    return _templates(request).TemplateResponse("pages/power_system_detail.html", ctx)
