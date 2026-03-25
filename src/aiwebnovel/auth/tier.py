"""Tier resolution and limit enforcement for free/BYOK/admin authors."""

from __future__ import annotations

from enum import StrEnum

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import AVAILABLE_MODELS, Settings
from aiwebnovel.db.models import AuthorAPIKey, AuthorProfile, Chapter, Novel

logger = structlog.get_logger(__name__)


class AuthorTier(StrEnum):
    FREE = "free"
    BYOK = "byok"
    ADMIN = "admin"


class TierInfo:
    """Resolved tier information for an author."""

    def __init__(
        self,
        tier: AuthorTier,
        max_worlds: int | None,
        max_chapters_per_novel: int | None,
        providers: list[str],
    ) -> None:
        self.tier = tier
        self.max_worlds = max_worlds  # None = unlimited
        self.max_chapters_per_novel = max_chapters_per_novel
        self.providers = providers  # provider names with valid keys


async def resolve_tier(
    session: AsyncSession,
    user_id: int,
    settings: Settings,
) -> TierInfo:
    """Determine the author's effective tier based on plan_type and API keys."""
    profile = (
        await session.execute(
            select(AuthorProfile).where(AuthorProfile.user_id == user_id)
        )
    ).scalar_one_or_none()

    if profile is None:
        return TierInfo(
            tier=AuthorTier.FREE,
            max_worlds=settings.free_tier_max_worlds,
            max_chapters_per_novel=settings.free_tier_max_chapters,
            providers=[],
        )

    # Admin bypasses everything
    if profile.plan_type == "admin":
        return TierInfo(
            tier=AuthorTier.ADMIN,
            max_worlds=None,
            max_chapters_per_novel=None,
            providers=list(AVAILABLE_MODELS.keys()),
        )

    # Check for valid BYOK keys
    valid_keys = (
        await session.execute(
            select(AuthorAPIKey.provider).where(
                AuthorAPIKey.user_id == user_id,
                AuthorAPIKey.is_valid.is_(True),
            )
        )
    ).scalars().all()

    if valid_keys:
        return TierInfo(
            tier=AuthorTier.BYOK,
            max_worlds=None,
            max_chapters_per_novel=None,
            providers=list(valid_keys),
        )

    return TierInfo(
        tier=AuthorTier.FREE,
        max_worlds=settings.free_tier_max_worlds,
        max_chapters_per_novel=settings.free_tier_max_chapters,
        providers=[],
    )


async def check_world_limit(
    session: AsyncSession,
    user_id: int,
    settings: Settings,
) -> tuple[bool, str]:
    """Check if the author can create a new world.

    Returns (allowed, reason).
    """
    tier = await resolve_tier(session, user_id, settings)
    if tier.max_worlds is None:
        return True, ""

    novel_count = (
        await session.execute(
            select(func.count(Novel.id)).where(Novel.author_id == user_id)
        )
    ).scalar_one()

    if novel_count >= tier.max_worlds:
        return False, (
            "Two worlds is all the free slop you get. "
            "The multiverse requires your own API key."
        )
    return True, ""


async def check_chapter_limit(
    session: AsyncSession,
    novel_id: int,
    user_id: int,
    settings: Settings,
) -> tuple[bool, str]:
    """Check if the author can generate another chapter.

    Returns (allowed, reason).
    """
    tier = await resolve_tier(session, user_id, settings)
    if tier.max_chapters_per_novel is None:
        return True, ""

    chapter_count = (
        await session.execute(
            select(func.count(Chapter.id)).where(
                Chapter.novel_id == novel_id
            )
        )
    ).scalar_one()

    if chapter_count >= tier.max_chapters_per_novel:
        return False, (
            "The free slop dispenser caps at 3 chapters. "
            "Bring your own API key for unlimited narrative sludge."
        )
    return True, ""


async def check_lifetime_budget(
    session: AsyncSession,
    user_id: int,
    settings: Settings,
) -> tuple[bool, str]:
    """Check if the free tier user has exceeded their lifetime budget.

    Returns (allowed, reason). Allow-overspend: check is at operation START
    only. If budget passes, let the operation finish even if it exceeds $5.
    """
    tier = await resolve_tier(session, user_id, settings)
    if tier.tier != AuthorTier.FREE:
        return True, ""

    profile = (
        await session.execute(
            select(AuthorProfile).where(AuthorProfile.user_id == user_id)
        )
    ).scalar_one_or_none()

    if profile is None:
        return True, ""

    total_spent = profile.api_spent_cents + profile.image_spent_cents
    if total_spent >= settings.free_tier_lifetime_budget_cents:
        return False, (
            "You've squeezed $5 worth of slop from our servers. "
            "Time to bring your own key."
        )
    return True, ""


async def resolve_model(
    session: AsyncSession,
    user_id: int,
    requested_model: str | None,
    settings: Settings,
) -> str:
    """Resolve the effective model for a generation request.

    FREE: always Haiku, ignores requested_model.
    BYOK: validates requested_model against user's provider keys.
    ADMIN: any model allowed.
    """
    tier = await resolve_tier(session, user_id, settings)

    if tier.tier == AuthorTier.FREE:
        return settings.free_tier_model

    if tier.tier == AuthorTier.ADMIN:
        return requested_model or settings.litellm_default_model

    # BYOK — validate model against available providers
    if not requested_model:
        # Default: use best model from first available provider
        for provider in tier.providers:
            models = AVAILABLE_MODELS.get(provider, [])
            if models:
                return models[0]["id"]
        return settings.free_tier_model  # fallback

    # Validate the requested model's provider has a key
    model_provider = requested_model.split("/")[0] if "/" in requested_model else None
    if model_provider and model_provider in tier.providers:
        return requested_model

    # Model doesn't match any available provider
    logger.warning(
        "model_provider_mismatch",
        requested=requested_model,
        available=tier.providers,
    )
    return settings.free_tier_model


def get_allowed_models(tier_info: TierInfo) -> list[dict[str, str]]:
    """Get the list of models available to this author."""
    if tier_info.tier == AuthorTier.FREE:
        return [{"id": "anthropic/claude-haiku-4-5-20251001", "name": "Haiku 4.5 (free tier)"}]

    if tier_info.tier == AuthorTier.ADMIN:
        return [m for models in AVAILABLE_MODELS.values() for m in models]

    # BYOK — models matching configured providers
    result = []
    for provider in tier_info.providers:
        result.extend(AVAILABLE_MODELS.get(provider, []))
    return result or [{"id": "anthropic/claude-haiku-4-5-20251001", "name": "Haiku 4.5 (fallback)"}]
