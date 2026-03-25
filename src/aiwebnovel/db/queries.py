"""Common async query helpers used across the application.

Every function accepts an ``AsyncSession`` as its first argument
so callers (routes, pipeline stages, workers) can pass in the
session they already hold.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aiwebnovel.db.models import (
    ArcPlan,
    Chapter,
    Character,
    ChekhovGun,
    EscalationState,
    Faction,
    ForeshadowingSeed,
    Novel,
    PlotThread,
    PowerSystem,
    Region,
    ScopeTier,
    TensionTracker,
    WorldBuildingStage,
)

# ---------------------------------------------------------------------------
# Novel helpers
# ---------------------------------------------------------------------------


async def get_novel_with_status(
    session: AsyncSession,
    novel_id: int,
) -> Novel | None:
    """Load a novel with its settings, stats, and access record."""
    stmt = (
        select(Novel)
        .where(Novel.id == novel_id)
        .options(
            selectinload(Novel.settings),
            selectinload(Novel.novel_stats),
            selectinload(Novel.novel_access),
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_novel_full(
    session: AsyncSession,
    novel_id: int,
) -> Novel | None:
    """Load a novel with most key relationships eagerly loaded."""
    stmt = (
        select(Novel)
        .where(Novel.id == novel_id)
        .options(
            selectinload(Novel.settings),
            selectinload(Novel.power_system),
            selectinload(Novel.cosmology),
            selectinload(Novel.novel_stats),
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Chapter context (for generation pipeline)
# ---------------------------------------------------------------------------


async def get_chapter_context(
    session: AsyncSession,
    novel_id: int,
    chapter_number: int,
) -> dict[str, Any]:
    """Assemble the raw data needed for chapter generation.

    Returns a dict with keys:
        revealed_regions, active_characters, power_system,
        current_escalation, recent_chapters
    """
    # Regions revealed up to this chapter
    regions_stmt = (
        select(Region)
        .where(
            Region.novel_id == novel_id,
            (Region.revealed_at_chapter.is_(None))
            | (Region.revealed_at_chapter <= chapter_number),
        )
    )
    regions_result = await session.execute(regions_stmt)
    revealed_regions: Sequence[Region] = regions_result.scalars().all()

    # Active characters introduced before this chapter
    chars_stmt = (
        select(Character)
        .where(
            Character.novel_id == novel_id,
            Character.is_alive.is_(True),
            (Character.introduced_at_chapter.is_(None))
            | (Character.introduced_at_chapter <= chapter_number),
        )
    )
    chars_result = await session.execute(chars_stmt)
    active_characters: Sequence[Character] = chars_result.scalars().all()

    # Power system (always available)
    ps_stmt = select(PowerSystem).where(PowerSystem.novel_id == novel_id)
    ps_result = await session.execute(ps_stmt)
    power_system: PowerSystem | None = ps_result.scalar_one_or_none()

    # Latest escalation state
    esc_stmt = (
        select(EscalationState)
        .where(EscalationState.novel_id == novel_id)
        .order_by(EscalationState.activated_at_chapter.desc())
        .limit(1)
    )
    esc_result = await session.execute(esc_stmt)
    current_escalation: EscalationState | None = esc_result.scalar_one_or_none()

    # Recent chapters
    ch_stmt = (
        select(Chapter)
        .where(Chapter.novel_id == novel_id, Chapter.chapter_number < chapter_number)
        .order_by(Chapter.chapter_number.desc())
        .limit(5)
    )
    ch_result = await session.execute(ch_stmt)
    recent_chapters: Sequence[Chapter] = ch_result.scalars().all()

    # World building stages (all completed)
    wbs_stmt = (
        select(WorldBuildingStage)
        .where(
            WorldBuildingStage.novel_id == novel_id,
            WorldBuildingStage.status == "complete",
        )
        .order_by(WorldBuildingStage.stage_order.asc())
    )
    wbs_result = await session.execute(wbs_stmt)
    world_stages: Sequence[WorldBuildingStage] = wbs_result.scalars().all()

    # Factions
    factions_stmt = select(Faction).where(Faction.novel_id == novel_id)
    factions_result = await session.execute(factions_stmt)
    factions: Sequence[Faction] = factions_result.scalars().all()

    return {
        "revealed_regions": list(revealed_regions),
        "active_characters": list(active_characters),
        "power_system": power_system,
        "current_escalation": current_escalation,
        "recent_chapters": list(recent_chapters),
        "world_stages": list(world_stages),
        "factions": list(factions),
    }


# ---------------------------------------------------------------------------
# Cross-novel name exclusion
# ---------------------------------------------------------------------------


async def get_other_novel_character_names(
    session: AsyncSession,
    author_id: int,
    novel_id: int,
) -> list[str]:
    """Get protagonist/major character names from author's OTHER novels.

    Used to prevent the same names (e.g. "Kael") appearing in every novel.
    """
    other_novels_stmt = select(Novel.id).where(
        Novel.author_id == author_id,
        Novel.id != novel_id,
    )
    chars_stmt = (
        select(Character.name)
        .where(
            Character.novel_id.in_(other_novels_stmt),
            Character.role.in_(["protagonist", "antagonist", "mentor", "ally"]),
        )
        .distinct()
    )
    result = await session.execute(chars_stmt)
    return [row[0] for row in result.all()]


# ---------------------------------------------------------------------------
# Character helpers
# ---------------------------------------------------------------------------


async def get_character_full(
    session: AsyncSession,
    character_id: int,
) -> Character | None:
    """Load a character with power profile, abilities, worldview, and voice."""
    stmt = (
        select(Character)
        .where(Character.id == character_id)
        .options(
            selectinload(Character.power_profile),
            selectinload(Character.abilities),
            selectinload(Character.worldview),
            selectinload(Character.narrative_voice),
            selectinload(Character.knowledge),
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_characters_for_novel(
    session: AsyncSession,
    novel_id: int,
    *,
    alive_only: bool = True,
) -> Sequence[Character]:
    """List characters for a novel, optionally filtered to living ones."""
    stmt = select(Character).where(Character.novel_id == novel_id)
    if alive_only:
        stmt = stmt.where(Character.is_alive.is_(True))
    stmt = stmt.order_by(Character.introduced_at_chapter.asc().nulls_first())
    result = await session.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Foreshadowing / Chekhov
# ---------------------------------------------------------------------------


async def get_active_foreshadowing(
    session: AsyncSession,
    novel_id: int,
) -> Sequence[ForeshadowingSeed]:
    """Return all planted / reinforced foreshadowing seeds for a novel."""
    stmt = (
        select(ForeshadowingSeed)
        .where(
            ForeshadowingSeed.novel_id == novel_id,
            ForeshadowingSeed.status.in_(["planted", "reinforced"]),
        )
        .order_by(ForeshadowingSeed.planted_at_chapter.asc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_active_chekhov_guns(
    session: AsyncSession,
    novel_id: int,
) -> Sequence[ChekhovGun]:
    """Return active / reinforced Chekhov guns ordered by pressure."""
    stmt = (
        select(ChekhovGun)
        .where(
            ChekhovGun.novel_id == novel_id,
            ChekhovGun.status.in_(["loaded", "cocked", "active", "reinforced"]),
        )
        .order_by(ChekhovGun.pressure_score.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


async def get_escalation_state(
    session: AsyncSession,
    novel_id: int,
) -> dict[str, Any]:
    """Return the current escalation state with scope tier details."""
    esc_stmt = (
        select(EscalationState)
        .where(EscalationState.novel_id == novel_id)
        .order_by(EscalationState.id.desc())
        .limit(1)
        .options(selectinload(EscalationState.scope_tier))
    )
    esc_result = await session.execute(esc_stmt)
    state = esc_result.scalar_one_or_none()

    if state is None:
        return {"state": None, "scope_tier": None}

    return {
        "state": state,
        "scope_tier": state.scope_tier,
    }


async def get_scope_tiers(
    session: AsyncSession,
    novel_id: int,
) -> Sequence[ScopeTier]:
    """Return all scope tiers for a novel in order."""
    stmt = (
        select(ScopeTier)
        .where(ScopeTier.novel_id == novel_id)
        .order_by(ScopeTier.tier_order.asc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


async def get_current_arc(
    session: AsyncSession,
    novel_id: int,
) -> ArcPlan | None:
    """Return the current active arc plan for a novel."""
    stmt = (
        select(ArcPlan)
        .where(
            ArcPlan.novel_id == novel_id,
            ArcPlan.status.in_(["in_progress", "approved"]),
        )
        .order_by(ArcPlan.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_plot_threads(
    session: AsyncSession,
    novel_id: int,
) -> Sequence[PlotThread]:
    """Return active and dormant plot threads ordered by priority."""
    stmt = (
        select(PlotThread)
        .where(
            PlotThread.novel_id == novel_id,
            PlotThread.status.in_(["active", "dormant"]),
        )
        .order_by(PlotThread.priority.asc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# World building
# ---------------------------------------------------------------------------


async def get_world_stages(
    session: AsyncSession,
    novel_id: int,
) -> Sequence[WorldBuildingStage]:
    """Return all world building stages for a novel in order."""
    stmt = (
        select(WorldBuildingStage)
        .where(WorldBuildingStage.novel_id == novel_id)
        .order_by(WorldBuildingStage.stage_order.asc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Tension
# ---------------------------------------------------------------------------


async def get_recent_tension(
    session: AsyncSession,
    novel_id: int,
    limit: int = 5,
) -> Sequence[TensionTracker]:
    """Return the most recent tension tracker entries."""
    stmt = (
        select(TensionTracker)
        .where(TensionTracker.novel_id == novel_id)
        .order_by(TensionTracker.chapter_number.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------


async def paginate(
    session: AsyncSession,
    stmt: Any,
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Apply OFFSET/LIMIT pagination to a select statement.

    Returns::

        {
            "items": [...],
            "page": 1,
            "page_size": 20,
            "total": 42,
        }
    """
    # Count total
    from sqlalchemy import select as sa_select

    count_stmt = sa_select(func.count()).select_from(stmt.subquery())
    count_result = await session.execute(count_stmt)
    total = count_result.scalar_one()

    # Fetch page
    offset = (page - 1) * page_size
    page_stmt = stmt.offset(offset).limit(page_size)
    result = await session.execute(page_stmt)
    items = result.scalars().all()

    return {
        "items": list(items),
        "page": page,
        "page_size": page_size,
        "total": total,
    }


async def get_chapters_paginated(
    session: AsyncSession,
    novel_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Paginated chapter listing for a novel."""
    stmt = (
        select(Chapter)
        .where(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_number.asc())
    )
    return await paginate(session, stmt, page=page, page_size=page_size)
