"""World building routes: overview, regions, history, power system."""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aiwebnovel.db.models import (
    Cosmology,
    HistoricalEvent,
    PowerSystem,
    Region,
)
from aiwebnovel.db.schemas import PowerRankRead, PowerSystemRead
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────


class WorldOverviewResponse(BaseModel):
    novel_id: int
    cosmology: Optional[dict[str, Any]] = None
    region_count: int
    power_system_name: Optional[str] = None
    has_world: bool


class RegionRead(BaseModel):
    id: int
    novel_id: int
    name: str
    description: str
    geography_type: Optional[str] = None
    parent_region_id: Optional[int] = None
    climate: Optional[str] = None
    notable_features: Optional[list[Any]] = None
    scope_tier: int
    revealed_at_chapter: Optional[int] = None

    class Config:
        from_attributes = True


class HistoricalEventRead(BaseModel):
    id: int
    novel_id: int
    name: str
    description: str
    era: Optional[str] = None
    chronological_order: Optional[int] = None
    impact: Optional[list[Any]] = None
    is_common_knowledge: bool
    scope_tier: int

    class Config:
        from_attributes = True


class PowerSystemDetailResponse(BaseModel):
    power_system: Optional[PowerSystemRead] = None
    ranks: list[PowerRankRead]


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/{novel_id}/world", response_model=WorldOverviewResponse)
async def world_overview(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
) -> WorldOverviewResponse:
    """World overview — cosmology summary, counts."""
    # Get cosmology
    cosmo_stmt = select(Cosmology).where(Cosmology.novel_id == novel_id)
    cosmo_result = await db.execute(cosmo_stmt)
    cosmology = cosmo_result.scalar_one_or_none()

    # Region count
    from sqlalchemy import func

    region_count_stmt = (
        select(func.count(Region.id)).where(Region.novel_id == novel_id)
    )
    region_result = await db.execute(region_count_stmt)
    region_count = region_result.scalar_one()

    # Power system name
    ps_stmt = select(PowerSystem.system_name).where(PowerSystem.novel_id == novel_id)
    ps_result = await db.execute(ps_stmt)
    ps_name = ps_result.scalar_one_or_none()

    cosmo_data = None
    if cosmology:
        cosmo_data = {
            "creation_myth": cosmology.creation_myth,
            "fundamental_forces": cosmology.fundamental_forces,
            "planes_of_existence": cosmology.planes_of_existence,
        }

    has_world = cosmology is not None or region_count > 0

    return WorldOverviewResponse(
        novel_id=novel_id,
        cosmology=cosmo_data,
        region_count=region_count,
        power_system_name=ps_name,
        has_world=has_world,
    )


@router.get("/{novel_id}/world/regions", response_model=list[RegionRead])
async def list_regions(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[RegionRead]:
    """List revealed regions for a novel."""
    stmt = (
        select(Region)
        .where(Region.novel_id == novel_id)
        .order_by(Region.scope_tier.asc(), Region.name.asc())
    )
    result = await db.execute(stmt)
    regions = result.scalars().all()
    return [RegionRead.model_validate(r) for r in regions]


@router.get("/{novel_id}/world/regions/{region_id}", response_model=RegionRead)
async def get_region(
    novel_id: int,
    region_id: int,
    db: AsyncSession = Depends(get_db),
) -> RegionRead:
    """Get region detail."""
    stmt = select(Region).where(Region.id == region_id, Region.novel_id == novel_id)
    result = await db.execute(stmt)
    region = result.scalar_one_or_none()
    if region is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Region not found",
        )
    return RegionRead.model_validate(region)


@router.get("/{novel_id}/world/history", response_model=list[HistoricalEventRead])
async def list_history(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[HistoricalEventRead]:
    """List historical events for a novel."""
    stmt = (
        select(HistoricalEvent)
        .where(HistoricalEvent.novel_id == novel_id)
        .order_by(HistoricalEvent.chronological_order.asc().nulls_last())
    )
    result = await db.execute(stmt)
    events = result.scalars().all()
    return [HistoricalEventRead.model_validate(e) for e in events]


@router.get("/{novel_id}/world/power-system", response_model=PowerSystemDetailResponse)
async def get_power_system(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
) -> PowerSystemDetailResponse:
    """Get power system detail with ranks."""
    stmt = (
        select(PowerSystem)
        .where(PowerSystem.novel_id == novel_id)
        .options(selectinload(PowerSystem.ranks))
    )
    result = await db.execute(stmt)
    ps = result.scalar_one_or_none()

    if ps is None:
        return PowerSystemDetailResponse(power_system=None, ranks=[])

    ranks = sorted(ps.ranks, key=lambda r: r.rank_order)

    return PowerSystemDetailResponse(
        power_system=PowerSystemRead.model_validate(ps),
        ranks=[PowerRankRead.model_validate(r) for r in ranks],
    )
