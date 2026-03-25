"""Character page routes: gallery and detail."""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    ArtAsset,
    Character,
    CharacterPowerProfile,
    CharacterRelationship,
    Faction,
    Novel,
    NovelStats,
    PowerRank,
    Region,
)
from aiwebnovel.db.session import get_db

from .helpers import _base_context, _novel_view, _templates

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/novels/{novel_id}/characters", response_class=HTMLResponse)
async def character_gallery_page(
    novel_id: int,
    request: Request,
    role: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Character gallery page — bestiary-style grid of all characters."""
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

    # All characters (optionally filtered by role)
    chars_stmt = (
        select(Character)
        .where(Character.novel_id == novel_id)
        .order_by(Character.introduced_at_chapter.asc().nulls_first())
    )
    if role:
        chars_stmt = chars_stmt.where(Character.role == role)
    characters = (await db.execute(chars_stmt)).scalars().all()

    # Batch-fetch related data to avoid N+1 queries
    char_ids = [c.id for c in characters]

    # Power profiles + ranks in one query
    pp_stmt = (
        select(CharacterPowerProfile, PowerRank)
        .outerjoin(PowerRank, PowerRank.id == CharacterPowerProfile.current_rank_id)
        .where(CharacterPowerProfile.character_id.in_(char_ids))
    ) if char_ids else None
    rank_by_char: dict[int, str | None] = {}
    if pp_stmt is not None:
        for profile, rank in (await db.execute(pp_stmt)).all():
            rank_by_char[profile.character_id] = rank.rank_name if rank else None

    # Relationship counts in one query
    rel_counts: dict[int, int] = {}
    if char_ids:
        rel_stmt = (
            select(
                CharacterRelationship.character_a_id,
                CharacterRelationship.character_b_id,
            )
            .where(
                or_(
                    CharacterRelationship.character_a_id.in_(char_ids),
                    CharacterRelationship.character_b_id.in_(char_ids),
                )
            )
        )
        for a_id, b_id in (await db.execute(rel_stmt)).all():
            if a_id in char_ids:
                rel_counts[a_id] = rel_counts.get(a_id, 0) + 1
            if b_id in char_ids:
                rel_counts[b_id] = rel_counts.get(b_id, 0) + 1

    # Portraits in one query (latest per character)
    portrait_map: dict[int, str] = {}
    if char_ids:
        port_stmt = (
            select(ArtAsset.entity_id, ArtAsset.file_path)
            .where(
                ArtAsset.entity_id.in_(char_ids),
                ArtAsset.entity_type == "character",
                ArtAsset.asset_type == "portrait",
                ArtAsset.file_path.isnot(None),
            )
            .order_by(ArtAsset.created_at.desc())
        )
        for entity_id, file_path in (await db.execute(port_stmt)).all():
            if entity_id not in portrait_map:
                portrait_map[entity_id] = file_path

    char_views = []
    for c in characters:
        portrait_path = portrait_map.get(c.id)
        char_views.append({
            "id": c.id,
            "name": c.name,
            "role": c.role,
            "description": c.description,
            "visual_appearance": c.visual_appearance,
            "sex": getattr(c, "sex", None),
            "pronouns": getattr(c, "pronouns", None),
            "portrait_url": f"/assets/images/{portrait_path}" if portrait_path else None,
            "is_alive": c.is_alive,
            "introduced_at_chapter": c.introduced_at_chapter,
            "power_rank": rank_by_char.get(c.id),
            "relationship_count": rel_counts.get(c.id, 0),
            "faction_id": c.faction_id,
        })

    ctx["characters"] = char_views
    ctx["role_filter"] = role
    ctx["roles"] = ["protagonist", "antagonist", "mentor", "ally", "rival", "neutral"]

    return _templates(request).TemplateResponse("pages/character_gallery.html", ctx)


@router.get(
    "/novels/{novel_id}/characters/{char_id}",
    response_class=HTMLResponse,
)
async def character_detail_page(
    novel_id: int,
    char_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Character detail page — portrait, stats, relationships, power progression."""
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

    # Character with eager loads
    from aiwebnovel.db.queries import get_character_full

    character = await get_character_full(db, char_id)
    if character is None or character.novel_id != novel_id:
        return _templates(request).TemplateResponse(
            "pages/404.html",
            {**ctx, "message": "Character not found"},
            status_code=404,
        )
    ctx["character"] = character

    # Portrait image + asset object for regeneration
    portrait_stmt = (
        select(ArtAsset)
        .where(
            ArtAsset.entity_id == char_id,
            ArtAsset.entity_type == "character",
            ArtAsset.asset_type == "portrait",
            ArtAsset.is_current.is_(True),
        )
        .order_by(ArtAsset.created_at.desc())
        .limit(1)
    )
    portrait_asset = (await db.execute(portrait_stmt)).scalar_one_or_none()
    ctx["portrait_url"] = (
        f"/assets/images/{portrait_asset.file_path}"
        if portrait_asset and portrait_asset.file_path else None
    )
    ctx["portrait_asset"] = portrait_asset

    # Power profile with rank details
    pp_stmt = (
        select(CharacterPowerProfile)
        .where(CharacterPowerProfile.character_id == char_id)
    )
    profile = (await db.execute(pp_stmt)).scalar_one_or_none()
    if profile:
        rank = (
            await db.execute(
                select(PowerRank).where(PowerRank.id == profile.current_rank_id)
            )
        ).scalar_one_or_none()
        ctx["power_profile"] = {
            "rank_name": rank.rank_name if rank else "Unknown",
            "rank_description": rank.description if rank else None,
        }
    else:
        ctx["power_profile"] = None

    # Relationships
    rel_stmt = (
        select(CharacterRelationship)
        .where(
            or_(
                CharacterRelationship.character_a_id == char_id,
                CharacterRelationship.character_b_id == char_id,
            )
        )
        .order_by(CharacterRelationship.intensity.desc())
    )
    relationships_raw = (await db.execute(rel_stmt)).scalars().all()

    # Batch-fetch all related characters in one query
    other_ids = list({
        rel.character_b_id if rel.character_a_id == char_id else rel.character_a_id
        for rel in relationships_raw
    })
    if other_ids:
        other_chars = (
            await db.execute(select(Character).where(Character.id.in_(other_ids)))
        ).scalars().all()
        char_by_id = {c.id: c for c in other_chars}
    else:
        char_by_id = {}

    relationships = []
    for rel in relationships_raw:
        other_id = rel.character_b_id if rel.character_a_id == char_id else rel.character_a_id
        other = char_by_id.get(other_id)
        if other:
            relationships.append({
                "other_id": other.id,
                "other_name": other.name,
                "other_role": other.role,
                "relationship_type": rel.relationship_type,
                "description": rel.description,
                "intensity": rel.intensity,
                "sentiment": rel.sentiment,
                "status": rel.status,
            })
    ctx["relationships"] = relationships

    # Faction info
    if character.faction_id:
        faction = (
            await db.execute(
                select(Faction).where(Faction.id == character.faction_id)
            )
        ).scalar_one_or_none()
        ctx["faction"] = faction
    else:
        ctx["faction"] = None

    # Current region
    if character.current_region_id:
        region = (
            await db.execute(
                select(Region).where(Region.id == character.current_region_id)
            )
        ).scalar_one_or_none()
        ctx["current_region"] = region
    else:
        ctx["current_region"] = None

    return _templates(request).TemplateResponse("pages/character_detail.html", ctx)
