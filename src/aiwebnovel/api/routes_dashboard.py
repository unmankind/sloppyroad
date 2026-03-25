"""Author dashboard routes: novel list, usage stats, profile settings."""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import require_author
from aiwebnovel.db.models import AuthorProfile, LLMUsageLog, Novel
from aiwebnovel.db.schemas import AuthorProfileRead, NovelList
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────


class DashboardResponse(BaseModel):
    novels: list[NovelList]
    total_spent_cents: float
    budget_cents: int
    novel_count: int
    image_spent_cents: int = 0
    image_budget_cents: int = 0


class UsageResponse(BaseModel):
    total_llm_cost_cents: float
    total_calls: int
    by_purpose: dict[str, Any]


class AuthorSettingsUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=200)
    bio: Optional[str] = Field(None, max_length=2000)


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/", response_model=DashboardResponse)
async def dashboard(
    user: dict = Depends(require_author),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    """Author dashboard: novels list and spending summary."""
    user_id = user["user_id"]

    # Get novels
    stmt = (
        select(Novel)
        .where(Novel.author_id == user_id)
        .order_by(Novel.updated_at.desc())
    )
    result = await db.execute(stmt)
    novels = result.scalars().all()

    # Get author profile for budget
    profile_stmt = select(AuthorProfile).where(AuthorProfile.user_id == user_id)
    profile_result = await db.execute(profile_stmt)
    profile = profile_result.scalar_one_or_none()

    # Total spending
    spent_stmt = (
        select(func.coalesce(func.sum(LLMUsageLog.cost_cents), 0.0))
        .where(LLMUsageLog.user_id == user_id)
    )
    spent_result = await db.execute(spent_stmt)
    total_spent = spent_result.scalar_one()

    return DashboardResponse(
        novels=[NovelList.model_validate(n) for n in novels],
        total_spent_cents=float(total_spent),
        budget_cents=profile.api_budget_cents if profile else 0,
        novel_count=len(novels),
        image_spent_cents=profile.image_spent_cents if profile else 0,
        image_budget_cents=profile.image_budget_cents if profile else 0,
    )


@router.get("/usage", response_model=UsageResponse)
async def usage(
    user: dict = Depends(require_author),
    db: AsyncSession = Depends(get_db),
) -> UsageResponse:
    """Detailed cost breakdown by purpose."""
    user_id = user["user_id"]

    # Total
    total_stmt = (
        select(
            func.coalesce(func.sum(LLMUsageLog.cost_cents), 0.0),
            func.count(LLMUsageLog.id),
        )
        .where(LLMUsageLog.user_id == user_id)
    )
    total_result = await db.execute(total_stmt)
    row = total_result.one()
    total_cost = float(row[0])
    total_calls = int(row[1])

    # By purpose
    purpose_stmt = (
        select(
            LLMUsageLog.purpose,
            func.sum(LLMUsageLog.cost_cents),
            func.count(LLMUsageLog.id),
        )
        .where(LLMUsageLog.user_id == user_id)
        .group_by(LLMUsageLog.purpose)
    )
    purpose_result = await db.execute(purpose_stmt)
    by_purpose = {
        row[0]: {"cost_cents": float(row[1]), "count": int(row[2])}
        for row in purpose_result.all()
    }

    return UsageResponse(
        total_llm_cost_cents=total_cost,
        total_calls=total_calls,
        by_purpose=by_purpose,
    )


@router.get("/settings", response_model=AuthorProfileRead)
async def get_settings(
    user: dict = Depends(require_author),
    db: AsyncSession = Depends(get_db),
) -> AuthorProfileRead:
    """Get author profile settings."""
    stmt = select(AuthorProfile).where(AuthorProfile.user_id == user["user_id"])
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author profile not found",
        )
    return AuthorProfileRead.model_validate(profile)


@router.put("/settings", response_model=AuthorProfileRead)
async def update_settings(
    body: AuthorSettingsUpdate,
    user: dict = Depends(require_author),
    db: AsyncSession = Depends(get_db),
) -> AuthorProfileRead:
    """Update author profile settings."""
    stmt = select(AuthorProfile).where(AuthorProfile.user_id == user["user_id"])
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author profile not found",
        )

    if body.display_name is not None:
        profile.display_name = body.display_name
    if body.bio is not None:
        profile.bio = body.bio

    await db.flush()
    logger.info("author_settings_updated", user_id=user["user_id"])

    return AuthorProfileRead.model_validate(profile)
