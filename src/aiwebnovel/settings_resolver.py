"""Consolidated settings resolution across Global, AuthorProfile, and NovelSettings.

Single entry point: resolve_effective_settings(session, novel_id, user_id)
returns an EffectiveSettings dataclass merging all three levels with proper
fallback chains.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import AuthorProfile, NovelSettings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EffectiveSettings:
    """Merged settings from global config, author profile, and novel settings."""

    # Model selection
    model: str
    analysis_model: str | None
    temperature: float

    # Image generation
    image_generation_enabled: bool
    art_style_preset: str | None

    # Planning
    planning_mode: str
    target_chapter_length: int
    target_chapter_length_min: int
    target_chapter_length_max: int

    # Autonomous
    autonomous_enabled: bool
    autonomous_cadence_hours: int
    autonomous_daily_budget_cents: int

    # Content
    custom_conventions: str | None
    content_rating: str
    pov_mode: str


async def resolve_effective_settings(
    session: AsyncSession,
    novel_id: int,
    user_id: int,
    global_settings: Settings,
) -> EffectiveSettings:
    """Resolve merged settings for a novel, falling back through layers.

    Priority: NovelSettings > AuthorProfile > Global Settings
    """
    # Fetch both in a single round-trip pattern
    profile = (
        await session.execute(
            select(AuthorProfile).where(AuthorProfile.user_id == user_id)
        )
    ).scalar_one_or_none()

    ns = (
        await session.execute(
            select(NovelSettings).where(NovelSettings.novel_id == novel_id)
        )
    ).scalar_one_or_none()

    # Model: NovelSettings.generation_model > AuthorProfile.default_model > global default
    model = (
        (ns.generation_model if ns and ns.generation_model else None)
        or (profile.default_model if profile and profile.default_model else None)
        or global_settings.litellm_default_model
    )

    analysis_model = ns.analysis_model if ns and ns.analysis_model else None

    # Temperature: novel > global default
    temperature = ns.default_temperature if ns else 0.7

    # Image: novel > author default > False
    image_enabled = (
        ns.image_generation_enabled
        if ns is not None
        else (
            profile.default_image_generation_enabled
            if profile is not None
            else False
        )
    )

    art_style = ns.art_style_preset if ns else None

    # Planning
    planning_mode = ns.planning_mode if ns else "supervised"
    target_len = ns.target_chapter_length if ns else 5000
    target_min = ns.target_chapter_length_min if ns else 3000
    target_max = ns.target_chapter_length_max if ns else 5000

    # Autonomous
    auto_enabled = ns.autonomous_generation_enabled if ns else False
    auto_cadence = ns.autonomous_cadence_hours if ns else 24
    auto_budget = (
        ns.autonomous_daily_budget_cents
        if ns
        else global_settings.autonomous_daily_budget_cents
    )

    # Content
    custom = ns.custom_genre_conventions if ns else None
    rating = ns.content_rating if ns else "teen"
    pov = ns.pov_mode if ns else "single"

    return EffectiveSettings(
        model=model,
        analysis_model=analysis_model,
        temperature=temperature,
        image_generation_enabled=image_enabled,
        art_style_preset=art_style,
        planning_mode=planning_mode,
        target_chapter_length=target_len,
        target_chapter_length_min=target_min,
        target_chapter_length_max=target_max,
        autonomous_enabled=auto_enabled,
        autonomous_cadence_hours=auto_cadence,
        autonomous_daily_budget_cents=auto_budget,
        custom_conventions=custom,
        content_rating=rating,
        pov_mode=pov,
    )
