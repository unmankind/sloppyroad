"""Chekhov's Gun dashboard routes (author only)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import require_novel_owner
from aiwebnovel.db.models import ChekhovGun
from aiwebnovel.db.schemas import ChekhovGunRead
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/{novel_id}/chekhov", response_model=list[ChekhovGunRead])
async def chekhov_dashboard(
    novel_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[ChekhovGunRead]:
    """Chekhov dashboard — all guns with pressure scores, status, lifecycle."""
    stmt = (
        select(ChekhovGun)
        .where(ChekhovGun.novel_id == novel_id)
        .order_by(ChekhovGun.pressure_score.desc())
    )
    result = await db.execute(stmt)
    guns = result.scalars().all()
    return [ChekhovGunRead.model_validate(g) for g in guns]
