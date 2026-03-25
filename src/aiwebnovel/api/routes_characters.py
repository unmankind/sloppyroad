"""Character gallery and relationship routes."""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import Character, CharacterPowerProfile, CharacterRelationship
from aiwebnovel.db.queries import get_character_full, get_characters_for_novel
from aiwebnovel.db.schemas import CharacterList, CharacterPowerProfileRead, CharacterRead
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────


class RelationshipRead(BaseModel):
    id: int
    character_a_id: int
    character_b_id: int
    relationship_type: str
    description: Optional[str] = None
    intensity: float
    sentiment: float
    status: str

    class Config:
        from_attributes = True


class RelationshipGraphResponse(BaseModel):
    relationships: list[RelationshipRead]
    characters: list[CharacterList]


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/{novel_id}/characters", response_model=list[CharacterList])
async def list_characters(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[CharacterList]:
    """Character gallery — lists characters introduced so far."""
    characters = await get_characters_for_novel(db, novel_id, alive_only=False)
    return [CharacterList.model_validate(c) for c in characters]


@router.get("/{novel_id}/characters/{char_id}", response_model=CharacterRead)
async def get_character(
    novel_id: int,
    char_id: int,
    db: AsyncSession = Depends(get_db),
) -> CharacterRead:
    """Get character detail."""
    character = await get_character_full(db, char_id)
    if character is None or character.novel_id != novel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    return CharacterRead.model_validate(character)


@router.get("/{novel_id}/characters/{char_id}/power", response_model=CharacterPowerProfileRead)
async def get_character_power(
    novel_id: int,
    char_id: int,
    db: AsyncSession = Depends(get_db),
) -> CharacterPowerProfileRead:
    """Get character power progression data."""
    stmt = select(CharacterPowerProfile).where(CharacterPowerProfile.character_id == char_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Power profile not found for this character",
        )

    # Verify character belongs to this novel
    char_stmt = select(Character.novel_id).where(Character.id == char_id)
    char_result = await db.execute(char_stmt)
    char_novel_id = char_result.scalar_one_or_none()
    if char_novel_id != novel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found in this novel",
        )

    return CharacterPowerProfileRead.model_validate(profile)


@router.get("/{novel_id}/relationships", response_model=RelationshipGraphResponse)
async def get_relationships(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
) -> RelationshipGraphResponse:
    """Relationship data for graph visualization."""
    # Get all characters for the novel
    characters = await get_characters_for_novel(db, novel_id, alive_only=False)
    char_ids = [c.id for c in characters]

    # Get relationships between characters in this novel
    if char_ids:
        stmt = select(CharacterRelationship).where(
            CharacterRelationship.character_a_id.in_(char_ids),
            CharacterRelationship.character_b_id.in_(char_ids),
        )
        result = await db.execute(stmt)
        relationships = result.scalars().all()
    else:
        relationships = []

    return RelationshipGraphResponse(
        relationships=[RelationshipRead.model_validate(r) for r in relationships],
        characters=[CharacterList.model_validate(c) for c in characters],
    )
