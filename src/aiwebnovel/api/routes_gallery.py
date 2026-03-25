"""Gallery API routes: art asset listing, detail, and regeneration for novels."""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import require_novel_owner
from aiwebnovel.db.models import ArtAsset, ArtGenerationQueue, ChapterImage
from aiwebnovel.db.schemas import ArtAssetRead
from aiwebnovel.db.session import get_db
from aiwebnovel.images.budget import check_image_budget
from aiwebnovel.worker.tasks import enqueue_art_generation

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/{novel_id}/gallery",
    response_model=list[ArtAssetRead],
)
async def list_gallery_assets(
    novel_id: int,
    asset_type: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    current_only: bool = Query(False),
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[ArtAssetRead]:
    """List all art assets for a novel, optionally filtered."""
    stmt = (
        select(ArtAsset)
        .where(ArtAsset.novel_id == novel_id)
        .order_by(ArtAsset.asset_type.asc(), ArtAsset.created_at.desc())
    )
    if asset_type:
        stmt = stmt.where(ArtAsset.asset_type == asset_type)
    if entity_type:
        stmt = stmt.where(ArtAsset.entity_type == entity_type)
    if current_only:
        stmt = stmt.where(ArtAsset.is_current.is_(True))

    assets = (await db.execute(stmt)).scalars().all()
    return [ArtAssetRead.model_validate(a) for a in assets]


@router.get(
    "/{novel_id}/gallery/{asset_id}",
    response_model=ArtAssetRead,
)
async def get_gallery_asset(
    novel_id: int,
    asset_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> ArtAssetRead:
    """Get a single art asset by ID."""
    stmt = select(ArtAsset).where(
        ArtAsset.id == asset_id,
        ArtAsset.novel_id == novel_id,
    )
    asset = (await db.execute(stmt)).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return ArtAssetRead.model_validate(asset)


@router.get(
    "/{novel_id}/gallery/{asset_id}/evolution",
    response_model=list[ArtAssetRead],
)
async def get_asset_evolution_chain(
    novel_id: int,
    asset_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[ArtAssetRead]:
    """Get the full evolution chain for an asset (all versions)."""
    # Find the root of the chain by walking up parent_asset_id
    current = (
        await db.execute(
            select(ArtAsset).where(
                ArtAsset.id == asset_id, ArtAsset.novel_id == novel_id,
            )
        )
    ).scalar_one_or_none()
    if current is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Walk up to root
    root = current
    visited = {root.id}
    while root.parent_asset_id is not None:
        parent = (
            await db.execute(
                select(ArtAsset).where(ArtAsset.id == root.parent_asset_id)
            )
        ).scalar_one_or_none()
        if parent is None or parent.id in visited:
            break
        visited.add(parent.id)
        root = parent

    # Walk down from root collecting the chain
    chain = [root]
    current_id = root.id
    for _ in range(50):  # safety limit
        child = (
            await db.execute(
                select(ArtAsset).where(
                    ArtAsset.parent_asset_id == current_id,
                    ArtAsset.novel_id == novel_id,
                )
            )
        ).scalar_one_or_none()
        if child is None:
            break
        chain.append(child)
        current_id = child.id

    return [ArtAssetRead.model_validate(a) for a in chain]


@router.post(
    "/{novel_id}/gallery/retry/{queue_id}",
)
async def retry_failed_image(
    novel_id: int,
    queue_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Retry a failed image generation by resetting its queue entry to pending."""
    stmt = select(ArtGenerationQueue).where(
        ArtGenerationQueue.id == queue_id,
        ArtGenerationQueue.novel_id == novel_id,
        ArtGenerationQueue.status == "failed",
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Failed queue entry not found")

    item.status = "pending"
    item.error_message = None

    # If this was a scene/chapter_image, also reset the ChapterImage status
    if item.asset_type == "scene" and item.entity_type == "chapter_image" and item.entity_id:
        ci_stmt = select(ChapterImage).where(ChapterImage.id == item.entity_id)
        ci = (await db.execute(ci_stmt)).scalar_one_or_none()
        if ci:
            ci.status = "pending"
            ci.error_message = None

    await db.commit()

    logger.info(
        "image_retry_requested",
        queue_id=queue_id,
        novel_id=novel_id,
        asset_type=item.asset_type,
    )
    return {"status": "queued", "queue_id": queue_id}


@router.post(
    "/{novel_id}/gallery/{asset_id}/regenerate",
)
async def regenerate_image(
    novel_id: int,
    asset_id: int,
    feedback: str = Form(...),
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Queue image regeneration with author feedback."""
    # Validate feedback
    feedback = feedback.strip()
    if not feedback:
        raise HTTPException(status_code=422, detail="Feedback cannot be empty")
    if len(feedback) > 500:
        raise HTTPException(status_code=422, detail="Feedback must be 500 characters or less")

    # Validate asset belongs to novel
    stmt = select(ArtAsset).where(
        ArtAsset.id == asset_id,
        ArtAsset.novel_id == novel_id,
    )
    asset = (await db.execute(stmt)).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Check image budget
    budget = await check_image_budget(db, novel_id)
    if not budget.allowed:
        raise HTTPException(status_code=429, detail=f"Image budget exceeded: {budget.reason}")

    # Enqueue regeneration
    queue_id = await enqueue_art_generation(
        session=db,
        novel_id=novel_id,
        asset_type=asset.asset_type,
        entity_id=asset.entity_id,
        entity_type=asset.entity_type,
        source_asset_id=asset_id,
        feedback=feedback,
        trigger_event="manual_regenerate",
        priority=2,
    )
    await db.commit()

    logger.info(
        "image_regeneration_requested",
        novel_id=novel_id,
        asset_id=asset_id,
        queue_id=queue_id,
    )
    return {"status": "queued", "queue_id": queue_id}
