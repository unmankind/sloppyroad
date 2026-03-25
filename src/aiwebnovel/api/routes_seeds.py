"""Seed preview, reroll, and confirm API routes."""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import require_novel_owner
from aiwebnovel.db.models import NovelSeed, NovelTag
from aiwebnovel.db.schemas import NovelSeedRead
from aiwebnovel.db.session import get_db
from aiwebnovel.story.seeds import SEED_BANK, select_seeds

logger = structlog.get_logger(__name__)

router = APIRouter()


class RerollAllRequest(BaseModel):
    locked_seed_ids: list[int] = Field(default_factory=list)


@router.get("/{novel_id}/seeds", response_model=list[NovelSeedRead])
async def list_seeds(
    novel_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[NovelSeedRead]:
    """List current seeds for a novel (any status)."""
    stmt = select(NovelSeed).where(NovelSeed.novel_id == novel_id)
    result = await db.execute(stmt)
    seeds = result.scalars().all()
    return [NovelSeedRead.model_validate(s) for s in seeds]


@router.post("/{novel_id}/seeds/reroll/{seed_id}")
async def reroll_seed(
    novel_id: int,
    seed_id: int,
    request: Request,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
):
    """Reroll a single seed, replacing it with a new one from the same category.

    Returns HTML partial if called via HTMX, otherwise JSON.
    """
    old_seed = (await db.execute(
        select(NovelSeed).where(
            NovelSeed.id == seed_id,
            NovelSeed.novel_id == novel_id,
        )
    )).scalar_one_or_none()

    if old_seed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seed not found",
        )

    # Get novel's tags for weighted selection
    tag_result = await db.execute(
        select(NovelTag.tag_name).where(NovelTag.novel_id == novel_id)
    )
    author_tags = [row[0] for row in tag_result.all()]

    # Select a replacement from the same category, excluding the current seed
    category = old_seed.seed_category
    new_seeds = select_seeds(
        author_tags=author_tags,
        num_seeds=1,
        exclude_seeds={old_seed.seed_id},
    )
    # Filter to same category
    new_seed_data = next((s for s in new_seeds if s.category == category), None)

    # Fallback: pick directly from the category bank if select_seeds didn't return one
    if new_seed_data is None:
        import random

        tag_set = set(author_tags)
        candidates = [
            s for s in SEED_BANK.get(category, [])
            if s.id != old_seed.seed_id and not (tag_set & s.incompatible_tags)
        ]
        if candidates:
            new_seed_data = random.choice(candidates)

    if new_seed_data is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No alternative seeds available for this category",
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

    logger.info("seed_rerolled", novel_id=novel_id, old=old_seed.seed_id, new=new_seed_data.id)

    # Return HTML partial for HTMX, JSON otherwise
    if request.headers.get("hx-request"):
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "partials/seed_card.html",
            {
                "request": request,
                "seed": novel_seed,
                "novel_id": novel_id,
                "locked": False,
            },
        )
    return NovelSeedRead.model_validate(novel_seed)


@router.post("/{novel_id}/seeds/reroll-all", response_model=list[NovelSeedRead])
async def reroll_all_seeds(
    novel_id: int,
    body: Optional[RerollAllRequest] = None,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[NovelSeedRead]:
    """Reroll all proposed seeds, optionally locking some in place."""
    locked_ids = set(body.locked_seed_ids) if body else set()

    # Get all proposed seeds
    proposed_result = await db.execute(
        select(NovelSeed).where(
            NovelSeed.novel_id == novel_id,
            NovelSeed.status == "proposed",
        )
    )
    proposed_seeds = proposed_result.scalars().all()

    to_replace = [s for s in proposed_seeds if s.id not in locked_ids]
    kept = [s for s in proposed_seeds if s.id in locked_ids]

    if not to_replace:
        # Nothing to reroll — return current seeds
        all_result = await db.execute(
            select(NovelSeed).where(NovelSeed.novel_id == novel_id)
        )
        return [NovelSeedRead.model_validate(s) for s in all_result.scalars().all()]

    # Collect seed_ids to exclude (locked seeds + non-proposed seeds)
    all_seeds_result = await db.execute(
        select(NovelSeed.seed_id).where(NovelSeed.novel_id == novel_id)
    )
    all_existing_seed_ids = {row[0] for row in all_seeds_result.all()}
    # Exclude locked seeds and any confirmed/rejected seeds, but allow reuse of seeds being replaced
    replace_seed_ids = {s.seed_id for s in to_replace}
    exclude = all_existing_seed_ids - replace_seed_ids

    # Get novel's tags
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
        novel_seed = NovelSeed(
            novel_id=novel_id,
            seed_id=seed_data.id,
            seed_category=seed_data.category,
            seed_text=seed_data.text,
            status="proposed",
        )
        db.add(novel_seed)

    await db.flush()

    logger.info("seeds_rerolled_all", novel_id=novel_id, replaced=len(to_replace), locked=len(kept))

    # Return full list
    final_result = await db.execute(
        select(NovelSeed).where(NovelSeed.novel_id == novel_id)
    )
    return [NovelSeedRead.model_validate(s) for s in final_result.scalars().all()]


@router.delete("/{novel_id}/seeds/{seed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reject_seed(
    novel_id: int,
    seed_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Reject a seed (soft-delete by setting status to 'rejected')."""
    seed = (await db.execute(
        select(NovelSeed).where(
            NovelSeed.id == seed_id,
            NovelSeed.novel_id == novel_id,
        )
    )).scalar_one_or_none()

    if seed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seed not found",
        )

    seed.status = "rejected"
    await db.flush()
    logger.info("seed_rejected", novel_id=novel_id, seed_id=seed.seed_id)


@router.post("/{novel_id}/seeds/confirm", response_model=list[NovelSeedRead])
async def confirm_seeds(
    novel_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[NovelSeedRead]:
    """Confirm all proposed seeds for a novel."""
    result = await db.execute(
        select(NovelSeed).where(
            NovelSeed.novel_id == novel_id,
            NovelSeed.status == "proposed",
        )
    )
    seeds = result.scalars().all()

    if not seeds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No proposed seeds to confirm",
        )

    for seed in seeds:
        seed.status = "confirmed"

    await db.flush()

    logger.info("seeds_confirmed", novel_id=novel_id, count=len(seeds))
    return [NovelSeedRead.model_validate(s) for s in seeds]
